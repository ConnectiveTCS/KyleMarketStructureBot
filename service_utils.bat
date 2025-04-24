@echo off
REM filepath: c:\Coding\Market Structure Shift\service_utils.bat
echo Market Structure Bot Service Utilities

:menu
cls
echo ==============================================
echo         MARKET STRUCTURE BOT SERVICE
echo ==============================================
echo.
echo  1. Install service
echo  2. Start service
echo  3. Stop service
echo  4. Restart service
echo  5. Remove service
echo  6. Check service status
echo  7. Exit
echo.
set /p choice=Enter your choice (1-7): 

if "%choice%"=="1" goto install
if "%choice%"=="2" goto start
if "%choice%"=="3" goto stop
if "%choice%"=="4" goto restart
if "%choice%"=="5" goto remove
if "%choice%"=="6" goto status
if "%choice%"=="7" goto end

echo Invalid choice. Please try again.
timeout /t 2 >nul
goto menu

:install
echo Installing service...
python market_structure_service.py install
echo.
echo Service installed!
timeout /t 2 >nul
goto menu

:start
echo Starting service...
python market_structure_service.py start
echo.
echo Service start requested.
timeout /t 2 >nul
goto menu

:stop
echo Stopping service...
python market_structure_service.py stop
echo.
echo Service stop requested.
timeout /t 2 >nul
goto menu

:restart
echo Restarting service...
python market_structure_service.py restart
echo.
echo Service restart requested.
timeout /t 2 >nul
goto menu

:remove
echo Removing service...
python market_structure_service.py remove
echo.
echo Service removed!
timeout /t 2 >nul
goto menu

:status
echo Checking service status...
sc query MarketStructureBot
echo.
pause
goto menu

:end
echo Exiting...
exit