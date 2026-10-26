@echo off
cd /d "%~dp0"
python ".\tools\adaptive_document_reader\card_verification_dashboard_v03.py" --run-dir ".\runs\azd_20261014T071802" --source-root "W:\00-1403\1403-02-05-230kV Azad\Letter\technical" --focus-ref "1404/ES/S/3003" --tesseract "C:\Program Files\Tesseract-OCR\tesseract.exe"
