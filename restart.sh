#!/bin/bash
# 快速重启 CyberReel 项目
cd /c/Users/Dyson/Desktop/claude_proj/cyber_reel || exit 1
PID=$(cmd //c "netstat -ano 2>nul | findstr 8080 | findstr LISTENING" | awk '{print $NF}')
[ -n "$PID" ] && cmd //c "taskkill /F /PID $PID" 2>/dev/null
sleep 1
python main.py &
sleep 3
cmd //c "netstat -ano | findstr 8080 | findstr LISTENING" && echo "  http://127.0.0.1:8080"
