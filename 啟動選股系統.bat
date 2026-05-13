@echo off
chcp 65001 > nul
echo.
echo  ===================================
echo   SuperTREX 選股系統  啟動中...
echo  ===================================
echo.
cd /d "%~dp0"
py -m streamlit run app.py --server.port 8501 --server.headless false
pause
