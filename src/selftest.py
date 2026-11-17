# -*- coding: utf-8 -*-
"""自测：合成 TS/pcap/pcapng/SLL + M3U 往返 + 向导逻辑 + 参考库 + 跨平台层。
用法: python selftest.py [--real]  (--real 追加真实 test.ts / cap.pcap 测试)
"""
import os
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capture
import channeldb
import m3u
import naspush
import netutil
import tsutil
import wizard

RESULTS = []


def check(name, cond, extra=''):
    RESULTS.append((name, bool(cond)))
    print('%s %s %s' % ('PASS' if cond else 'FAIL', name, extra))


# ---------- 合成 TS ----------
class _BW:
    def __init__(self):
        self.bits = []

    def u(self, v, n):
        for i in range(n - 1, -1, -1):
            self.bits.append((v >> i) & 1)

    def ue(self, v):
        v += 1
        n = v.bit_length()
        self.u(0, n - 1)
        self.u(v, n)

    def bytes(self):
        bits = self.bits + [1] + [0] * 7
        bits = bits[:len(bits) // 8 * 8]
        out = bytearray()
        for i in range(0, len(bits), 8):
            b = 0
            for j in range(8):
                b = (b << 1) | bits[i + j]
            out.append(b)
        return bytes(out)


def make_sps_1080():
    bw = _BW()
    bw.u(100, 8); bw.u(0, 8); bw.u(40, 8)
    bw.ue(0)          # sps id
    bw.ue(1)          # chroma 4:2:0
    bw.ue(0); bw.ue(0)  # bit depth -8
    bw.u(0, 1)        # qpprime
    bw.u(0, 1)        # scaling matrix
    bw.ue(0)          # log2 max frame num -4
    bw.ue(0)          # poc type
    bw.ue(0)          # log2 max poc -4
    bw.ue(1)          # max ref frames
    bw.u(0, 1)        # gaps
    bw.ue(119)        # width mbs -1 → 1920
    bw.ue(67)         # height map units -1 → 1088
    bw.u(1, 1)        # frame_mbs_only
    bw.u(1, 1)        # direct 8x8
    bw.u(1, 1)        # crop
    bw.ue(0); bw.ue(0); bw.ue(0); bw.ue(4)  # crop → 1080
    return b'\x67' + bw.bytes()


def ts_packet(pid, payload, pusi=False, cc=0):
    hdr = bytes([0x47, ((0x40 if pusi else 0) | ((pid >> 8) & 0x1F)), pid & 0xFF,
                 0x10 | (cc & 0x0F)])
    body = payload[:184]
    return hdr + body + b'\xff' * (184 - len(body))


def psi_packet(pid, section, cc=0):
    return ts_packet(pid, b'\x00' + section, pusi=True, cc=cc)


def crc_placeholder(section_body):
    return section_body + b'\x00\x00\x00\x00'


def make_test_ts():
    # PAT: program 1 → PMT PID 0x100
    pat_body = bytes([0x00, 0x01, 0xC1, 0x00, 0x00]) + bytes([0x00, 0x01, 0xE1, 0x00])
    pat = bytes([0x00, 0xB0 | ((len(pat_body) + 4) >> 8), (len(pat_body) + 4) & 0xFF]) + pat_body
    pat = crc_placeholder(pat)
    # PMT: h264 PID 0x101, mp2 PID 0x102
    pmt_body = bytes([0x00, 0x01, 0xC1, 0x00, 0x00, 0xE1, 0x01, 0xF0, 0x00,
                      0x1B, 0xE1, 0x01, 0xF0, 0x00,
                      0x04, 0xE1, 0x02, 0xF0, 0x00])
    pmt = bytes([0x02, 0xB0 | ((len(pmt_body) + 4) >> 8), (len(pmt_body) + 4) & 0xFF]) + pmt_body
    pmt = crc_placeholder(pmt)
    # SDT: service 1, name 'CCTV-1测试'
    name = 'CCTV-1测试'.encode('utf-8')
    desc = bytes([0x48, 1 + 1 + 0 + 1 + len(name), 0x01, 0x00, len(name)]) + name
    svc = bytes([0x00, 0x01, 0xFC, 0x80 | ((len(desc) >> 8) & 0x0F), len(desc) & 0xFF]) + desc
    sdt_body = bytes([0x00, 0x01, 0xC1, 0x00, 0x00, 0x00, 0x01, 0xFF]) + svc
    sdt = bytes([0x42, 0xF0 | ((len(sdt_body) + 4) >> 8), (len(sdt_body) + 4) & 0xFF]) + sdt_body
    sdt = crc_placeholder(sdt)
    # 视频 PES 含 SPS
    sps = make_sps_1080()
    annexb = b'\x00\x00\x00\x01' + sps + b'\x00\x00\x00\x01\x68\xce\x3c\x80'
    pes = b'\x00\x00\x01\xe0\x00\x00\x80\x80\x00' + annexb
    pkts = []
    for rep in range(3):
        pkts.append(psi_packet(0x0000, pat, rep))
        pkts.append(psi_packet(0x0100, pmt, rep))
        pkts.append(psi_packet(0x0011, sdt, rep))
    # 视频分片
    cc = 0
    for i in range(0, len(pes), 184):
        pkts.append(ts_packet(0x0101, pes[i:i + 184], pusi=(i == 0), cc=cc))
        cc = (cc + 1) & 0x0F
    for i in range(40):
        pkts.append(ts_packet(0x0102, b'\xff\xfb\x90\x00' + b'\x00' * 180, cc=i & 0x0F))
    return b''.join(pkts)


def test_ts():
    data = make_test_ts()
    ana = tsutil.TSAnalyzer()
    ana.feed(data)
    check('TS: 同步+PAT+PMT', ana.ready, 'video=%s audio=%s' % (ana.video_codec, ana.audio_codec))
    check('TS: h264+mp2', ana.video_codec == 'h264' and ana.audio_codec == 'mp2')
    check('TS: SDT 频道名', ana.service_name() == 'CCTV-1测试', repr(ana.service_name()))
    check('TS: SPS 分辨率 1920x1080', ana.resolution == '1920x1080', str(ana.resolution))
    # RTP 封装
    rtp = bytes([0x80, 0x21, 0x00, 0x01, 0, 0, 0, 0, 0, 0, 0, 0]) + data
    check('TS: RTP 剥离', tsutil.strip_rtp(rtp) == data)
    check('TS: 裸 TS 直通', tsutil.strip_rtp(data) == data)


# ---------- 合成 pcap / pcapng ----------
def eth_ip_udp(src_ip, dst_ip, sport, dport, payload, ip_id=1, proto=17):
    eth = bytes.fromhex('01005e000001') + bytes.fromhex('021122334455') + b'\x08\x00'
    ip = bytearray(20)
    ip[0] = 0x45
    total = 20 + (8 + len(payload) if proto == 17 else len(payload))
    ip[2:4] = struct.pack('!H', total)
    ip[4:6] = struct.pack('!H', ip_id)
    ip[8] = 64
    ip[9] = proto
    ip[12:16] = bytes(int(x) for x in src_ip.split('.'))
    ip[16:20] = bytes(int(x) for x in dst_ip.split('.'))
    if proto == 17:
        udp = struct.pack('!HHHH', sport, dport, 8 + len(payload), 0)
        return eth + bytes(ip) + udp + payload
    return eth + bytes(ip) + payload


def igmp_report(group, ip_id=2):
    payload = bytes([0x16, 0x00, 0x00, 0x00]) + bytes(int(x) for x in group.split('.'))
    return eth_ip_udp('10.10.10.2', group, 0, 0, payload, ip_id=ip_id, proto=2)


def make_pcap(path, ts_data):
    pkts = [igmp_report('233.50.201.118')]
    chunk = ts_data[:1316]
    for i in range(10):
        pkts.append(eth_ip_udp('10.20.30.40', '233.50.201.118', 5000, 5140, chunk, ip_id=100 + i))
    pkts.append(eth_ip_udp('192.168.1.1', '239.255.255.250', 1900, 1900, b'NOTIFY', ip_id=999))
    with open(path, 'wb') as f:
        f.write(struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, 1))
        for i, p in enumerate(pkts):
            # pktmon 风格重复 8 份
            for _ in range(8):
                f.write(struct.pack('<IIII', 1700000000 + i, i * 1000, len(p), len(p)))
                f.write(p)


