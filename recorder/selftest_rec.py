# -*- coding: utf-8 -*-
"""无双IPTV录像工具 · 独立自测（合成 TS/假socket/假时钟/XMLTV + HTTP Range 回环）。
用法: python selftest_rec.py   （无需网络/IPTV/管理员；主工具 selftest 不受影响）
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'src'))

import epg
import m3u
import proxy
import record
from selftest import make_test_ts  # 复用主工具合成 TS 构造器（仅测试依赖）

RESULTS = []


def check(name, cond, extra=''):
    RESULTS.append((name, bool(cond)))
    print('%s %s %s' % ('PASS' if cond else 'FAIL', name, extra))


class FakeSock:
    """有限包序列 + 耗尽后模拟断流超时（触发 Recorder gap/重加组路径）。"""

    def __init__(self, packets):
        self.packets = list(packets)
        self.i = 0

    def recvfrom(self, n):
        if self.i < len(self.packets):
            d = self.packets[self.i]
            self.i += 1
            return d, ('10.0.0.1', 5140)
        time.sleep(0.03)
        raise socket.timeout()

    def close(self):
        pass


def ts_chunks(data, n=1316):
    return [data[i:i + n] for i in range(0, len(data), n)]


def rtp_wrap(chunk):
    return bytes([0x80, 0x21, 0x00, 0x01, 0, 0, 0, 0, 0, 0, 0, 0]) + chunk


def wait_for(fn, timeout=8.0, interval=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if fn():
            return True
        time.sleep(interval)
    return fn()


CH = {'name': 'CCTV1', 'group': '233.50.201.118', 'port': 5140}


# ---------- Recorder ----------
def test_recorder():
    ts = make_test_ts()
    tmp = tempfile.mkdtemp(prefix='rec_st_')
    # 基本录制（裸 TS）
    out = os.path.join(tmp, 'a.ts')
    r = record.Recorder(CH, '127.0.0.1', out, sock_factory=lambda: FakeSock(ts_chunks(ts)))
    th = r.start()
    time.sleep(0.4)
    r.stop()
    th.join(5)
    data = open(out, 'rb').read()
    check('录制: 裸TS字节一致', data == ts, 'bytes=%d' % len(data))
    check('录制: stats 正确', r.stats['bytes'] == len(ts) and r.stats['pkts'] > 0
          and not r.stats['error'], str(r.stats['gaps']))
    # RTP 封装
    out2 = os.path.join(tmp, 'b.ts')
    r2 = record.Recorder(CH, '127.0.0.1', out2,
                         sock_factory=lambda: FakeSock([rtp_wrap(c) for c in ts_chunks(ts)]))
    th2 = r2.start()
    time.sleep(0.4)
    r2.stop()
    th2.join(5)
    check('录制: RTP 剥离后字节一致', open(out2, 'rb').read() == ts)
    # 分段
    out3 = os.path.join(tmp, 'c.ts')
    r3 = record.Recorder(CH, '127.0.0.1', out3,
                         sock_factory=lambda: FakeSock(ts_chunks(ts)),
                         part_max_bytes=1000)
    th3 = r3.start()
    time.sleep(0.4)
    r3.stop()
    th3.join(5)
    total = sum(os.path.getsize(p['file']) for p in r3.stats['parts'])
    check('录制: 自动分段', len(r3.stats['parts']) >= 2 and total == len(ts),
          'parts=%d' % len(r3.stats['parts']))
    # 磁盘保护
    out4 = os.path.join(tmp, 'd.ts')
    r4 = record.Recorder(CH, '127.0.0.1', out4,
                         sock_factory=lambda: FakeSock(ts_chunks(ts)),
                         disk_usage_fn=lambda p: SimpleNamespace(free=1))
    th4 = r4.start()
    th4.join(5)
    check('录制: 磁盘不足优雅停止', r4.stats['error'] == 'disk_full')
    # 提前停止 → ended_early
    out5 = os.path.join(tmp, 'e.ts')
    r5 = record.Recorder(CH, '127.0.0.1', out5,
                         sock_factory=lambda: FakeSock(ts_chunks(ts)),
                         end_time=datetime.now() + timedelta(hours=1))
    th5 = r5.start()
    time.sleep(0.3)
    r5.stop()
    th5.join(5)
    check('录制: 提前停止标记 ended_early', r5.stats.get('ended_early') is True)


# ---------- RecordManager ----------
def test_manager():
    ts = make_test_ts()
    tmp = tempfile.mkdtemp(prefix='rec_mgr_')
    clock = [datetime(2026, 11, 23, 19, 0, 0)]
    mgr = record.RecordManager(tmp, '127.0.0.1', now_fn=lambda: clock[0],
                               sock_factory=lambda: FakeSock(ts_chunks(ts)),
                               scheduler=True, pad_before=60, pad_after=120)
    mgr.start()
    # 预约：19:02~19:03，pad 后 19:01 启动、19:05 结束
    sch = mgr.add_schedule(CH, clock[0] + timedelta(seconds=120),
                           clock[0] + timedelta(seconds=180))
    clock[0] = datetime(2026, 11, 23, 19, 1, 30)
    ok = wait_for(lambda: mgr.status()['active'])
    check('调度: 到点(含提前量)自动启动', ok)
    clock[0] = datetime(2026, 11, 23, 19, 5, 1)
    ok = wait_for(lambda: any(r['status'] == 'done' for r in mgr.list_recordings()))
    recs = mgr.list_recordings()
    schs = mgr.list_schedules()
    check('调度: 到点(含延后量)自动收尾', ok and schs[0]['status'] == 'done',
          str([r['status'] for r in recs]))
    check('调度: 索引/计划落盘一致',
          os.path.exists(os.path.join(tmp, 'recordings.json'))
          and os.path.exists(os.path.join(tmp, 'records.json'))
          and recs[0]['bytes'] > 0 and recs[0]['parts'])
    mgr.stop()
    # 冲突检测
    try:
        mgr.add_schedule(CH, datetime(2026, 11, 23, 20, 0), datetime(2026, 11, 23, 21, 0))
        mgr.add_schedule(CH, datetime(2026, 11, 23, 20, 30), datetime(2026, 11, 23, 21, 30))
        check('调度: 同频道重叠拒绝', False)
    except ValueError:
        check('调度: 同频道重叠拒绝', True)
    # 即时录（scheduler=False 场景）
    tmp2 = tempfile.mkdtemp(prefix='rec_now_')
    m2 = record.RecordManager(tmp2, '127.0.0.1',
                              sock_factory=lambda: FakeSock(ts_chunks(ts)), scheduler=False)
    sch2 = m2.record_now(CH, seconds=3600)
    check('即时录: 返回 rid', bool(sch2.get('rid')))
    wait_for(lambda: m2.get_recording(sch2['rid'])
             and m2.get_recording(sch2['rid'])['bytes'] > 0)
    m2.stop()  # 提前停止 → partial + 索引落盘
    r2 = m2.get_recording(sch2['rid'])
    check('即时录: 停止收尾为 partial 且落盘', r2['status'] == 'partial' and r2['bytes'] > 0,
          r2['status'])
    # 即时录时长精确（不吃预约 pad）
    tmp4 = tempfile.mkdtemp(prefix='rec_pad_')
    clock4 = [datetime(2026, 11, 23, 20, 0, 0)]
    m4 = record.RecordManager(tmp4, '127.0.0.1', now_fn=lambda: clock4[0],
                              sock_factory=lambda: FakeSock(ts_chunks(ts)), scheduler=True)
    m4.start()
    sch4 = m4.record_now(CH, seconds=60)
    wait_for(lambda: m4.status()['active'])
    clock4[0] = clock4[0] + timedelta(seconds=61)
    ok = wait_for(lambda: not m4.status()['active'])
    rec4 = m4.get_recording(sch4['rid'])
    check('即时录: 时长精确不吃预约余量', ok and rec4['status'] == 'done'
          and rec4['duration'] <= 65, 'duration=%s' % rec4['duration'])
    m4.stop()
    # 跨进程取消：外部进程写 canceled → 拥有进程 tick 拾取停止并收尾
    tmp6 = tempfile.mkdtemp(prefix='rec_xcancel_')
    m6 = record.RecordManager(tmp6, '127.0.0.1',
                              sock_factory=lambda: FakeSock(ts_chunks(ts)), scheduler=True)
    m6.start()
    sch6 = m6.record_now(CH, seconds=3600)
    wait_for(lambda: m6.status()['active'])
    m6ext = record.RecordManager(tmp6, '127.0.0.1', scheduler=False)
    m6ext.cancel(sch6['id'])
    ok = wait_for(lambda: not m6.status()['active'])
    r6 = m6.get_recording(sch6['rid'])
    check('跨进程: cancel 信号被拥有进程拾取', ok and r6['status'] == 'partial',
          r6['status'])
    m6.stop()
    # 外部并发上限
    tmp3 = tempfile.mkdtemp(prefix='rec_conc_')
    with open(os.path.join(tmp3, 'recordings.json'), 'w', encoding='utf-8') as f:
        json.dump([{'id': 'ext1', 'status': 'recording', 'parts': []},
                   {'id': 'ext2', 'status': 'recording', 'parts': []}], f)
    m3 = record.RecordManager(tmp3, '127.0.0.1', max_concurrent=2, scheduler=False,
                              sock_factory=lambda: FakeSock(ts_chunks(ts)))
    try:
        m3.record_now(CH, seconds=60)
        check('并发: 跨进程上限生效', False)
    except ValueError:
        check('并发: 跨进程上限生效', True)


def test_recovery_quota():
    ts = make_test_ts()
    tmp = tempfile.mkdtemp(prefix='rec_recov_')
    os.makedirs(os.path.join(tmp, 'ts'))
    clock = [datetime(2026, 11, 23, 19, 10, 0)]
    rid = 'r20261123_190000_CCTV1'
    p1 = os.path.join(tmp, 'ts', rid + '.ts')
    with open(p1, 'wb') as f:
        f.write(ts)
    # 崩溃现场：recording 中 + 计划未结束；另有过期 pending
    with open(os.path.join(tmp, 'records.json'), 'w', encoding='utf-8') as f:
        json.dump([
            {'id': 's1', 'channel': CH, 'start': '2026-11-23T19:00:00',
             'end': '2026-11-23T19:30:00', 'status': 'recording', 'rid': rid,
             'source': 'manual', 'epg_title': '', 'error': '', 'created': ''},
            {'id': 's2', 'channel': CH, 'start': '2026-11-23T18:00:00',
             'end': '2026-11-23T18:30:00', 'status': 'pending', 'rid': '',
             'source': 'manual', 'epg_title': '', 'error': '', 'created': ''}], f)
    with open(os.path.join(tmp, 'recordings.json'), 'w', encoding='utf-8') as f:
        json.dump([{'id': rid, 'name': 'CCTV1', 'epg_title': '', 'group': CH['group'],
                    'port': CH['port'], 'start': '2026-11-23T19:00:00', 'end': '',
                    'duration': 0, 'bytes': len(ts),
                    'parts': [{'file': 'ts/' + rid + '.ts', 'bytes': len(ts)}],
                    'status': 'recording', 'gaps': 0, 'error': ''}], f)
    mgr = record.RecordManager(tmp, '127.0.0.1', now_fn=lambda: clock[0],
                               sock_factory=lambda: FakeSock(ts_chunks(ts)), scheduler=False)
    mgr.start()
    check('恢复: recording 续录剩余时段', len(mgr.status()['active']) == 1)
    check('恢复: 过期 pending 标记 missed',
          any(s['id'] == 's2' and s['status'] == 'missed' for s in mgr.list_schedules()))
    mgr.stop()
    r = mgr.get_recording(rid)
    check('恢复: 续录分段并入同一索引', r['status'] == 'partial'
          and len(r['parts']) == 2 and r['bytes'] > len(ts),
          'parts=%d bytes=%d' % (len(r['parts']), r['bytes']))
    # 索引重建
    tmp2 = tempfile.mkdtemp(prefix='rec_rebuild_')
    os.makedirs(os.path.join(tmp2, 'ts'))
    for nm in ('r20261123_190000_CCTV5.ts', 'r20261123_190000_CCTV5_p2.ts'):
        with open(os.path.join(tmp2, 'ts', nm), 'wb') as f:
            f.write(b'\x47' + b'\x00' * 187)
    m2 = record.RecordManager(tmp2, '127.0.0.1', scheduler=False)
    recs = m2.list_recordings()
    check('索引: 损坏时从文件名重建', len(recs) == 1 and recs[0]['name'] == 'CCTV5'
          and len(recs[0]['parts']) == 2 and recs[0]['bytes'] == 376)
    # 跨进程索引热重载（docker exec / CLI 即时录写入 → 常驻进程可见）
    tmp5 = tempfile.mkdtemp(prefix='rec_hot_')
    m5 = record.RecordManager(tmp5, '127.0.0.1', scheduler=False)
    ext = {'id': 'extdone', 'name': 'X', 'epg_title': '', 'group': '', 'port': 0,
           'start': '2026-11-23T19:00:00', 'end': '2026-11-23T19:10:00',
           'duration': 600, 'bytes': 100, 'parts': [], 'status': 'done', 'gaps': 0, 'error': ''}
    with open(os.path.join(tmp5, 'recordings.json'), 'w', encoding='utf-8') as f:
        json.dump([ext], f)
    os.utime(os.path.join(tmp5, 'recordings.json'), (time.time() + 2, time.time() + 2))
    check('索引: 跨进程热重载', any(r['id'] == 'extdone' for r in m5.list_recordings()))
    # 配额 LRU
    tmp3 = tempfile.mkdtemp(prefix='rec_quota_')
    os.makedirs(os.path.join(tmp3, 'ts'))
    m3 = record.RecordManager(tmp3, '127.0.0.1', quota_gb=3 / 1024 ** 2, scheduler=False)
    recs3 = []
    for i, t in enumerate(('19:00:00', '20:00:00', '21:00:00')):
        rid3 = 'r%d' % i
        p = os.path.join(tmp3, 'ts', rid3 + '.ts')
        with open(p, 'wb') as f:
            f.write(b'\x00' * 2048)
        recs3.append({'id': rid3, 'name': 'C%d' % i, 'epg_title': '', 'group': '', 'port': 0,
                      'start': '2026-11-23T' + t, 'end': '2026-11-23T' + t,
                      'duration': 60, 'bytes': 2048,
                      'parts': [{'file': 'ts/' + rid3 + '.ts', 'bytes': 2048}],
                      'status': 'done', 'gaps': 0, 'error': ''})
    m3.recordings = recs3
    m3._save_recordings()
    m3.cleanup_quota()
    left = m3.list_recordings()
    check('配额: LRU 只留最新且不误删', len(left) == 1 and left[0]['id'] == 'r2'
          and not os.path.exists(os.path.join(tmp3, 'ts', 'r0.ts')))


# ---------- HTTP 点播 ----------
def test_vod():
    tmp = tempfile.mkdtemp(prefix='rec_vod_')
    os.makedirs(os.path.join(tmp, 'ts'))
    data = bytes(range(256)) * 40  # 10240B
    rid = 'r20261123_190000_TEST'
    with open(os.path.join(tmp, 'ts', rid + '.ts'), 'wb') as f:
        f.write(data[:5120])
    with open(os.path.join(tmp, 'ts', rid + '_p2.ts'), 'wb') as f:
        f.write(data[5120:])
    mgr = record.RecordManager(tmp, '127.0.0.1', scheduler=False)
    mgr.recordings = [{'id': rid, 'name': 'TEST', 'epg_title': '测试节目',
                       'group': '', 'port': 0, 'start': '2026-11-23T19:00:00',
                       'end': '2026-11-23T20:00:00', 'duration': 3600, 'bytes': 10240,
                       'parts': [{'file': 'ts/' + rid + '.ts', 'bytes': 5120},
                                 {'file': 'ts/' + rid + '_p2.ts', 'bytes': 5120}],
                       'status': 'done', 'gaps': 0, 'error': ''}]
    mgr._save_recordings()
    port = 19876
    srv = proxy.ProxyServer('127.0.0.1', port, record_mgr=mgr)
    ok, msg = srv.start()
    check('点播: 服务启动', ok, msg)
    base = 'http://127.0.0.1:%d' % port

    def get(path, rng=None, method='GET'):
        req = urllib.request.Request(base + path, method=method)
        if rng:
            req.add_header('Range', rng)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    try:
        st, hd, body = get('/vod/' + rid)
        check('点播: 200 全量字节一致', st == 200 and body == data
              and hd.get('Accept-Ranges') == 'bytes')
        st, hd, body = get('/vod/' + rid, 'bytes=100-199')
        check('点播: 206 Range 精确', st == 206 and body == data[100:200]
              and hd.get('Content-Range') == 'bytes 100-199/10240')
        st, hd, body = get('/vod/' + rid, 'bytes=5000-5300')
        check('点播: 跨分段虚拟拼接', st == 206 and body == data[5000:5301])
        st, hd, body = get('/vod/' + rid, 'bytes=-100')
        check('点播: 后缀范围', st == 206 and body == data[-100:])
        st, hd, body = get('/vod/' + rid, 'bytes=99999-')
        check('点播: 越界 416', st == 416 and hd.get('Content-Range') == 'bytes */10240')
        st, hd, body = get('/vod/' + rid, method='HEAD')
        check('点播: HEAD 探测', st == 200 and hd.get('Content-Length') == '10240'
              and body == b'')
        st, _, _ = get('/vod/nonexistent')
        check('点播: 未知 rid 404', st == 404)
        st, _, _ = get('/vod/x..y')
        check('点播: 非法 rid(路径穿越) 404', st == 404)
        st, _, body = get('/recordings.m3u')
        text = body.decode('utf-8')
        check('点播: 录像列表 M3U', st == 200 and '#EXTINF:3600' in text
              and 'group-title="录像"' in text and '/vod/' + rid in text
              and '测试节目' in text)
        st, _, body = get('/recordings.json')
        check('点播: 录像索引 JSON', st == 200 and json.loads(body)[0]['id'] == rid)
        st, _, body = get('/status')
        check('点播: /status 含录像状态', st == 200 and 'recordings' in json.loads(body))
        st, _, body = get('/playlist.m3u')
        check('兼容: 无录像参数时旧端点不变', st == 200 and body.startswith(b'#EXTM3U'))
    finally:
        srv.stop()
    # 向后兼容：不带 record_mgr 时 /vod 404、/status 无 recordings
    srv2 = proxy.ProxyServer('127.0.0.1', port + 1)
    srv2.start()
    try:
        req = urllib.request.Request('http://127.0.0.1:%d/status' % (port + 1))
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.loads(r.read())
        check('兼容: 主工具模式零变化', 'recordings' not in d)
    finally:
        srv2.stop()


# ---------- EPG ----------
def test_epg():
    now = datetime.now()
    s1 = (now + timedelta(hours=1)).strftime('%Y%m%d%H%M%S') + ' +0800'
    e1 = (now + timedelta(hours=2)).strftime('%Y%m%d%H%M%S') + ' +0800'
    xml = ('<?xml version="1.0" encoding="UTF-8"?><tv>'
           '<channel id="c1"><display-name>CCTV-1综合</display-name></channel>'
           '<channel id="c2"><display-name>湖南卫视高清</display-name></channel>'
           '<programme channel="c1" start="%s" stop="%s"><title>测试节目</title>'
           '<desc>描述</desc></programme></tv>' % (s1, e1)).encode('utf-8')
    parsed = epg.parse_xmltv(xml)
    check('EPG: XMLTV 解析', len(parsed['channels']) == 2 and len(parsed['programmes']) == 1)
    mapped, unmapped = epg.map_channels([{'name': 'CCTV1'}, {'name': '湖南卫视'},
                                         {'name': '未知频道'}], parsed['channels'])
    check('EPG: 别名映射(CCTV-1综合/卫视高清)', 'CCTV1' in mapped and '湖南卫视' in mapped
          and unmapped == ['未知频道'], str(mapped))
    p = parsed['programmes'][0]
    check('EPG: 时区解析为本地时间', p[1].hour == (now + timedelta(hours=1)).hour
          or abs((p[1] - (now + timedelta(hours=1))).total_seconds()) < 3600)
    # 缓存查询
    tmp = tempfile.mkdtemp(prefix='rec_epg_')
    start = (now + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%S')
    stop = (now + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%S')
    with open(os.path.join(tmp, 'epg.json'), 'w', encoding='utf-8') as f:
        json.dump({'updated': '', 'source': 'test',
                   'channels': {'CCTV1': [{'title': '测试节目', 'start': start,
                                           'stop': stop, 'desc': ''}]}}, f)
    check('EPG: programs 查询', len(epg.programs(tmp, 'CCTV-1综合')) == 1)
    nxt = epg.find_next(tmp, 'CCTV1', '测试')
    check('EPG: find_next 关键词', nxt is not None and nxt['title'] == '测试节目')
    check('EPG: find_next 日期过滤', epg.find_next(tmp, 'CCTV1', '测试', '2000-01-01') is None)
    rep = epg.map_report(tmp, [{'name': 'CCTV1'}, {'name': '湖南卫视'}])
    check('EPG: 映射报告', rep['ok'] and len(rep['mapped']) == 1
          and rep['unmapped'] == ['湖南卫视'])


def test_misc():
    check('默认目录: 系统下载文件夹子目录',
          record.default_record_dir().endswith('无双IPTV录像'))
    check('命名: 非法字符清洗', record.safe_name('CCTV-5/体育:*?') == 'CCTV-5_体育'
          and '/' not in record.safe_name('a/b\\c:d'))
    recs = [{'id': 'r1', 'name': 'A', 'status': 'done', 'start': '2026-11-23T19:00:00',
             'duration': 60, 'epg_title': ''},
            {'id': 'r2', 'name': 'B', 'status': 'done', 'start': '2026-11-23T21:00:00',
             'duration': 120, 'epg_title': '节目X'},
            {'id': 'r3', 'name': 'C', 'status': 'error', 'start': '2026-11-23T20:00:00',
             'duration': 0, 'epg_title': ''}]
    text = m3u.recordings_m3u(recs, '192.168.1.10', 9999)
    lines = text.splitlines()
    check('M3U: 录像列表倒序+真实时长', lines[1].startswith('#EXTINF:120')
          and '节目X' in lines[1] and '/vod/r2' in lines[2] and '/vod/r1' in lines[4]
          and 'r3' not in text)


def test_webui():
    ts = make_test_ts()
    tmp = tempfile.mkdtemp(prefix='rec_web_')
    mgr = record.RecordManager(tmp, '127.0.0.1',
                               sock_factory=lambda: FakeSock(ts_chunks(ts)), scheduler=True)
    mgr.start()
    port = 19879
    srv = proxy.ProxyServer('127.0.0.1', port, channels_cb=lambda: [CH], record_mgr=mgr)
    ok, msg = srv.start()
    check('Web: 服务启动', ok, msg)
    base = 'http://127.0.0.1:%d' % port

    def get(p):
        with urllib.request.urlopen(base + p, timeout=5) as r:
            return r.status, r.read()

    def post(p, obj):
        req = urllib.request.Request(base + p, data=json.dumps(obj).encode(),
                                     headers={'Content-Type': 'application/json'},
                                     method='POST')
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())

    try:
        st, body = get('/')
        check('Web: 管理页 HTML', st == 200 and b'/api/state' in body
              and '无双'.encode('utf-8') in body)
        st, body = get('/api/state')
        d = json.loads(body)
        check('Web: state 含频道/录像/计划', d['ok'] and d['channels'][0]['group'] == CH['group']
              and 'recordings' in d and 'schedules' in d)
        r = post('/api/record/start', {'group': CH['group'], 'port': CH['port'],
                                       'name': 'CCTV1', 'seconds': 3600})
        rid = r['schedule']['rid']
        check('Web: API 开始录制', r['ok'] and wait_for(lambda: mgr.status()['active']))
        r = post('/api/record/stop', {'rid': rid})
        ok2 = wait_for(lambda: not mgr.status()['active'])
        rec = mgr.get_recording(rid)
        check('Web: API 停止录制', r['ok'] and ok2 and rec['status'] == 'partial')
        r = post('/api/schedule/add', {'group': CH['group'], 'port': CH['port'], 'name': 'CCTV1',
                                       'start': '2026-12-01T19:00:00',
                                       'end': '2026-12-01T20:00:00'})
        sid = r['schedule']['id']
        check('Web: API 添加预约', r['ok'])
        r = post('/api/schedule/cancel', {'id': sid})
        check('Web: API 取消预约', r['ok'])
        r = post('/api/recording/delete', {'id': rid})
        check('Web: API 删除录像', r['ok'] and mgr.get_recording(rid) is None)
        st, body = get('/api/programs?name=CCTV1')
        check('Web: programs API', json.loads(body)['ok'])
        r = post('/api/record/start', {'group': 'bad', 'port': 'x'})
        check('Web: 坏参数返回错误 JSON', r['ok'] is False)
        r = post('/api/settings', {'quota_gb': 55})
        check('Web: 容量设置生效', r['ok'] and r['settings']['quota_gb'] == 55)
        st, body = get('/api/state')
        d3 = json.loads(body)
        check('Web: state 含设置与 GB/小时字段', 'settings' in d3
              and 'gb_per_hour' in d3['status'])
        newdir = tempfile.mkdtemp(prefix='rec_webdir_')
        r = post('/api/settings', {'quota_gb': 55, 'record_dir': newdir})
        st, body = get('/api/state')
        d4 = json.loads(body)
        check('Web: 换文件夹重建管理器', r['ok']
              and d4['settings']['record_dir'] == os.path.abspath(newdir))
        check('设置: 锚目录 settings.json 落盘',
              os.path.exists(os.path.join(tmp, 'settings.json')))
    finally:
        srv.stop()
        if srv.record_mgr is not None:
            srv.record_mgr.stop()


def test_settings():
    tmp = tempfile.mkdtemp(prefix='rec_set_')
    m = record.RecordManager(tmp, '127.0.0.1', scheduler=False)
    check('设置: 默认容量 100G', m.quota_gb == 100)
    m.save_settings(quota_gb=5)
    m2 = record.RecordManager(tmp, '127.0.0.1', scheduler=False)
    check('设置: 容量持久化重载', m2.quota_gb == 5)
    sub = os.path.join(tmp, 'sub')
    m2.save_settings(record_dir=sub)
    m3 = record.RecordManager(tmp, '127.0.0.1', scheduler=False)
    check('设置: 文件夹覆盖生效且锚不变', m3.record_dir == os.path.abspath(sub)
          and m3.base_dir == os.path.abspath(tmp))


def main():
    test_recorder()
    test_manager()
    test_recovery_quota()
    test_vod()
    test_epg()
    test_misc()
    test_webui()
    test_settings()
    failed = [n for n, ok in RESULTS if not ok]
    print('\n%d/%d PASS' % (len(RESULTS) - len(failed), len(RESULTS)))
    if failed:
        print('FAILED:', failed)
        sys.exit(1)
    print('ALL PASS')


if __name__ == '__main__':
    main()
