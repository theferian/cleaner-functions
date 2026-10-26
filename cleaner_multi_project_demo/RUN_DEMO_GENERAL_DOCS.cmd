@echo off
setlocal
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
py .\DEMO_ALL_GENERAL_DOCS.py --status-date 1405/07/30 --batch DEMO_14050730
set "RC=%ERRORLEVEL%"
echo.
echo Demo return code: %RC%  [0 complete, 2 review/incomplete, 1 error]
echo Open: "%CD%\demo_review\DEMO_14050730\index.html"
exit /b %RC%