def make_pcapng(path, ts_data):
    pkts = [igmp_report('233.50.201.118')]
    chunk = ts_data[:1316]
    for i in range(10):
        pkts.append(eth_ip_udp('10.20.30.40', '233.50.201.118', 5000, 5140, chunk, ip_id=100 + i))
    pkts.append(eth_ip_udp('192.168.1.1', '239.255.255.250', 1900, 1900, b'NOTIFY', ip_id=999))

    def block(btype, body):
        blen = 12 + len(body)
        return struct.pack('<II', btype, blen) + body + struct.pack('<I', blen)

    shb_body = struct.pack('<IHHq', 0x1A2B3C4D, 1, 0, -1)
    idb_body = struct.pack('<HHI', 1, 0, 65535)
    out = block(0x0A0D0D0A, shb_body) + block(0x00000001, idb_body)
    for i, p in enumerate(pkts):
        ts = (1700000000 + i) * 1_000_000 + i * 1000
        epb = struct.pack('<IIIII', 0, ts >> 32, ts & 0xFFFFFFFF, len(p), len(p)) + p
        pad = (-len(p)) % 4
        epb += b'\x00' * pad
        for _ in range(8):
            out += block(0x00000006, epb)
    with open(path, 'wb') as f:
        f.write(out)


def test_capture():
    ts_data = make_test_ts()
    tmp = tempfile.mkdtemp(prefix='iptv_selftest_')
    pcap = os.path.join(tmp, 't.pcap')
    pcapng = os.path.join(tmp, 't.pcapng')
    make_pcap(pcap, ts_data)
    make_pcapng(pcapng, ts_data)
    for path, kind in ((pcap, 'pcap'), (pcapng, 'pcapng')):
        r = capture.analyze(path)
        flows = [f for f in r['flows'] if not f['noise']]
        ok = (len(flows) == 1 and flows[0]['group'] == '233.50.201.118'
              and flows[0]['port'] == 5140 and flows[0]['pkts'] == 10)
        check('抓包: %s 组播流+去重' % kind, ok,
              'pkts=%s unique=%s' % (flows[0]['pkts'] if flows else '-', r['stats']['unique']))
        check('抓包: %s IGMP 加组' % kind, r['joins'].get('233.50.201.118') == 1)
        check('抓包: %s 噪声标记' % kind, any(f['noise'] for f in r['flows']))


