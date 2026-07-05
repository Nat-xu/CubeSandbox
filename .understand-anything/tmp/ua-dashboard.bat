@echo off
setlocal
set "GRAPH_DIR=C:\Users\18257\Desktop\issue\CubeSandbox\CubeAPI"
cd /d "C:\Users\18257\.understand-anything\repo\understand-anything-plugin\packages\dashboard"
call npx vite --host 127.0.0.1 --port 5173 > "%TEMP%\ua-dashboard.log" 2>&1