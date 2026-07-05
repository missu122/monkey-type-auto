@echo off
echo Installing Tesseract OCR through winget...
echo.
winget install --id UB-Mannheim.TesseractOCR --source winget --accept-package-agreements --accept-source-agreements
echo.
echo If installation finished successfully, close and reopen Text Typer.
pause