def test_m3u():
    tmp = tempfile.mkdtemp(prefix='iptv_selftest_')
    chans = [
        {'name': 'CCTV1', 'group': '233.50.201.118', 'port': 5140, 'cat': '央视高清', 'ok': True},
        {'name': '浙江卫视', 'group': '233.50.201.100', 'port': 5140, 'cat': '卫视高清', 'ok': True},
        {'name': '停播台', 'group': '233.50.200.191', 'port': 5140, 'cat': '国际标清', 'ok': False},
    ]
    p1 = os.path.join(tmp, 'a.m3u')
    n = m3u.write_m3u(p1, chans, fmt='udp', only_ok=True)
    back = m3u.read_m3u(p1)
    check('M3U: udp 往返', n == 2 and len(back) == 2 and back[0]['group'] == '233.50.201.118'
          and back[0]['name'] == 'CCTV1')
    p2 = os.path.join(tmp, 'b.m3u')
    m3u.write_m3u(p2, chans, fmt='udpxy', udpxy_host='192.168.1.100', udpxy_port=9999)
    back2 = m3u.read_m3u(p2)
    check('M3U: udpxy 往返', len(back2) == 2 and back2[0]['port'] == 5140)
    old = [{'name': '自定义名', 'group': '233.50.201.118', 'port': 5140, 'cat': '央视高清',
            'ok': True, 'user_named': True}]
    new = [{'name': 'CCTV1', 'group': '233.50.201.118', 'port': 5140, 'cat': '央视高清',
            'ok': True, 'video': 'h264'}]
    merged = m3u.merge_channels(old, new)
    check('M3U: 合并保留用户名', merged[0]['name'] == '自定义名' and merged[0]['video'] == 'h264')
    # 回归：已验证可用的频道，载入未验证参考候选时不应被降级
    verified = [{'name': 'CCTV1', 'group': '233.50.201.118', 'port': 5140, 'cat': '央视高清',
                 'ok': True, 'tested': True, 'video': 'h264', 'res': '1920x1080'}]
    ref_candidate = [{'name': 'CCTV1', 'group': '233.50.201.118', 'port': 5140, 'cat': '央视',
                      'ok': False, 'source': 'ref'}]
    m2 = m3u.merge_channels(verified, ref_candidate)
    check('M3U: 验证成果不被参考候选降级', m2[0]['ok'] is True and m2[0]['res'] == '1920x1080')
    # 本轮新实测失败应能覆盖旧的可用状态
    retest_bad = [{'name': 'CCTV1', 'group': '233.50.201.118', 'port': 5140, 'cat': '央视高清',
                   'ok': False, 'tested': True}]
    m3 = m3u.merge_channels(verified, retest_bad)
    check('M3U: 新实测失败可覆盖', m3[0]['ok'] is False)


