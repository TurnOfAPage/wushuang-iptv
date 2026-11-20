FROM python:3.12-alpine
WORKDIR /app
COPY iptv_wan_proxy.py /app/iptv_wan_proxy.py
ENV IPTV_PORT=19999 \
    IPTV_M3U=/data/iptv.m3u \
    IPTV_MAX_TOTAL=8 \
    IPTV_REFRESH_SECS=60
EXPOSE 19999
CMD ["python", "/app/iptv_wan_proxy.py"]
