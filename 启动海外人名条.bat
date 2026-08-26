@echo off
chcp 65001 >nul
rem ====================================================
rem  海外人名条批量生成 - 启动器
rem  双击此文件打开界面
rem ====================================================
set "SCRIPT_DIR=%~dp0"
set "PYW=%SCRIPT_DIR%..\.venv\Scripts\pythonw.exe"

if not exist "%PYW%" (
    echo 未找到 pythonw.exe, 请确认 venv 存在: %PYW%
    pause
    exit /b 1
)

start "" "%PYW%" "%SCRIPT_DIR%gui_batch.pyw"
