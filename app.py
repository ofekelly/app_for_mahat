# app.py
# Streamlit Prompt+Response Labeling (Human vs Machine) — supports Excel (.xlsx/.xls) and CSV
import streamlit as st
import pandas as pd
import numpy as np
import io
import hashlib
import os
from datetime import datetime, timezone

st.set_page_config(page_title="תיוג אדם/מכונה לתשובות", page_icon="🔎", layout="centered")

DEFAULT_K = 10
try:
    _SECRETS = st.secrets
except Exception:
    _SECRETS = {}
def _sec_get(key, default=None):
    try:
        return _SECRETS.get(key, default)
    except Exception:
        return default
SURVEY_ID = _sec_get("survey_id", "default_survey")
STORAGE_MODE = _sec_get("storage_mode", "csv")
ADMIN_PASSWORD = _sec_get("admin_password")
GSHEETS = _sec_get("gsheets", {})

def _now_iso():
    return datetime.now(timezone.utc).isoformat()
def _stable_sample_seed(respondent_id: str, survey_id: str) -> int:
    digest = hashlib.sha256(f"{respondent_id}::{survey_id}".encode("utf-8")).hexdigest()
    return int(digest[:8], 16)
def _norm_truth(v):
    if v is None: return None
    s = str(v).strip().lower()
    if s in ["human","אדם","1","true","yes","y"]: return "human"
    if s in ["machine","מכונה","0","false","no","n","ai","model"]: return "machine"
    return None

def _read_items_from_excel(file_bytes: bytes, filename: str = "") -> pd.DataFrame:
    ext = os.path.splitext(filename.lower())[1]
    if ext == ".csv":
        df = pd.read_csv(io.BytesIO(file_bytes))
    else:
        # Explicit engine improves reliability on Streamlit Cloud
        df = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl")
    cols_lower = {c.lower(): c for c in df.columns}
    prompt_col = None
    for cand in ["test_prompt","prompt","פרומפט","שאלה","טקסט"]:
        if cand in cols_lower: prompt_col = cols_lower[cand]; break
    resp_col = None
    for cand in ["response","תשובה","answer","טקסט_תשובה"]:
        if cand in cols_lower: resp_col = cols_lower[cand]; break
    if prompt_col is None or resp_col is None:
        if df.shape[1] >= 2 and prompt_col is None and resp_col is None:
            prompt_col, resp_col = df.columns[0], df.columns[1]
        else:
            raise ValueError("חובה עמודות 'test_prompt' ו-'response'.")
    truth_col = None
    for cand in ["ground_truth","truth","label","gt","is_human","מקור"]:
        if cand in cols_lower: truth_col = cols_lower[cand]; break
    df = df.rename(columns={prompt_col:"test_prompt", resp_col:"response"})
    if truth_col: df = df.rename(columns={truth_col:"ground_truth"})
    df["test_prompt"] = df["test_prompt"].astype(str).str.strip()
    df["response"] = df["response"].astype(str).str.strip()
    df = df[(df["test_prompt"].str.len()>0) & (df["response"].str.len()>0)].copy()
    if "id" not in df.columns: df.insert(0,"id", range(1,len(df)+1))
    else: df["id"] = df["id"].astype(str).str.strip()
    if "ground_truth" in df.columns: df["ground_truth"] = df["ground_truth"].apply(_norm_truth)
    else: df["ground_truth"] = None
    return df[["id","test_prompt","response","ground_truth"]].reset_index(drop=True)

class CsvStorage:
    def __init__(self):
        self.responses_csv = "responses.csv"
        self.assign_csv = "assignments.csv"
        for path, columns in [
            (self.responses_csv, ["timestamp_utc","survey_id","respondent_id","item_id","label","label_bin","prompt","response","truth","correct"]),
            (self.assign_csv, ["timestamp_utc","survey_id","respondent_id","k","item_ids"]),
        ]:
            try: pd.read_csv(path)
            except Exception: pd.DataFrame(columns=columns).to_csv(path, index=False)
    def save_assignment(self, survey_id, respondent_id, k, item_ids):
        df = pd.read_csv(self.assign_csv)
        df = pd.concat([df, pd.DataFrame([{
            "timestamp_utc": _now_iso(),
            "survey_id": survey_id,
            "respondent_id": respondent_id,
            "k": int(k),
            "item_ids": ",".join(map(str, item_ids)),
        }])], ignore_index=True)
        df.to_csv(self.assign_csv, index=False)
    def has_responses(self, survey_id, respondent_id):
        try: df = pd.read_csv(self.responses_csv)
        except Exception: return False
        if df.empty: return False
        return ((df["survey_id"]==survey_id) & (df["respondent_id"]==respondent_id)).any()
    def save_responses(self, rows):
        df = pd.read_csv(self.responses_csv)
        df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
        df.to_csv(self.responses_csv, index=False)
    def load_responses(self):
        try: return pd.read_csv(self.responses_csv)
        except Exception:
            return pd.DataFrame(columns=["timestamp_utc","survey_id","respondent_id","item_id","label","label_bin","prompt","response","truth","correct"])

