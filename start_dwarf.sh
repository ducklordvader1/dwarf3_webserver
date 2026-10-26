#!/bin/bash
# Start DWARF web server as a detached daemon
# Usage: ./start_dwarf.sh [telescope_ip]

TELESCOPE_IP=${1:-192.168.1.10}
PIDFILE=/tmp/dwarf_web.pid
LOGFILE=/tmp/dwarf_web.log
SERVER=/home/kali/dwarf_web/server.py

# Check if already running
if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "DWARF server already running as PID $PID"
        echo "Logs: tail -f $LOGFILE"
        exit 0
    fi
fi

nohup python3 "$SERVER" "$TELESCOPE_IP" > "$LOGFILE" 2>&1 &
DWARF_PID=$!
disown $DWARF_PID
echo $DWARF_PID > "$PIDFILE"
echo "DWARF web server started as PID $DWARF_PID"
echo "Telescope: $TELESCOPE_IP"
echo "Browser:   http://$(hostname -I | awk '{print $1}'):5000"
echo "Logs:      tail -f $LOGFILE"
