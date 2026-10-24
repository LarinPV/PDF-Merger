@echo off
chcp 65001 >nul
echo ======================================================================
echo          PDF Merger - Uninstall Context Menu
echo ======================================================================
echo.

set "ROOT_DIR=%~dp0"
set "EXE_PATH=%ROOT_DIR%PDFMerger.exe"
if exist "%EXE_PATH%" goto USE_EXE

set "EXE_PATH=%ROOT_DIR%dist\PDFMerger.exe"
if exist "%EXE_PATH%" goto USE_EXE

set "EXE_PATH=%ROOT_DIR%dist\PDFMerger\PDFMerger.exe"
if exist "%EXE_PATH%" goto USE_EXE

rem Fallback to Python if binary is not present
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [+] Running via py launcher: py -3 "%ROOT_DIR%src\app.py" --uninstall
    py -3 "%ROOT_DIR%src\app.py" --uninstall
    goto CHECK_RESULT
)

where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [+] Running via python: python "%ROOT_DIR%src\app.py" --uninstall
    python "%ROOT_DIR%src\app.py" --uninstall
    goto CHECK_RESULT
)

echo [-] Ошибка: Не найден ни PDFMerger.exe, ни установленный Python в системе.
goto ERROR_EXIT

:USE_EXE
echo [+] Running: "%EXE_PATH%" --uninstall
"%EXE_PATH%" --uninstall
goto CHECK_RESULT

:CHECK_RESULT
if %ERRORLEVEL% NEQ 0 goto ERROR_EXIT

echo.
echo ======================================================================
echo   [OK] Пункт успешно удален из контекстного меню.
echo ======================================================================
echo.
pause
exit /b 0

:ERROR_EXIT
echo.
echo [-] Ошибка при удалении из контекстного меню.
echo.
pause
exit /b 1
