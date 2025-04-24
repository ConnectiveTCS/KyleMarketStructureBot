@echo off
REM filepath: c:\Coding\Market Structure Shift\install_service.bat
echo Installing Market Structure Bot Service...

REM Install required Python package
pip install pywin32

REM Install the service
python market_structure_service.py install

echo Service installed! You can now start it from Services.msc or by running:
echo python market_structure_service.py start
pause