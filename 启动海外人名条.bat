@echo off
chcp 65001 >nul
rem ====================================================
rem  海外人名条批量生成 - 启动器
rem  双击此文件打开界面
rem ====================================================
set "SCRIPT_DIR=%~dp0"
set "PYW=pythonw.exe"

rem 优先使用本目录 venv（若存在），否则用系统 pythonw
if exist "%SCRIPT_DIR%\.venv\Scripts\pythonw.exe" (
    set "PYW=%SCRIPT_DIR%\.venv\Scripts\pythonw.exe"
)

rem 检查依赖是否已安装
"%PYW%" -c "import uiautomation, tkinter" >nul 2>&1
if errorlevel 1 (
    echo [提示] 首次运行需要安装依赖: uiautomation
    echo 请在命令行运行:  pip install -r "%SCRIPT_DIR%requirements.txt"
    echo.
    echo 按任意键退出...
    pause >nul
    exit /b 1
)

start "" "%PYW%" "%SCRIPT_DIR%gui_batch.pyw"
