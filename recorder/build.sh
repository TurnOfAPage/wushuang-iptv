#!/usr/bin/env bash
# 无双IPTV录像工具 · GUI 构建脚本（Linux/macOS，在 recorder 目录运行）
# 产物: ../dist/无双IPTV录像工具 (单文件 / 需要 python3-tk；NAS 无头场景请用 CLI)
# 依赖: python3 + pip install pyinstaller + tkinter
set -eo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
SRC="../src"
EXTRA=()
if [ -f "$SRC/refdb.json.gz" ]; then
  EXTRA+=(--add-data "$PWD/$SRC/refdb.json.gz:.")
fi
if [ -f "$SRC/app.ico" ]; then
  EXTRA+=(--add-data "$PWD/$SRC/app.ico:.")
fi
"$PY" -m PyInstaller --noconfirm --onefile --noconsole \
  --name "无双IPTV录像工具" \
  --paths "$SRC" \
  ${EXTRA[@]+"${EXTRA[@]}"} \
  --distpath "../dist" \
  --workpath "../build/recorder" \
  --specpath "../build/recorder" \
  rec_main.py
echo "完成: ../dist/无双IPTV录像工具"
