# -*- coding: utf-8 -*-
"""IPTV  WAN 转发（鉴权版）· 纯标准库 · 可 Docker / 可 root 任务直跑。

与局域网版 mcast_proxy.py 同内核（剥 RTP 头裸转发），但面向公网暴露加固：
  1. 所有请求强制 ?token=... （恒定时间比较），连续失败封 IP 10 分钟；
  2. 组播地址白名单：只转发播放列表里存在的 (group,port)；
  3. 并发流上限（默认 4，保护家庭上行带宽）；
  4. 不暴露 /restart /ffmpegtest 等管理端点；/status 也需 token。

用法:
  python iptv_wan_proxy.py [iface_ip] [port] [token]
  环境变量优先: IPTV_IFACE / IPTV_PORT / IPTV_TOKEN / IPTV_M3U / IPTV_MAX_TOTAL
  IPTV_M3U 默认 = 脚本同目录 zj-telecom-verified.m3u（组播版列表）
播放列表:
  GET /playlist.m3u?token=...   流地址自动用请求的 Host（LAN IP 或 DDNS 域名均可）
单频道:
  GET /udp/<group>:<port>?token=...
"""
import socket, struct, sys, os, re, json, time, hmac, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
IFACE = os.environ.get('IPTV_IFACE') or (sys.argv[1] if len(sys.argv) > 1 else '0.0.0.0')
PORT = int(os.environ.get('IPTV_PORT') or (sys.argv[2] if len(sys.argv) > 2 else 19999))
TOKEN = os.environ.get('IPTV_TOKEN') or (sys.argv[3] if len(sys.argv) > 3 else '')
M3U = os.environ.get('IPTV_M3U') or os.path.join(HERE, 'zj-telecom-verified.m3u')
MAX_TOTAL = int(os.environ.get('IPTV_MAX_TOTAL', '8'))
BAN_FAILS, BAN_SECS = 8, 600
# 新光猫不发 IGMP 查询 → 内核加组会在光猫侧老化(~4分钟)断流；
# 每 REFRESH_SECS 秒主动补发 IGMPv2 报告续期（raw socket，需 root；非 root 回退 drop/re-add）
REFRESH_SECS = int(os.environ.get('IPTV_REFRESH_SECS', '60'))

if not TOKEN:
    sys.stderr.write('ERROR: 必须设置 IPTV_TOKEN（或第 3 个参数）。公网服务不允许无鉴权启动。\n')
    sys.exit(2)

ACTIVE = {}
LOCK = threading.Lock()
STRIKES = {}          # ip -> [fail_count, ban_until]
CHAN = []             # [(name, group, port)]
ALLOW = set()
M3U_MTIME = [0.0]


def load_channels():
    try:
        mt = os.path.getmtime(M3U)
    except OSError:
        return
    if mt == M3U_MTIME[0]:
        return
    chans, allow = [], set()
    name = ''
    with open(M3U, encoding='utf-8-sig', errors='replace') as f:
        for line in f:
            line = line.strip()
            if line.startswith('#EXTINF'):
                name = line.split(',')[-1].strip()
            elif line and not line.startswith('#'):
                m = re.search(r'(\d+\.\d+\.\d+\.\d+):(\d+)', line)
                if m:
                    g, p = m.group(1), int(m.group(2))
                    chans.append((name or g, g, p))
                    allow.add((g, p))
                name = ''
    global CHAN, ALLOW
    CHAN, ALLOW = chans, allow
    M3U_MTIME[0] = mt


def strip_rtp(data):
    """电信 IPTV 组播为 RTP 封装(MP2T)；剥头，兼容裸 TS。"""
    if len(data) >= 12 and (data[0] & 0xC0) == 0x80:
        cc = data[0] & 0x0F
        off = 12 + 4 * cc
        if (data[0] >> 4) & 1 and len(data) >= off + 4:
            off += 4 + int.from_bytes(data[off + 2:off + 4], 'big') * 4
        if len(data) > off and data[off] == 0x47:
            return data[off:]
    return data