def test_wizard():
    good = {'mode': 'fresh', 'pc_lan': 'yes', 'pc_wifi': 'yes', 'switch': 'dumb3',
            'stb_lan': 'yes', 'ont_port': 'lan2', 'router_wan': 'ont'}
    p = wizard.build_plan(good)
    check('向导: 标准搭线 7 步', p['ok'] and len(p['steps']) == 7, 'steps=%d' % len(p['steps']))
    check('向导: 含桥接进阶', len(p['bridge_steps']) == 2)
    bad = dict(good, pc_lan='no')
    check('向导: 无网口拦截', not wizard.build_plan(bad)['ok'])
    bad2 = dict(good, switch='none')
    check('向导: 无交换机拦截', not wizard.build_plan(bad2)['ok'])
    merged = wizard.build_plan({'mode': 'merged'})
    check('向导: 已桥接模式', merged['ok'] and merged['topology'] == 'merged')
    warn = wizard.build_plan(dict(good, switch='managed'))
    check('向导: 网管交换机警告', warn['ok'] and len(warn['warnings']) >= 1)
    # 路由器 IPTV 口场景
    rt = {'mode': 'router', 'pc_lan': 'yes', 'pc_wifi': 'yes', 'router_iptv': 'yes',
          'router_igmp': 'yes', 'stb_lan': 'yes', 'ont_port': 'itv'}
    pr = wizard.build_plan(rt)
    check('向导: 路由器场景免交换机', pr['ok'] and pr['topology'] == 'router' and len(pr['steps']) == 6)
    rt_no = dict(rt, router_iptv='no')
    check('向导: 路由不支持则拦截', not wizard.build_plan(rt_no)['ok'])
    rt_noigmp = dict(rt, router_igmp='no')
    check('向导: 无组播转发给回退提示', wizard.build_plan(rt_noigmp)['ok']
          and len(wizard.build_plan(rt_noigmp)['warnings']) >= 1)


