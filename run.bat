@echo off
chcp 65001 >nul
set "ROOT_DIR=%~dp0"
set "EXE_PATH=%ROOT_DIR%PDFMerger.exe"

if exist "%EXE_PATH%" (
    start "" "%EXE_PATH%" %*
) else if exist "%ROOT_DIR%dist\PDFMerger.exe" (
    start "" "%ROOT_DIR%dist\PDFMerger.exe" %*
) else if exist "%ROOT_DIR%dist\PDFMerger\PDFMerger.exe" (
    start "" "%ROOT_DIR%dist\PDFMerger\PDFMerger.exe" %*
) else (
    where pyw >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        start "" pyw -3 "%ROOT_DIR%src\app.py" %*
    ) else (
        where pythonw >nul 2>nul
        if %ERRORLEVEL% EQU 0 (
            start "" pythonw "%ROOT_DIR%src\app.py" %*
        ) else (
            start "" python "%ROOT_DIR%src\app.py" %*
        )
    )
)
