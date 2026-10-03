@echo off
chcp 65001 >nul
title 社團 AI 營運顧問

rem 先找專案資料夾：優先用這個檔案所在的資料夾，找不到時改用預設位置
set "PROJECT=%~dp0"
if not exist "%PROJECT%app.py" set "PROJECT=%USERPROFILE%\club-ai-agent\"
if not exist "%PROJECT%app.py" (
    echo 找不到專案資料夾。
    echo 請把這個檔案放回 club-ai-agent 資料夾裡，再用「建立捷徑」放到桌面。
    pause
    exit /b 1
)
cd /d "%PROJECT%"
echo 專案資料夾：%CD%

echo [1/3] 正在取得最新版本...
git pull
if errorlevel 1 echo     （無法更新，先用目前的版本啟動）

echo [2/3] 正在檢查需要的套件...
python -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo     套件安裝失敗，請把上面的訊息貼給 Claude
    pause
    exit /b 1
)

echo [3/3] 正在啟動網頁，瀏覽器會自動打開。
echo     要停止網頁：直接關閉這個視窗。
python -m streamlit run app.py
pause
