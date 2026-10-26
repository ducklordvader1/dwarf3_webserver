#!/bin/bash
PIDFILE=/tmp/dwarf_web.pid
if [ -f "$PIDFILE" ]; then
    PID=$(cat "$PIDFILE")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        rm "$PIDFILE"
        echo "DWARF server PID $PID stopped"
    else
        echo "PID $PID not running"
        rm "$PIDFILE"
    fi
else
    pkill -f "server.py" && echo "Stopped" || echo "Not running"
fi
