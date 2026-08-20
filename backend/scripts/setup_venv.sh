#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "[ERROR] 找不到 $PY。请先安装 Python 3.10+（推荐 3.12）。"
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  echo "Creating backend/.venv with $PY"
  "$PY" -m venv .venv
fi

.venv/bin/python -m pip install -U pip
# 默认 CPU 版 PyTorch。有 NVIDIA GPU 时可：
#   TORCH_INDEX=https://download.pytorch.org/whl/cu124 bash backend/scripts/setup_venv.sh
INDEX="${TORCH_INDEX:-https://download.pytorch.org/whl/cpu}"
.venv/bin/python -m pip install torch torchvision --index-url "$INDEX"
.venv/bin/python -m pip install -r requirements.txt
echo "venv ready: $ROOT/.venv/bin/python"
