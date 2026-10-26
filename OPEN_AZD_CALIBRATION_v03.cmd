@echo off
setlocal
cd /d "%~dp0"
python ".\tools\adaptive_document_reader\calibrate_letter_in_reader_v03.py" %*
endlocal