def test_db():
    info = channeldb.db_info()
    check('参考库: 覆盖31省', info['provinces'] == 31, str(info))
    check('参考库: 频道数>10000', info['channels'] > 10000)
    e = channeldb.lookup('233.50.201.118', 5140)
    # ok 标记来自本地实测叠加表 verify_results.json（gitignore，CI 无）：
    # 有叠加表时严格断言实测可用；无叠加表时只断言在库且名称正确。
    overlay = os.path.exists(os.path.join(channeldb.app_dir(), '..', 'verify_results.json'))
    if overlay:
        check('参考库: CCTV1 实测可用', e and e['name'] == 'CCTV1' and e.get('ok'))
    else:
        check('参考库: CCTV1 在库', e and e['name'] == 'CCTV1')
    zj = channeldb.channels_for('浙江', '电信')
    check('参考库: 浙江电信列表', len(zj) >= 162, 'n=%d' % len(zj))
    gd = channeldb.channels_for('广东', '电信')
    check('参考库: 广东电信列表', len(gd) > 100, 'n=%d' % len(gd))
    check('参考库: 命名规范化', channeldb.normalize_name('CCTV-1综合') == 'CCTV1')
    txt = '央视,#genre#\nCCTV1,rtp://239.1.1.1:5140\n空频道,\n'
    parsed = channeldb.parse_txt(txt)
    check('参考库: txt解析', len(parsed) == 1 and parsed[0]['group'] == '239.1.1.1'
          and parsed[0]['cat'] == '央视')
    d = channeldb.build_db({'Multicast/beijing/unicom.txt': txt})
    check('参考库: build_db', d['regions'][0]['province'] == '北京'
          and d['regions'][0]['carrier'] == '联通')


def test_real():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ts = os.path.join(here, 'test.ts')
    if os.path.exists(ts):
        ana = tsutil.TSAnalyzer()
        with open(ts, 'rb') as f:
            raw = f.read()
        # test.ts 是 RTP 封装转储：12B RTP 头 + 1316B TS，按真实收包路径逐记录剥离
        fed = 0
        for i in range(0, len(raw) - 12, 1328):
            t = tsutil.strip_rtp(raw[i:i + 1328])
            if t:
                ana.feed(t)
                fed += 1
        check('真实 test.ts: 解析出流', ana.ready,
              'records=%d video=%s audio=%s name=%r res=%s' % (fed, ana.video_codec,
              ana.audio_codec, ana.service_name(), ana.resolution))
    else:
        print('SKIP 真实 test.ts（不存在）')
    pcap = os.path.join(here, 'cap', 'cap.pcap')
    if os.path.exists(pcap) and '--full' in sys.argv:
        r = capture.analyze(pcap)
        fl = [f for f in r['flows'] if not f['noise']]
        check('真实 cap.pcap: 发现 CCTV1 流',
              any(f['group'] == '233.50.201.118' and f['port'] == 5140 for f in fl),
              'flows=%d unique=%d' % (len(fl), r['stats']['unique']))
        check('真实 cap.pcap: 机顶盒信息提取', bool(r['stb'] and r['stb'].get('account')))


def test_naspush():
    tmp = tempfile.mkdtemp(prefix='iptv_nas_')
    src = os.path.join(tmp, 'iptv.m3u')
    with open(src, 'w', encoding='utf-8') as f:
        f.write('#EXTM3U\n')
    dest_dir = os.path.join(tmp, 'nas')
    dest = naspush.push_file(src, 'smb', dest_dir)
    check('NAS推送: SMB/本地目录', os.path.exists(dest) and os.path.basename(dest) == 'iptv.m3u')
    res = naspush.push_many([src, src + '.nope'], 'local', dest_dir)
    check('NAS推送: 批量跳过缺失', len(res) == 1)
    try:
        naspush.push_file(src, 'smb', '')
        check('NAS推送: 空路径报错', False)
    except ValueError:
        check('NAS推送: 空路径报错', True)


