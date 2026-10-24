@echo off
chcp 65001 >nul
echo ======================================================================
echo          PDF Merger - Context Menu Setup
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
    echo [+] Running via py launcher: py -3 "%ROOT_DIR%src\app.py" --install
    py -3 "%ROOT_DIR%src\app.py" --install
    goto CHECK_RESULT
)

where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo [+] Running via python: python "%ROOT_DIR%src\app.py" --install
    python "%ROOT_DIR%src\app.py" --install
    goto CHECK_RESULT
)

echo [-] Ошибка: Не найден ни PDFMerger.exe, ни установленный Python в системе.
goto ERROR_EXIT

:USE_EXE
echo [+] Running: "%EXE_PATH%" --install
"%EXE_PATH%" --install
goto CHECK_RESULT

:CHECK_RESULT
if %ERRORLEVEL% NEQ 0 goto ERROR_EXIT

echo.
echo ======================================================================
echo   [OK] Пункт успешно добавлен в контекстное меню Windows!
echo.
echo   Как пользоваться:
echo     1. Выделите файлы в Проводнике (PDF, JPG, Word docx и др.)
echo     2. Нажмите правую кнопку мыши и выберите "Объединить в PDF..."
echo     3. Нажмите "Объединить в один PDF"
echo.
echo   * Программа НЕ висит в фоне и потребляет 0 ресурсов при простое.
echo ======================================================================
echo.
pause
exit /b 0

:ERROR_EXIT
echo.
echo [-] Ошибка при установке контекстного меню в реестр.
echo.
pause
exit /b 1
