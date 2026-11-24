#!/usr/bin/env bash
# 无双IPTV录像工具 · CLI 构建脚本（Linux/macOS，在 recorder 目录运行）
# 产物: ../dist/WushuangIPTV-Recorder-CLI (单文件 / 控制台 / 不需要 root)
# 依赖: python3 + pip install pyinstaller
set -eo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
SRC="../src"
EXTRA=()
if [ -f "$SRC/refdb.json.gz" ]; then
  EXTRA+=(--add-data "$PWD/$SRC/refdb.json.gz:.")
fi
"$PY" -m PyInstaller --noconfirm --onefile --console \
  --name "WushuangIPTV-Recorder-CLI" \
  --paths "$SRC" \
  ${EXTRA[@]+"${EXTRA[@]}"} \
  --distpath "../dist" \
  --workpath "../build/recorder" \
  --specpath "../build/recorder" \
  rec_cli.py
echo "完成: ../dist/WushuangIPTV-Recorder-CLI"
