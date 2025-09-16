@echo off
set PORT=8501
set ADDRESS=0.0.0.0
if exist "%~dp0venv\Scripts\activate.bat" (
    call "%~dp0venv\Scripts\activate.bat"
)
streamlit run "%~dp0app.py" --server.address %ADDRESS% --server.port %PORT%
