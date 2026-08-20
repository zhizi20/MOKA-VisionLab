#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo
echo "=============================================="
echo "  Web UI:  http://127.0.0.1:5174"
echo "  Login:   http://127.0.0.1:5174/login"
echo "  Account: admin / admin123"
echo "  API:     http://127.0.0.1:8000"
echo "=============================================="
echo

if [[ ! -x backend/.venv/bin/python ]]; then
  echo "未找到 backend/.venv，正在创建..."
  bash backend/scripts/setup_venv.sh
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "[ERROR] 找不到 npm。请安装 Node.js 18+ 后再试。"
  exit 1
fi

if [[ ! -d frontend/node_modules ]]; then
  echo "Installing frontend dependencies..."
  (cd frontend && npm install)
fi

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  echo
  echo "正在停止..."
  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "启动后端..."
(cd backend && .venv/bin/python app.py) &
BACKEND_PID=$!

echo "启动前端..."
(cd frontend && npm run dev) &
FRONTEND_PID=$!

sleep 2
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://127.0.0.1:5174" >/dev/null 2>&1 || true
fi

echo
echo "已启动。浏览器打开：http://127.0.0.1:5174"
echo "按 Ctrl+C 停止后端和前端。"
echo
wait
