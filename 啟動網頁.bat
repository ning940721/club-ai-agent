@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 社團 AI 營運顧問

echo [1/3] 正在取得最新版本...
git pull
if errorlevel 1 echo     （無法更新，先用目前的版本啟動）

echo [2/3] 正在檢查需要的套件...
python -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo     套件安裝失敗，請把上面的訊息貼給 Claude
    pause
    exit /b 1
)

echo [3/3] 正在啟動網頁，瀏覽器會自動打開。
echo     要停止網頁：直接關閉這個視窗。
python -m streamlit run app.py
pause
