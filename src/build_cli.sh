#!/usr/bin/env bash
# 无双IPTV · CLI 公开构建脚本（Linux/macOS，在 src 目录运行）
# 产物: ../dist/WushuangIPTV-CLI (单文件 / 控制台；仅 capture 子命令需要 root/sudo)
# 依赖: python3 + pip install pyinstaller
set -eo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}

# 可选：仅当已抓取社区参考数据时才内嵌参考库；默认不内嵌（运行时在线更新）
if [ -d "../ref/national" ]; then
  "$PY" build_refdb.py
fi
EXTRA=()
if [ -f "refdb.json.gz" ]; then
  EXTRA+=(--add-data "$PWD/refdb.json.gz:.")
fi

"$PY" -m PyInstaller --noconfirm --onefile --console \
  --name "WushuangIPTV-CLI" \
  ${EXTRA[@]+"${EXTRA[@]}"} \
  --distpath "../dist" \
  --workpath "../build" \
  --specpath "../build" \
  cli_entry.py
echo "完成: ../dist/WushuangIPTV-CLI"
