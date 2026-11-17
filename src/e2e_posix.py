# -*- coding: utf-8 -*-
"""Linux/macOS 端到端冒烟（无需 IPTV 专网、无需 root）：
合成 TS 组播源（回环网卡）→ verify 真实加组收流 → proxy HTTP 转发 → M3U 生成。
用法: python3 e2e_posix.py
说明：在 127.0.0.1 上发/收组播，验证的是与真实 IPTV 完全相同的代码路径
（IP_ADD_MEMBERSHIP / TS 解析 / HTTP 单播转发），只是网络换成回环。
"""
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import m3u
import proxy
import selftest
import verify

GROUP, PORT, IFACE = '239.123.45.67', 5140, '127.0.0.1'
FAILS = []


def check(name, cond, extra=''):
    print('%s %s %s' % ('PASS' if cond else 'FAIL', name, extra))
    if not cond:
        FAILS.append(name)


class Sender(threading.Thread):
    """把合成 TS 按 1316 字节 UDP 载荷循环发往组播组（与真实 IPTV 封装一致）。"""
    daemon = True

    def __init__(self, ts_data):
        super().__init__()
        self.chunks = [ts_data[i:i + 1316] for i in range(0, len(ts_data), 1316)]
        self.stop = threading.Event()

    def run(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(IFACE))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        i = 0
        while not self.stop.is_set():
            s.sendto(self.chunks[i % len(self.chunks)], (GROUP, PORT))
            i += 1
            time.sleep(0.002)
        s.close()


def main():
    ts_data = selftest.make_test_ts()
    snd = Sender(ts_data)
    snd.start()
    time.sleep(0.2)
    try:
        # 1) verify：真实加组收流 + TS 解析（与 CLI/GUI 同一函数）
        r = verify.verify_channel(GROUP, PORT, IFACE, timeout=6.0, min_bytes=100_000)
        check('verify: 加组收流', r['ok'],
              'bytes=%d pkts=%d err=%s' % (r['bytes'], r['pkts'], r['error']))
        check('verify: 编码识别', r['video'] == 'h264' and r['audio'] == 'mp2',
              str((r['video'], r['audio'])))
        check('verify: SDT 频道名', r['sdt_name'] == 'CCTV-1测试', repr(r['sdt_name']))
        check('verify: SPS 分辨率', r['res'] == '1920x1080', str(r['res']))

        # 2) proxy：组播 → HTTP 单播转发
        chans = [{'name': r['sdt_name'] or 'CCTV1', 'group': GROUP, 'port': PORT,
                  'cat': '央视', 'ok': r['ok'], 'video': r['video'],
                  'audio': r['audio'], 'res': r['res']}]
        srv = proxy.ProxyServer(IFACE, 19999, lambda: chans)
        ok, msg = srv.start()
        check('proxy: 启动', ok, msg)
        if ok:
            try:
                time.sleep(0.3)
                with urllib.request.urlopen('http://127.0.0.1:19999/status', timeout=5) as resp:
                    check('proxy: /status', resp.status == 200)
                with urllib.request.urlopen('http://127.0.0.1:19999/playlist.m3u', timeout=5) as resp:
                    body = resp.read().decode('utf-8')
                check('proxy: /playlist.m3u', GROUP in body and '19999' in body)
                with urllib.request.urlopen('http://127.0.0.1:19999/udp/%s:%d' % (GROUP, PORT),
                                            timeout=8) as resp:
                    got = b''
                    deadline = time.time() + 2
                    while time.time() < deadline and len(got) < 200_000:
                        got += resp.read(4096)
                check('proxy: /udp 流转发', len(got) > 50_000 and got[0] == 0x47,
                      'bytes=%d' % len(got))
            finally:
                srv.stop()

        # 3) m3u 生成
        tmp = tempfile.mkdtemp(prefix='iptv_e2e_')
        p = os.path.join(tmp, 'iptv.m3u')
        n = m3u.write_m3u(p, chans, fmt='udp')
        check('m3u: 生成', n == 1 and os.path.exists(p))
    finally:
        snd.stop.set()
    print('\n%s' % ('ALL PASS' if not FAILS else 'FAILED: %s' % FAILS))
    sys.exit(1 if FAILS else 0)


if __name__ == '__main__':
    main()
