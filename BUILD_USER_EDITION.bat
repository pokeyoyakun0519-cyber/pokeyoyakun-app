@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo   PokeyoyaKun User Edition Build
echo ========================================
python tools\build_user_edition.py
if errorlevel 1 goto :failed
python tools\build_user_installer.py
if errorlevel 1 goto :failed
echo.
echo User Edition build: OK
echo release\user_installer_rc5\PokeyoyaKun_User_Setup_Ver1.25.0_RC5.exe
pause
exit /b 0
:failed
echo.
echo User Edition build: NG
pause
exit /b 1
