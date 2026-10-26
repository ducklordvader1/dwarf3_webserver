@echo off
REM Stop the DWARF web server (Windows)
setlocal
set "WINTITLE=dwarf_web_server"

taskkill /f /fi "windowtitle eq %WINTITLE%*" >nul 2>&1
if not errorlevel 1 (
    echo DWARF web server stopped.
) else (
    REM Fall back to matching the server.py command line
    taskkill /f /fi "imagename eq python.exe" /fi "windowtitle eq %WINTITLE%*" >nul 2>&1
    echo No running DWARF web server found ^(or already stopped^).
)
endlocal