def get_storage():
    if STORAGE_MODE == "gsheets":
        try:
            import gspread
            from google.oauth2.service_account import Credentials
        except Exception:
            st.error("מצב gsheets דורש gspread ו-google-auth + secrets תקינים.")
            st.stop()
        cfg = GSHEETS
        creds_json = cfg.get("credentials")
        rsp_url = cfg.get("responses_sheet_url")
        asg_url = cfg.get("assignments_sheet_url")
        if not creds_json or not rsp_url or not asg_url:
            st.error("חסר gsheets.credentials/urls ב-secrets.")
            st.stop()
        scopes = ["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
        credentials = Credentials.from_service_account_info(creds_json, scopes=scopes)
        gc = gspread.authorize(credentials)
        responses_sh = gc.open_by_url(rsp_url).sheet1
        assignments_sh = gc.open_by_url(asg_url).sheet1
        if len(responses_sh.get_all_values())==0:
            responses_sh.append_row(["timestamp_utc","survey_id","respondent_id","item_id","label","label_bin","prompt","response","truth","correct"])
        if len(assignments_sh.get_all_values())==0:
            assignments_sh.append_row(["timestamp_utc","survey_id","respondent_id","k","item_ids"])
        class GSheetsStorage:
            def save_assignment(self, survey_id, respondent_id, k, item_ids):
                assignments_sh.append_row([_now_iso(), survey_id, respondent_id, int(k), ",".join(map(str, item_ids))])
            def has_responses(self, survey_id, respondent_id):
                vals = responses_sh.col_values(2)
                vals2 = responses_sh.col_values(3)
                for s, r in zip(vals[1:], vals2[1:]):
                    if s==survey_id and r==respondent_id: return True
                return False
            def save_responses(self, rows):
                to_rows = [[r["timestamp_utc"], r["survey_id"], r["respondent_id"], r["item_id"], r["label"], r["label_bin"], r["prompt"], r["response"], r["truth"], r["correct"]] for r in rows]
                responses_sh.append_rows(to_rows)
            def load_responses(self):
                data = responses_sh.get_all_records()
                return pd.DataFrame(data)
        return GSheetsStorage()
    return CsvStorage()

def admin_panel():
    st.subheader("📋 הגדרות (Admin)")
    st.caption("טען Excel/CSV עם 'test_prompt' ו-'response'. אפשרי 'ground_truth' (human/machine או 1/0).")
    uploaded = st.file_uploader("טעינת מאגר (Excel/CSV: xlsx/xls/csv)", type=["xlsx","xls","csv"])
    k = st.number_input("כמה פריטים לכל נבדק (K)?", min_value=1, value=st.session_state.get("k", DEFAULT_K), step=1)
    survey_id = st.text_input("Survey ID", value=st.session_state.get("survey_id", SURVEY_ID))
    if "items_df" not in st.session_state: st.session_state["items_df"] = None
    if uploaded:
        try:
            df = _read_items_from_excel(uploaded.getvalue(), uploaded.name)
            st.session_state["items_df"] = df
            st.success(f"נטענו {len(df)} פריטים.")
            st.dataframe(df.head(20))
            if df["ground_truth"].notna().any(): st.info("התגלתה ground_truth — יוצגו מדדי דיוק לאחר שליחה.")
        except Exception as e:
            st.error(f"שגיאה בקריאת הקובץ: {e}")
    st.session_state["k"] = int(k)
    st.session_state["survey_id"] = survey_id
    st.markdown("**קישור לשיתוף (לאחר פריסה/שיתוף):**")
    st.code("http://YOUR-APP/?sid=YOUR_SURVEY_ID&rid=USER123", language="bash")
    st.divider()
    st.subheader("⬇️ הורדת כל התשובות")
    if st.button("ייצא כל התשובות ל-CSV"):
        storage = get_storage()
        df_all = storage.load_responses()
        if df_all.empty:
            st.warning("אין תשובות עדיין.")
        else:
            st.download_button("הורד responses.csv", data=df_all.to_csv(index=False).encode("utf-8"), file_name="responses_export.csv", mime="text/csv")

def run_task():
    sid = st.query_params.get("sid", [st.session_state.get("survey_id", SURVEY_ID)])
    if isinstance(sid, list): sid = sid[0]
    rid = st.query_params.get("rid", [""])
    if isinstance(rid, list): rid = rid[0]
    st.header("תיוג תשובות: אדם או מכונה?")
    st.write("לכל פריט מוצגים פרומפט ותשובה. סמנו אם לדעתכם נכתב ע\"י **אדם** או **מכונה**.")
    respondent_id = st.text_input("RID (מזהה נבדק)", value=rid, help="אפשר אימייל או מזהה פנימי.")
    k = st.session_state.get("k", DEFAULT_K)
    k = st.number_input("כמה פריטים תקבל/י (K)", min_value=1, value=int(k), step=1)
    df = st.session_state.get("items_df")
    if df is None:
        st.warning("המאגר טרם נטען (Admin). העלה קובץ במצב Admin.")
        return
    if not respondent_id.strip():
        st.info("יש להזין RID כדי להתחיל.")
        return
    if k > len(df):
        st.error(f"K ({k}) גדול ממספר הפריטים ({len(df)}).")
        return
    seed = _stable_sample_seed(respondent_id.strip(), sid)
    rng = np.random.default_rng(seed)
    sample_idx = rng.choice(len(df), size=int(k), replace=False)
    sample_df = df.iloc[sample_idx].copy().reset_index(drop=True)
    st.subheader("הפריטים שלך")
    labels = []
    for i, row in sample_df.iterrows():
        with st.container(border=True):
            st.markdown(f"**פריט {i+1}** (ID: {row['id']})")
            with st.expander("📜 Prompt", expanded=True):
                st.write(row["test_prompt"])
            with st.expander("📝 Response", expanded=True):
                st.write(row["response"])
            choice = st.radio("מי כתב את התשובה?", options=["אדם","מכונה"], index=None, key=f"lbl_{row['id']}", horizontal=True)
            labels.append({"id": row["id"], "prompt": row["test_prompt"], "response": row["response"], "label": choice, "truth": row.get("ground_truth", None)})
    submitted = st.button("שליחה")
    if submitted:
        if any(l["label"] is None for l in labels):
            st.warning("יש לענות על כל הפריטים לפני שליחה.")
            return
        storage = get_storage()
        if storage.has_responses(sid, respondent_id.strip()):
            st.error("כבר קיימות תשובות עבור RID זה בסקר הזה. לשכפול ניסיון יש לשנות SID או RID.")
            return
        storage.save_assignment(sid, respondent_id.strip(), int(k), [l["id"] for l in labels])
        rows = []
        for l in labels:
            lab_norm = "human" if l["label"] == "אדם" else "machine"
            truth = l["truth"]
            correct = None
            if truth in ["human","machine"]: correct = 1 if lab_norm == truth else 0
            rows.append({
                "timestamp_utc": _now_iso(),
                "survey_id": sid,
                "respondent_id": respondent_id.strip(),
                "item_id": l["id"],
                "label": lab_norm,
                "label_bin": 1 if lab_norm == "human" else 0,
                "prompt": l["prompt"],
                "response": l["response"],
                "truth": truth if truth in ["human","machine"] else None,
                "correct": correct,
            })
        storage.save_responses(rows)
        st.success("התשובות נקלטו! תודה 🙏")
        st.balloons()
        st.subheader("🔎 סיכום אישי")
        df_me = pd.DataFrame(rows)
        st.write(f"מספר פריטים: **{len(df_me)}**")
        st.write(f"אחוז 'אדם' שסומנו: **{(df_me['label_bin'].mean()*100):.1f}%**")
        if df_me["truth"].notna().any():
            df_truth = df_me.dropna(subset=["truth"]).copy()
            acc = (df_truth["label"] == df_truth["truth"]).mean() if not df_truth.empty else None
            if acc is not None:
                st.write(f"דיוק (אם קיימת אמת-מידה): **{acc*100:.1f}%**")
                cm = pd.crosstab(df_truth["truth"], df_truth["label"], dropna=False)
                st.dataframe(cm)
        st.download_button(
            "הורד CSV של התיוגים שלך",
            data=df_me.to_csv(index=False).encode("utf-8"),
            file_name=f"labels_{sid}_{respondent_id.strip()}.csv",
            mime="text/csv"
        )

st.title("🔎 תיוג אדם/מכונה לתשובות")
mode = st.sidebar.selectbox("מצב", ["Respondent", "Admin"])
if mode == "Admin":
    if ADMIN_PASSWORD:
        pw = st.sidebar.text_input("סיסמת אדמין", type="password")
        if pw != ADMIN_PASSWORD:
            st.warning("נדרש להזין סיסמת אדמין תקפה.")
            st.stop()
    admin_panel()
run_task()
st.markdown("---")
st.caption("נוצר ע\"י ChatGPT • Streamlit • שמירה ל-CSV מקומי או ל-Google Sheets (secrets).")