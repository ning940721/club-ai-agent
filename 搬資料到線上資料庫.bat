@echo off
chcp 65001 >nul
title 搬資料到線上資料庫
cd /d "%~dp0"
echo 這會把這台電腦上的社團資料（data 資料夾）複製到線上資料庫，電腦上的資料不會被刪除。
echo 線上已經有的社團帳號會略過，不會被覆蓋。
echo.
python -m pip install -q --disable-pip-version-check -r requirements.txt
set PYTHONPATH=%~dp0src
python -m club_agent.migrate
echo.
pause
