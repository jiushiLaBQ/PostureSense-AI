@echo off
REM ============================================================
REM  智姿 AI (PostureSense AI) 一键启动脚本 —— 源码环境
REM
REM  用法: 双击本文件，或命令行执行 start_posturesense.bat
REM  冻结包用户: 直接双击 dist\PostureSenseAI\PostureSenseAI.exe，无需本脚本
REM
REM  注意: 本文件必须是 CRLF 换行（cmd.exe 对 LF 括号块解析有 bug）
REM ============================================================
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 goto no_python

REM 排除 Microsoft Store 别名桩（where 能找到但不能用）
call python -c "import sys" >nul 2>nul
if errorlevel 1 goto no_python

call python -c "import posturesense" >nul 2>nul
if errorlevel 1 (
    echo [错误] posturesense 未安装。
    echo        请先执行: pip install -e .
    pause
    exit /b 2
)

call python -m posturesense %*
set RC=%ERRORLEVEL%
if not "%RC%"=="0" (
    echo.
    echo [提示] 程序退出码 %RC%。常见问题见 README.md 故障排查一节。
    pause
)
exit /b %RC%

:no_python
echo [错误] 未找到可用的 python。
echo        请安装 Python 3.12+ 并加入 PATH；
echo        若已安装请关闭"应用执行别名"中的 Microsoft Store python 桩。
pause
exit /b 1
