@echo off
chcp 65001 >nul
rem ============================================================
rem  Сборка Softpalaroid под Windows: exe + установщик
rem  Требования: Python 3.11+ (в PATH), для установщика — Inno Setup 6
rem  Запуск: просто дважды кликнуть по файлу или `packaging\build.bat`
rem ============================================================
cd /d "%~dp0\.."

echo [1/4] Виртуальное окружение...
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv || python -m venv .venv
)
set PY=.venv\Scripts\python.exe

echo [2/4] Зависимости...
%PY% -m pip install --upgrade pip || goto :error
%PY% -m pip install -r requirements.txt pyinstaller || goto :error

echo [3/4] Сборка Softpalaroid.exe (PyInstaller)...
%PY% -m PyInstaller packaging\Softpalaroid.spec --noconfirm || goto :error

echo [4/4] Установщик (Inno Setup)...
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
    %ISCC% packaging\installer.iss || goto :error
    echo.
    echo ГОТОВО: установщик в папке dist\installer\
) else (
    echo.
    echo Inno Setup не найден — установщик пропущен.
    echo Скачать: https://jrsoftware.org/isdl.php
    echo Программа без установщика: dist\Softpalaroid\Softpalaroid.exe
)
echo.
pause
exit /b 0

:error
echo.
echo ОШИБКА сборки, код %errorlevel%
pause
exit /b 1
