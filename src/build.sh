#!/usr/bin/env bash
# 无双IPTV · GUI 构建脚本（Linux/macOS，在 src 目录运行）
# 产物: Linux → ../dist/WushuangIPTV-GUI (单文件)
#       macOS → ../dist/WushuangIPTV-GUI.app (应用包)
# 依赖: python3 + pip install pyinstaller；Linux 另需 python3-tk（系统包）
# 注意: 抓包功能需 sudo 启动本程序；验证/M3U/转发不需要 root。
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
if [ -f "icon_44.png" ]; then
  EXTRA+=(--add-data "$PWD/icon_44.png:.")
fi

"$PY" -m PyInstaller --noconfirm --onefile --windowed \
  --name "WushuangIPTV-GUI" \
  ${EXTRA[@]+"${EXTRA[@]}"} \
  --distpath "../dist" \
  --workpath "../build" \
  --specpath "../build" \
  main.py
echo "完成: ../dist/WushuangIPTV-GUI (macOS 为 .app 包)"
