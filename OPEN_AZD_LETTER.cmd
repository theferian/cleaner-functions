@echo off
cd /d "%~dp0"
python ".\tools\adaptive_document_reader\open_letter_in_reader.py" %*
if errorlevel 1 pause
