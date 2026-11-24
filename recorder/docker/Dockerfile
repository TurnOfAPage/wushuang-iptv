ARG BASE=python:3.12-alpine
FROM ${BASE}
WORKDIR /app
COPY src/ /app/src/
COPY recorder/ /app/recorder/
COPY entrypoint.sh /app/entrypoint.sh
WORKDIR /app/recorder
ENV IPTV_IFACE=192.168.1.100 \
    IPTV_PORT=9999 \
    IPTV_CHANNELS=/data/zj-telecom-verified.m3u \
    IPTV_RECORD_DIR=/rec \
    IPTV_QUOTA_GB=100 \
    IPTV_MAX_CONCURRENT=2 \
    IPTV_PAD_BEFORE=60 \
    IPTV_PAD_AFTER=120 \
    IPTV_MISSED=skip \
    TZ=Asia/Shanghai
EXPOSE 9999
ENTRYPOINT ["/bin/sh", "/app/entrypoint.sh"]
