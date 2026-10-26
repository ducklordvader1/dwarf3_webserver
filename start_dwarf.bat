@echo off
REM Start the DWARF web server (Windows)
REM Usage: start_dwarf.bat [telescope_ip]
REM   telescope_ip defaults to 192.168.1.10

setlocal
set "SCRIPT_DIR=%~dp0"
set "TELESCOPE_IP=%~1"
if "%TELESCOPE_IP%"=="" set "TELESCOPE_IP=192.168.1.10"
set "LOGFILE=%TEMP%\dwarf_web.log"
set "WINTITLE=dwarf_web_server"

REM Refuse to start a second instance (match our titled window)
tasklist /v /fi "imagename eq python.exe" 2>nul | find /i "%WINTITLE%" >nul
if not errorlevel 1 (
    echo DWARF web server already running.
    echo Logs: %LOGFILE%
    goto :eof
)

REM Launch detached, in its own titled window, logging to a file
start "%WINTITLE%" /b cmd /c "python ""%SCRIPT_DIR%server.py"" %TELESCOPE_IP% > ""%LOGFILE%"" 2>&1"

echo DWARF web server started.
echo Telescope: %TELESCOPE_IP%
echo Browser:   http://localhost:5000
echo Logs:      %LOGFILE%
echo Stop with: stop_dwarf.bat
endlocal
