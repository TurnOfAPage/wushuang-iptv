#!/usr/bin/env bash
# 无双IPTV录像工具 · Docker 部署包打包脚本（Linux/macOS，在 recorder 目录运行）
# 产物: ../dist/docker-recorder/ （自包含上传目录）；本机 Docker 可用时另导出离线镜像 tar
set -eo pipefail
cd "$(dirname "$0")"
ROOT=".."
OUT="$ROOT/dist/docker-recorder"
rm -rf "$OUT"
mkdir -p "$OUT/src" "$OUT/recorder"
for m in channeldb.py epg.py m3u.py netutil.py proxy.py record.py tsutil.py webui.py; do
  cp "$ROOT/src/$m" "$OUT/src/$m"
done
[ -f "$ROOT/src/refdb.json.gz" ] && cp "$ROOT/src/refdb.json.gz" "$OUT/src/refdb.json.gz"
cp rec_cli.py recinfo.py "$OUT/recorder/"
cp docker/Dockerfile docker/entrypoint.sh docker/docker-compose.yml docker/.env.example docker/README.md "$OUT/"
echo "打包完成: $OUT"
if docker info >/dev/null 2>&1; then
  docker build -t iptv-recorder:1.0.0 "$OUT"
  docker run --rm iptv-recorder:1.0.0 info >/dev/null
  docker save -o "$ROOT/dist/iptv-recorder-1.0.0.tar" iptv-recorder:1.0.0
  echo "镜像导出: $ROOT/dist/iptv-recorder-1.0.0.tar"
else
  echo "Docker 守护进程不可用：仅生成上传目录（NAS 端 Container Manager 自行构建）"
fi