def _csum(b):
    if len(b) % 2:
        b += b'\x00'
    s = sum(struct.unpack('!%dH' % (len(b) // 2), b))
    while s >> 16:
        s = (s & 0xffff) + (s >> 16)
    return (~s) & 0xffff


def make_report(group, src):
    """IGMPv2 membership report（带 Router Alert 选项的完整 IP 包）。"""
    g = socket.inet_aton(group)
    ig = struct.pack('!BBH4s', 0x16, 0, 0, g)
    ig = struct.pack('!BBH4s', 0x16, 0, _csum(ig), g)
    hdr = struct.pack('!BBHHHBBH4s4s', 0x46, 0xc0, 32, 0, 0, 1,
                      socket.IPPROTO_IGMP, 0, socket.inet_aton(src), g)
    hdr += b'\x94\x04\x00\x00'
    hdr = hdr[:10] + struct.pack('!H', _csum(hdr)) + hdr[12:]
    return hdr + ig


def refresh_loop(group, stop_evt, stream_sock, mreq):
    rs = None
    try:
        rs = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IGMP)
        rs.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        rs.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(IFACE))
    except OSError:
        rs = None
    pkt = make_report(group, IFACE) if rs else None
    while not stop_evt.wait(REFRESH_SECS):
        if rs is not None:
            try:
                rs.sendto(pkt, (group, 0))
            except OSError:
                pass
        else:
            try:
                stream_sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
                stream_sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            except OSError:
                pass
    if rs is not None:
        rs.close()


def client_ip(h):
    return h.client_address[0]


def banned(ip):
    rec = STRIKES.get(ip)
    return bool(rec and rec[1] > time.time())


def strike(ip):
    rec = STRIKES.setdefault(ip, [0, 0.0])
    rec[0] += 1
    if rec[0] >= BAN_FAILS:
        rec[1] = time.time() + BAN_SECS
        rec[0] = 0
        sys.stderr.write('BAN %s for %ds\n' % (ip, BAN_SECS))


def auth_ok(h, qs, ptok=''):
    ip = client_ip(h)
    if banned(ip):
        return False
    t = (qs.get('token') or [''])[0] or ptok
    if t and hmac.compare_digest(t, TOKEN):
        STRIKES.pop(ip, None)
        return True
    strike(ip)
    return False


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'iptv-wan'
    sys_version = ''

    def log_message(self, fmt, *args):
        pass

    def _text(self, body, code=200, ctype='text/plain; charset=utf-8'):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        path = u.path
        ptok = ''
        # 路径式 token：/t/<token>/... —— 客户端重连丢 query 时鉴权仍存活
        m = re.fullmatch(r'/t/([^/]+)(/.*)', path)
        if m:
            ptok, path = m.group(1), m.group(2)
        if path == '/':
            self._text('iptv-wan-proxy ok\n')
            return
        if not auth_ok(self, qs, ptok):
            self._text('forbidden\n', 403)
            return
        if path == '/playlist.m3u':
            load_channels()
            host = self.headers.get('Host') or ('127.0.0.1:%d' % PORT)
            lines = ['#EXTM3U']
            for name, g, p in CHAN:
                lines.append('#EXTINF:-1,%s' % name)
                lines.append('http://%s/t/%s/udp/%s:%d' % (host, TOKEN, g, p))
            self._text('\n'.join(lines) + '\n', 200, 'audio/x-mpegurl; charset=utf-8')
            return
        if path == '/status':
            with LOCK:
                act = dict(ACTIVE)
            self._text(json.dumps({'active': act, 'max_total': MAX_TOTAL,
                                   'channels': len(CHAN)}, ensure_ascii=False),
                       200, 'application/json; charset=utf-8')
            return
        m = re.fullmatch(r'/udp/(\d+\.\d+\.\d+\.\d+):(\d+)', path)
        if m:
            load_channels()
            g, p = m.group(1), int(m.group(2))
            if (g, p) not in ALLOW:
                self._text('not in channel list\n', 404)
                return
            self.stream(g, p)
            return
        self._text('not found\n', 404)

    def stream(self, group, port):
        with LOCK:
            if sum(ACTIVE.values()) >= MAX_TOTAL:
                self._text('too many concurrent streams\n', 503)
                return
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
            s.bind(('', port))
            mreq = struct.pack('4s4s', socket.inet_aton(group), socket.inet_aton(IFACE))
            s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(IFACE))
            s.settimeout(6)
        except Exception as e:
            s.close()
            self._text('join failed: %s\n' % e, 500)
            return
        key = '%s:%d' % (group, port)
        with LOCK:
            ACTIVE[key] = ACTIVE.get(key, 0) + 1
        stop_evt = threading.Event()
        threading.Thread(target=refresh_loop, args=(group, stop_evt, s, mreq),
                         daemon=True).start()
        self.send_response(200)
        self.send_header('Content-Type', 'video/MP2T')
        self.send_header('Connection', 'close')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.close_connection = True
        try:
            while True:
                try:
                    data, _ = s.recvfrom(65535)
                except socket.timeout:
                    break
                self.wfile.write(strip_rtp(data))
        except Exception:
            pass
        finally:
            stop_evt.set()
            try:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
            except Exception:
                pass
            s.close()
            with LOCK:
                ACTIVE[key] = max(0, ACTIVE.get(key, 1) - 1)
                if ACTIVE[key] == 0:
                    del ACTIVE[key]


if __name__ == '__main__':
    load_channels()
    if not CHAN:
        sys.stderr.write('ERROR: 播放列表为空或不存在: %s\n' % M3U)
        sys.exit(2)
    srv = ThreadingHTTPServer(('0.0.0.0', PORT), Handler)
    print('iptv-wan-proxy on 0.0.0.0:%d iface=%s channels=%d max_total=%d auth=on'
          % (PORT, IFACE, len(CHAN), MAX_TOTAL), flush=True)
    srv.serve_forever()
