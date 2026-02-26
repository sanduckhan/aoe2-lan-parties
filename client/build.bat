@echo off
echo Installing dependencies...
pip install -r requirements.txt pyinstaller
echo Building AoE2 Uploader...
pyinstaller --onefile --windowed --icon=icon.ico --name="AoE2 Uploader" uploader.py
echo Done! Executable is in dist\AoE2 Uploader.exe
pause
