@echo off
cd /d "%~dp0"
if not exist .venv python -m venv .venv
.venv\Scripts\python -m pip install -q -r requirements.txt
.venv\Scripts\python -m PyInstaller --noconfirm --onefile --windowed --name MarkdownViewer --add-data "ui.html;." --add-data "vendor;vendor" --add-data "print.js;." mdviewer.py
echo.
echo dist\MarkdownViewer.exe