# ---------- 跨平台层 ----------
def test_platform():
    check('平台: 系统识别', netutil.IS_WIN or netutil.IS_MAC or netutil.IS_LINUX, sys.platform)
    ifaces = netutil.list_interfaces()
    check('平台: 网卡枚举', isinstance(ifaces, list), 'n=%d' % len(ifaces))
    keys = {'name', 'desc', 'mac', 'ipv4', 'gateway', 'dhcp', 'kind'}
    check('平台: 网卡结构一致', all(keys <= set(i) for i in ifaces))
    fake = [{'name': 'w', 'kind': 'wifi', 'ipv4': '192.168.1.5', 'gateway': '192.168.1.1'},
            {'name': 'e', 'kind': 'wired', 'ipv4': '169.254.1.2', 'gateway': ''},
            {'name': 'e2', 'kind': 'wired', 'ipv4': '192.168.1.6', 'gateway': '192.168.1.1'}]
    check('平台: 组播口优先有线带网关', netutil.pick_multicast_iface(fake) == '192.168.1.6')
    check('平台: udpxy 地址优先网关口', netutil.lan_ip_for_udpxy(fake) == '192.168.1.5')
    eng = capture.get_engine(tempfile.mkdtemp(prefix='iptv_eng_'))
    check('平台: 抓包引擎工厂', eng.name in ('pktmon', 'tcpdump')
          and all(hasattr(eng, m) for m in ('available', 'start', 'stop', 'convert', 'cleanup')))
    backend, path = netutil.capture_backend()
    check('平台: 后端探测一致', (backend is None) == (path is None), str(backend))


def sll_wrap(eth_pkt, linktype):
    """以太网帧 → LINUX_SLL(113)/SLL2(276) 帧（tcpdump -i any 产物）。"""
    ip_pkt = eth_pkt[14:]
    if linktype == 113:
        return struct.pack('!HHH8sH', 0, 1, 6, b'\x00' * 8, 0x0800) + ip_pkt
    return struct.pack('!HHIHBB8s', 0x0800, 0, 2, 1, 0, 6, b'\x00' * 8) + ip_pkt


def make_pcap_sll(path, ts_data, linktype):
    pkts = [sll_wrap(igmp_report('233.50.201.118'), linktype)]
    chunk = ts_data[:1316]
    for i in range(10):
        pkts.append(sll_wrap(eth_ip_udp('10.20.30.40', '233.50.201.118', 5000, 5140,
                                        chunk, ip_id=100 + i), linktype))
    with open(path, 'wb') as f:
        f.write(struct.pack('<IHHiIII', 0xa1b2c3d4, 2, 4, 0, 0, 65535, linktype))
        for i, p in enumerate(pkts):
            f.write(struct.pack('<IIII', 1700000000 + i, i * 1000, len(p), len(p)))
            f.write(p)


def test_capture_sll():
    ts_data = make_test_ts()
    tmp = tempfile.mkdtemp(prefix='iptv_selftest_')
    for lt, kind in ((113, 'SLL'), (276, 'SLL2')):
        p = os.path.join(tmp, 't_%s.pcap' % kind)
        make_pcap_sll(p, ts_data, lt)
        r = capture.analyze(p)
        flows = [f for f in r['flows'] if not f['noise']]
        check('抓包: %s 组播流' % kind,
              len(flows) == 1 and flows[0]['group'] == '233.50.201.118' and flows[0]['pkts'] == 10)
        check('抓包: %s IGMP 加组' % kind, r['joins'].get('233.50.201.118') == 1)


def main():
    test_ts()
    test_capture()
    test_capture_sll()
    test_m3u()
    test_wizard()
    test_db()
    test_naspush()
    test_platform()
    if '--real' in sys.argv:
        test_real()
    failed = [n for n, ok in RESULTS if not ok]
    print('\n%d/%d PASS' % (len(RESULTS) - len(failed), len(RESULTS)))
    if failed:
        print('FAILED:', failed)
        sys.exit(1)
    print('ALL PASS')


if __name__ == '__main__':
    main()
