
# app.py
import streamlit as st
import pandas as pd
import numpy as np
import io, os, hashlib
from datetime import datetime, timezone

st.set_page_config(page_title="תיוג אדם/מכונה לתשובות", page_icon="🔎", layout="centered")

DEFAULT_K = 10
try:
    _SECRETS = st.secrets
except Exception:
    _SECRETS = {}
def _sec_get(key, default=None):
    try: return _SECRETS.get(key, default)
    except Exception: return default
SURVEY_ID = _sec_get("survey_id", "default_survey")
ADMIN_PASSWORD = _sec_get("admin_password")

def _now_iso(): return datetime.now(timezone.utc).isoformat()
def _stable_sample_seed(rid: str, sid: str) -> int:
    digest = hashlib.sha256(f"{rid}::{sid}".encode("utf-8")).hexdigest()
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
        df = pd.read_excel(io.BytesIO(file_bytes), engine="openpyxl")
    cols_lower = {c.lower(): c for c in df.columns}
    prompt_col = next((cols_lower[c] for c in ["test_prompt","prompt","פרומפט","שאלה","טקסט"] if c in cols_lower), None)
    resp_col = next((cols_lower[c] for c in ["response","תשובה","answer","טקסט_תשובה"] if c in cols_lower), None)
    if not prompt_col or not resp_col:
        if df.shape[1] >= 2 and not prompt_col and not resp_col:
            prompt_col, resp_col = df.columns[0], df.columns[1]
        else:
            raise ValueError("חובה עמודות 'test_prompt' ו-'response'.")
    truth_col = next((cols_lower[c] for c in ["ground_truth","truth","label","gt","is_human","מקור"] if c in cols_lower), None)
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

@st.cache_resource
def datasets_cache():
    return {}

DATA_DIR = "datasets"
os.makedirs(DATA_DIR, exist_ok=True)
def save_items_to_disk(df: pd.DataFrame, sid: str):
    if not sid: return
    df.to_csv(os.path.join(DATA_DIR, f"{sid}.csv"), index=False)
def load_items_from_disk(sid: str):
    p = os.path.join(DATA_DIR, f"{sid}.csv")
    if not os.path.exists(p): return None
    df = pd.read_csv(p)
    if "ground_truth" not in df.columns: df["ground_truth"] = None
    if "id" not in df.columns: df.insert(0,"id", range(1,len(df)+1))
    return df[["id","test_prompt","response","ground_truth"]]

class CsvStorage:
    def __init__(self):
        self.responses_csv = "responses.csv"
        self.assign_csv = "assignments.csv"
        for path, cols in [
            (self.responses_csv, ["timestamp_utc","survey_id","respondent_id","item_id","label","label_bin","prompt","response","truth","correct"]),
            (self.assign_csv, ["timestamp_utc","survey_id","respondent_id","k","item_ids"]),
        ]:
            try: pd.read_csv(path)
            except Exception: pd.DataFrame(columns=cols).to_csv(path, index=False)
    def save_assignment(self, sid, rid, k, item_ids):
        df = pd.read_csv(self.assign_csv)
        df = pd.concat([df, pd.DataFrame([{
            "timestamp_utc": _now_iso(), "survey_id": sid, "respondent_id": rid, "k": int(k),
            "item_ids": ",".join(map(str, item_ids)),
        }])], ignore_index=True)
        df.to_csv(self.assign_csv, index=False)
    def has_responses(self, sid, rid):
        try: df = pd.read_csv(self.responses_csv)
        except Exception: return False
        if df.empty: return False
        return ((df["survey_id"]==sid) & (df["respondent_id"]==rid)).any()
    def save_responses(self, rows):
        df = pd.read_csv(self.responses_csv)
        df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
        df.to_csv(self.responses_csv, index=False)
    def load_responses(self):
        try: return pd.read_csv(self.responses_csv)
        except Exception:
            return pd.DataFrame(columns=["timestamp_utc","survey_id","respondent_id","item_id","label","label_bin","prompt","response","truth","correct"])

def get_storage(): return CsvStorage()

def admin_panel():
    st.subheader("📋 הגדרות (Admin)")
    uploaded = st.file_uploader("טעינת מאגר (Excel/CSV: xlsx/xls/csv)", type=["xlsx","xls","csv"])
    k = st.number_input("כמה פריטים לכל נבדק (K)?", min_value=1, value=st.session_state.get("k", DEFAULT_K), step=1)
    survey_id = st.text_input("Survey ID", value=st.session_state.get("survey_id", SURVEY_ID))
    if "items_df" not in st.session_state: st.session_state["items_df"] = None
    if uploaded:
        try:
            df = _read_items_from_excel(uploaded.getvalue(), uploaded.name)
            st.session_state["items_df"] = df
            datasets_cache()[survey_id] = df
            save_items_to_disk(df, survey_id)
            st.success(f"נטענו {len(df)} פריטים ונשמרו לשרת.")
            st.dataframe(df.head(20))
        except Exception as e:
            st.error(f"שגיאה בקריאת הקובץ: {e}")
    st.session_state["k"] = int(k)
    st.session_state["survey_id"] = survey_id
    if st.session_state.get("items_df") is not None and st.button("שמירת המאגר לשרת (לפי Survey ID)"):
        datasets_cache()[survey_id] = st.session_state["items_df"]
        save_items_to_disk(st.session_state["items_df"], survey_id)
        st.success("נשמר לשרת — כעת Respondent עם אותו sid יראו את המאגר.")
    st.markdown("**קישור לשיתוף (לאחר פריסה/שיתוף):**")
    st.code("http://YOUR-APP/?sid=YOUR_SURVEY_ID&rid=USER123", language="bash")

def run_task():
    sid = st.query_params.get("sid", [st.session_state.get("survey_id", SURVEY_ID)])
    if isinstance(sid, list): sid = sid[0]
    rid = st.query_params.get("rid", [""])
    if isinstance(rid, list): rid = rid[0]
    st.header("תיוג תשובות: אדם או מכונה?")
    st.write("לכל פריט מוצגים פרומפט ותשובה. סמנו אם לדעתכם נכתב ע"י **אדם** או **מכונה**.")
    respondent_id = st.text_input("RID (מזהה נבדק)", value=rid, help="אפשר אימייל או מזהה פנימי.")
    k = st.session_state.get("k", DEFAULT_K)
    k = st.number_input("כמה פריטים תקבל/י (K)", min_value=1, value=int(k), step=1)

    df = st.session_state.get("items_df")
    if df is None:
        df = datasets_cache().get(sid)
    if df is None:
        df = load_items_from_disk(sid)
    if df is None:
        st.warning("המאגר טרם נטען (Admin). העלה קובץ במצב Admin, או ודא שה-Survey ID נכון.")
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
            correct = 1 if (truth in ["human","machine"] and lab_norm == truth) else None
            rows.append({
                "timestamp_utc": _now_iso(),
                "survey_id": sid, "respondent_id": respondent_id.strip(),
                "item_id": l["id"], "label": lab_norm, "label_bin": 1 if lab_norm == "human" else 0,
                "prompt": l["prompt"], "response": l["response"], "truth": truth, "correct": correct,
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
                import pandas as pd
                cm = pd.crosstab(df_truth["truth"], df_truth["label"], dropna=False)
                st.dataframe(cm)
        st.download_button("הורד CSV של התיוגים שלך", data=df_me.to_csv(index=False).encode("utf-8"),
                           file_name=f"labels_{sid}_{respondent_id.strip()}.csv", mime="text/csv")

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
st.caption("נוצר ע"י ChatGPT • Persist by SID (cache+disk) • CSV/Excel נתמך.")
    