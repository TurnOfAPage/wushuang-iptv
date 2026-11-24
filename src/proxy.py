# -*- coding: utf-8 -*-
"""组播 → HTTP 单播转发服务（udpxy 等价物，源自今日实测的 mcast_proxy.py）。
/playlist.m3u 动态输出 HTTP 版列表；/udp/<组>:<端口> 转发单频道；/status 查看活跃流。
仅限局域网使用，禁止映射公网。

可选 record_mgr（record.RecordManager）：启用录像点播扩展（独立录像产品使用，
缺省 None 时行为与旧版完全一致）：/vod/<rid>（Range 拖动）、/recordings.m3u、
/recordings.json。
"""
import json
import os
import re
import socket
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import m3u
import webui


def strip_rtp(data):
    """部分运营商 IPTV 组播为 RTP 封装（12 字节头 + 1316 字节 TS）；
    转发前剥头，否则播放器失步 → 马赛克/疯狂缓冲。兼容裸 UDP-TS（首字节 0x47 直接放行）。"""
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


def _igmp_report(group, src):
    """IGMPv2 membership report 完整 IP 包（带 Router Alert 选项）。"""
    g = socket.inet_aton(group)
    ig = struct.pack('!BBH4s', 0x16, 0, 0, g)
    ig = struct.pack('!BBH4s', 0x16, 0, _csum(ig), g)
    hdr = struct.pack('!BBHHHBBH4s4s', 0x46, 0xc0, 32, 0, 0, 1,
                      socket.IPPROTO_IGMP, 0, socket.inet_aton(src), g)
    hdr += b'\x94\x04\x00\x00'
    return hdr[:10] + struct.pack('!H', _csum(hdr)) + hdr[12:] + ig


def _refresh_loop(group, iface, stop_evt, sock, mreq, interval=60):
    """光猫/交换机不发 IGMP 查询的网络里，内核加组会在设备侧老化（约 4 分钟）断流；
    周期补发报告续期。raw socket 需管理员/root；不可用时回退流 socket drop/re-add。"""
    rs = None
    try:
        rs = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IGMP)
        rs.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        rs.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface))
    except OSError:
        rs = None
    pkt = _igmp_report(group, iface) if rs else None
    while not stop_evt.wait(interval):
        if rs is not None:
            try:
                rs.sendto(pkt, (group, 0))
            except OSError:
                pass
        else:
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            except OSError:
                pass
    if rs is not None:
        rs.close()


