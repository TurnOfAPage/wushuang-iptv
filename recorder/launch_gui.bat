@echo off
rem GUI bootstrap: locate self dir then launch hidden vbs (pure ASCII).
cd /d "%~dp0"
start "" wscript.exe recorder_gui.vbs
