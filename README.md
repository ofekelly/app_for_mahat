# Streamlit Prompt+Response Labeling — Excel/CSV

- מגריל K פריטים מתוך Excel/CSV (`test_prompt`, `response`)
- תיוג אדם/מכונה
- שמירה ל-CSV לוקלי (ברירת מחדל) או Google Sheets (אם מגדירים secrets)

## ריצה לוקלית
```bash
pip install -r requirements.txt
streamlit run app.py
```

## פריסה חינמית: Streamlit Cloud
- העלה ל-GitHub → Deploy → קבל URL ציבורי לשיתוף
- ללא Google Sheets הנתונים בענן זמניים; הורד CSV מ-Admin בסיום

## קלט
- חובה: `test_prompt`, `response`
- אופציונלי: `ground_truth`, `id`
- נתמך: `.xlsx`, `.xls`, `.csv`