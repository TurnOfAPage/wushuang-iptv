# -*- coding: utf-8 -*-
"""真实网络端到端冒烟（可选，需本机已接入 IPTV 专网/桥接网络，能收到组播）：
  record start 实录 N 秒 → proxy 常驻 → /recordings.m3u → /vod Range 点播 → TS 解析校验。
用法:
  python e2e_rec.py --iface 192.168.1.10 --group 233.50.201.118 --port 5140 [--seconds 5] [--keep]
无 IPTV 网络时请用 selftest_rec.py（合成数据，全平台可跑）。
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'src'))

import proxy
import record
from tsutil import TSAnalyzer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--iface', required=True)
    ap.add_argument('--group', required=True)
    ap.add_argument('--port', type=int, default=5140)
    ap.add_argument('--seconds', type=int, default=5)
    ap.add_argument('--http-port', type=int, default=19998)
    ap.add_argument('--keep', action='store_true', help='保留录像目录')
    args = ap.parse_args()
    rd = tempfile.mkdtemp(prefix='rec_e2e_')
    ch_file = os.path.join(rd, 'ch.json')
    with open(ch_file, 'w', encoding='utf-8') as f:
        json.dump({'channels': [{'name': 'E2E', 'group': args.group, 'port': args.port,
                                 'cat': '未分类', 'ok': True}]}, f)
    out = os.path.join(rd, 'result.json')
    print('[1/4] record start 实录 %ds …' % args.seconds)
    r = subprocess.run([sys.executable, os.path.join(HERE, 'rec_cli.py'), 'record', 'start',
                        '--channels', ch_file, '--name', 'E2E',
                        '--seconds', str(args.seconds), '--record-dir', rd,
                        '--iface', args.iface, '--out', out],
                       capture_output=True, timeout=args.seconds + 60)
    d = json.load(open(out, encoding='utf-8'))
    assert d['ok'], '录制失败: %s' % d
    rec = d['recording']
    assert rec['bytes'] > 100000, '收到字节过少(%d)，组播未到达此网卡？' % rec['bytes']
    assert abs(rec['duration'] - args.seconds) <= 8, \
        '时长偏差过大: %s (期望 %ds)' % (rec['duration'], args.seconds)
    print('    OK: %s bytes=%d duration=%ss gaps=%d' % (
        rec['id'], rec['bytes'], rec['duration'], rec['gaps']))
    print('[2/4] 启动常驻服务（转发+点播）…')
    mgr = record.RecordManager(rd, args.iface, scheduler=False)
    srv = proxy.ProxyServer(args.iface, args.http_port, record_mgr=mgr)
    ok, msg = srv.start()
    assert ok, msg
    base = 'http://127.0.0.1:%d' % args.http_port
    try:
        print('[3/4] /recordings.m3u + /vod Range 点播 …')
        with urllib.request.urlopen(base + '/recordings.m3u', timeout=5) as r:
            m3u_text = r.read().decode('utf-8')
        assert '/vod/' + rec['id'] in m3u_text and '#EXTINF:' in m3u_text
        want = min(2000000, rec['bytes'])
        req = urllib.request.Request(base + '/vod/' + rec['id'])
        req.add_header('Range', 'bytes=0-%d' % (want - 1))
        with urllib.request.urlopen(req, timeout=10) as r:
            assert r.status == 206, r.status
            head = r.read()
        assert len(head) == want, len(head)
        print('    OK: 206 Partial Content, %d bytes' % want)
        print('[4/4] TS 解析校验（点播内容可解码）…')
        ana = TSAnalyzer()
        ana.feed(head)
        assert ana.ready, '点播字节流未解析出音视频'
        print('    OK: video=%s audio=%s name=%r' % (
            ana.video_codec, ana.audio_codec, ana.service_name()))
    finally:
        srv.stop()
    if not args.keep:
        import shutil
        shutil.rmtree(rd, ignore_errors=True)
    else:
        print('录像目录保留: %s' % rd)
    print('E2E PASS（真实网络录制→点播闭环）')


if __name__ == '__main__':
    main()
