@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo   PokeyoyaKun User Edition (Nuitka)
echo ========================================
python tools\build_user_edition_nuitka.py
if errorlevel 1 goto :failed
echo.
echo Nuitka build: OK
echo release\user_dist_nuitka
pause
exit /b 0
:failed
echo.
echo Nuitka build: NG
pause
exit /b 1