class ProxyServer:
    def __init__(self, iface_ip, port=9999, channels_cb=None, record_mgr=None):
        self.iface_ip = iface_ip
        self.port = port
        self.channels_cb = channels_cb or (lambda: [])
        self.record_mgr = record_mgr
        self.active = {}
        self.lock = threading.Lock()
        self.httpd = None
        self.thread = None
        self.error = ''

    def start(self):
        if self.httpd:
            return True, '已在运行'
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, fmt, *args):
                pass

            def _send(self, code, body, ctype):
                self.send_response(code)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self):
                path = self.path.split('?')[0]
                if outer.record_mgr is not None and path in ('/', '/admin', '/ui'):
                    self._send(200, webui.PAGE.encode('utf-8'), 'text/html; charset=utf-8')
                    return
                if outer.record_mgr is not None and path.startswith('/api/'):
                    webui.handle_get(self, outer, path)
                    return
                if path in ('/', '/status'):
                    with outer.lock:
                        act = dict(outer.active)
                    d = {'iface': outer.iface_ip, 'port': outer.port, 'active': act}
                    if outer.record_mgr is not None:
                        try:
                            d['recordings'] = outer.record_mgr.status()
                        except Exception:
                            pass
                    body = json.dumps(d, ensure_ascii=False).encode()
                    self._send(200, body, 'application/json')
                    return
                if outer.record_mgr is not None:
                    if path == '/recordings.json':
                        body = json.dumps(outer.record_mgr.list_recordings(),
                                          ensure_ascii=False).encode()
                        self._send(200, body, 'application/json')
                        return
                    if path == '/recordings.m3u':
                        text = m3u.recordings_m3u(outer.record_mgr.list_recordings(),
                                                  outer.iface_ip, outer.port)
                        self._send(200, text.encode('utf-8'), 'audio/x-mpegurl')
                        return
                if path in ('/playlist.m3u', '/http.m3u'):
                    chans = outer.channels_cb()
                    lines = ['#EXTM3U']
                    for ch in m3u.sort_channels(chans):
                        if not ch.get('ok'):
                            continue
                        name = ch.get('name') or '%s:%d' % (ch['group'], ch['port'])
                        lines.append('#EXTINF:-1 tvg-name="%s" group-title="%s",%s'
                                     % (name, ch.get('cat') or '未分类', name))
                        lines.append('http://%s:%d/udp/%s:%d'
                                     % (outer.iface_ip, outer.port, ch['group'], ch['port']))
                    self._send(200, ('\n'.join(lines) + '\n').encode('utf-8'),
                               'audio/x-mpegurl')
                    return
                if path == '/raw.m3u':
                    chans = outer.channels_cb()
                    lines = ['#EXTM3U']
                    for ch in m3u.sort_channels(chans):
                        if not ch.get('ok'):
                            continue
                        name = ch.get('name') or '%s:%d' % (ch['group'], ch['port'])
                        lines.append('#EXTINF:-1 tvg-name="%s" group-title="%s",%s'
                                     % (name, ch.get('cat') or '未分类', name))
                        lines.append('udp://@%s:%d' % (ch['group'], ch['port']))
                    self._send(200, ('\n'.join(lines) + '\n').encode('utf-8'),
                               'audio/x-mpegurl')
                    return
                parts = path.strip('/').split('/')
                if len(parts) == 2 and parts[0] in ('udp', 'rtp'):
                    try:
                        g, p = parts[1].split(':')
                        p = int(p)
                        socket.inet_aton(g)
                    except (ValueError, OSError):
                        self.send_error(400)
                        return
                    self.stream(g, p)
                    return
                if (len(parts) == 2 and parts[0] == 'vod'
                        and outer.record_mgr is not None):
                    self.vod(parts[1], head_only=False)
                    return
                self.send_error(404)

            def do_HEAD(self):
                path = self.path.split('?')[0]
                parts = path.strip('/').split('/')
                if (len(parts) == 2 and parts[0] == 'vod'
                        and outer.record_mgr is not None):
                    self.vod(parts[1], head_only=True)
                    return
                self.send_error(404)

            def do_POST(self):
                path = self.path.split('?')[0]
                if outer.record_mgr is None or not path.startswith('/api/'):
                    self.send_error(404)
                    return
                try:
                    length = int(self.headers.get('Content-Length', 0) or 0)
                except ValueError:
                    length = 0
                body = self.rfile.read(length) if length else b'{}'
                webui.handle_post(self, outer, path, body)

            def vod(self, rid, head_only=False):
                """录像点播：只认索引白名单 rid（防路径穿越）；Range 拖动；
                多分段按字节偏移虚拟拼接；录制中的文件也可边录边看。"""
                if not re.fullmatch(r'[A-Za-z0-9_\-]+', rid):
                    self.send_error(404)
                    return
                rec = outer.record_mgr.get_recording(rid)
                if not rec or not rec.get('parts'):
                    self.send_error(404)
                    return
                files = []
                total = 0
                for part in rec['parts']:
                    p = os.path.join(outer.record_mgr.record_dir, part['file'])
                    try:
                        sz = os.path.getsize(p)
                    except OSError:
                        continue
                    files.append((p, sz))
                    total += sz
                if not files or total == 0:
                    self.send_error(404)
                    return
                rng = self.headers.get('Range', '')
                start, end = 0, total - 1
                partial = False
                m = re.fullmatch(r'bytes=(\d*)-(\d*)', rng.strip()) if rng else None
                if m:
                    a, b = m.group(1), m.group(2)
                    if a == '' and b == '':
                        self.send_error(416)
                        return
                    if a == '':            # 后缀范围 bytes=-n
                        n = int(b)
                        if n == 0:
                            self._range_invalid(total)
                            return
                        start = max(0, total - n)
                    else:
                        start = int(a)
                        end = int(b) if b else total - 1
                    if start >= total:
                        self._range_invalid(total)
                        return
                    end = min(end, total - 1)
                    partial = True
                length = end - start + 1
                self.send_response(206 if partial else 200)
                self.send_header('Content-Type', 'video/MP2T')
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Content-Length', str(length))
                if partial:
                    self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, end, total))
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                if head_only:
                    return
                try:
                    remaining = length
                    off = start
                    for p, sz in files:
                        if off >= sz:
                            off -= sz
                            continue
                        take = min(sz - off, remaining)
                        with open(p, 'rb') as f:
                            f.seek(off)
                            while take > 0:
                                chunk = f.read(min(65536, take))
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                                take -= len(chunk)
                                remaining -= len(chunk)
                        off = 0
                        if remaining <= 0:
                            break
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                self.close_connection = True

            def _range_invalid(self, total):
                self.send_response(416)
                self.send_header('Content-Range', 'bytes */%d' % total)
                self.send_header('Content-Length', '0')
                self.end_headers()

            def stream(self, group, port):
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    s.bind(('', port))
                    mreq = struct.pack('4s4s', socket.inet_aton(group),
                                       socket.inet_aton(outer.iface_ip))
                    s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                                 socket.inet_aton(outer.iface_ip))
                    s.settimeout(6)
                except Exception as e:
                    s.close()
                    self.send_error(500, str(e))
                    return
                key = '%s:%d' % (group, port)
                with outer.lock:
                    outer.active[key] = outer.active.get(key, 0) + 1
                stop_evt = threading.Event()
                threading.Thread(target=_refresh_loop,
                                 args=(group, outer.iface_ip, stop_evt, s, mreq),
                                 daemon=True).start()
                self.send_response(200)
                self.send_header('Content-Type', 'video/MP2T')
                self.send_header('Connection', 'close')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                try:
                    while True:
                        try:
                            data, _ = s.recvfrom(65535)
                        except socket.timeout:
                            break
                        self.wfile.write(strip_rtp(data))
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    stop_evt.set()
                    with outer.lock:
                        outer.active[key] = max(0, outer.active.get(key, 1) - 1)
                        if outer.active[key] == 0:
                            outer.active.pop(key, None)
                    try:
                        s.setsockopt(socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq)
                    except OSError:
                        pass
                    s.close()
                    self.close_connection = True

        try:
            self.httpd = ThreadingHTTPServer(('0.0.0.0', self.port), Handler)
        except Exception as e:
            self.httpd = None
            self.error = str(e)
            return False, '监听失败: %s' % e
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       kwargs={'poll_interval': 0.3}, daemon=True)
        self.thread.start()
        return True, '转发服务已启动: 0.0.0.0:%d (组播网卡 %s)' % (self.port, self.iface_ip)

    def stop(self):
        if self.httpd:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
            self.httpd = None
            self.thread = None
        return True, '转发服务已停止'

    @property
    def running(self):
        return self.httpd is not None
