@echo off
rem Wushuang IPTV Recorder - CLI entry.
rem Prefer py launcher -> installed Python (AV-trusted chain); else bundled runtime.
rem Keep this file pure ASCII (cmd parses ANSI; UTF-8 comments can break lines).
setlocal
set BASE=%~dp0
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%BASE%app\recorder\rec_cli.py" %*
) else (
  "%BASE%python\python.exe" "%BASE%app\recorder\rec_cli.py" %*
)
exit /b %errorlevel%
