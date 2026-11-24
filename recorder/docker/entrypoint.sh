#!/bin/sh
# 无双IPTV录像工具容器入口：
#   无参数 → 常驻 proxy（展开环境变量；exec 保证 SIGTERM 直达 python，优雅停录收尾）
#   有参数 → 透传 rec_cli（docker run <镜像> info / record list ...）
if [ "$#" -eq 0 ]; then
  set -- proxy --channels "$IPTV_CHANNELS" --record-dir "$IPTV_RECORD_DIR" \
    --iface "$IPTV_IFACE" --port "$IPTV_PORT" --quota-gb "$IPTV_QUOTA_GB" \
    --max-concurrent "$IPTV_MAX_CONCURRENT" --pad-before "$IPTV_PAD_BEFORE" \
    --pad-after "$IPTV_PAD_AFTER" --missed "$IPTV_MISSED"
fi
exec python rec_cli.py "$@"
