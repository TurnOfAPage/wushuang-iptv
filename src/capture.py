# -*- coding: utf-8 -*-
"""抓包引擎（跨平台）：Windows 内置 pktmon（无需 Wireshark/Npcap）；
Linux/macOS 用系统 tcpdump（需 root/sudo）。pcap/pcapng 解析 + IGMP/组播分析全平台共用。
经验（实测总结）：
- pktmon etl2pcap 产物实际是 pcapng；
- pktmon 全 NIC/多组件抓包会重复 6~8 份，必须去重；
- tcpdump -i any 产物是 LINUX_SLL/SLL2 链路类型，同样支持；
- 过滤 224.0.0.x / SSDP / mDNS / LLMNR 噪声。
"""
import os
import re
import signal
import struct
import subprocess
import time

import netutil
from netutil import pktmon_path, run_hidden

NOISE_GROUPS = {'239.255.255.250'}
NOISE_PORTS = {1900, 5353, 5355, 3702}


def is_noise(group, port):
    if group.startswith('224.0.0.'):
        return True
    if group in NOISE_GROUPS:
        return True
    if port in NOISE_PORTS:
        return True
    return False


class Pktmon:
    """pktmon 生命周期封装（Windows）。调用方需管理员权限。"""
    name = 'pktmon'

    def __init__(self, workdir):
        self.workdir = workdir
        self.etl = os.path.join(workdir, 'iptv_cap.etl')
        self.pcap = os.path.join(workdir, 'iptv_cap.pcap')
        self.exe = pktmon_path()
        self.running = False
        self.started_at = None

    def available(self):
        return self.exe is not None

    def start(self):
        if not self.exe:
            return False, '未找到 pktmon（需要 Windows 10 1809+ / Windows 11）'
        os.makedirs(self.workdir, exist_ok=True)
        run_hidden([self.exe, 'stop'], timeout=30)  # 清理可能残留的会话
        for f in (self.etl, self.pcap):
            try:
                if os.path.exists(f):
                    os.remove(f)
            except OSError:
                pass
        code, out = run_hidden([self.exe, 'start', '--capture', '--pkt-size', '0',
                                '--file-name', self.etl], timeout=60)
        if code != 0:
            return False, 'pktmon start 失败: %s' % out.strip()[:400]
        self.running = True
        self.started_at = time.time()
        return True, '抓包已开始'

    def stop(self):
        if not self.exe:
            return False, '未找到 pktmon'
        code, out = run_hidden([self.exe, 'stop'], timeout=60)
        self.running = False
        if code != 0:
            return False, 'pktmon stop 失败: %s' % out.strip()[:400]
        return True, out.strip()[:400]

    def convert(self):
        if not os.path.exists(self.etl):
            return False, '未找到抓包文件 %s' % self.etl
        code, out = run_hidden([self.exe, 'etl2pcap', self.etl, '-o', self.pcap], timeout=600)
        if code != 0 or not os.path.exists(self.pcap):
            return False, 'etl2pcap 转换失败: %s' % out.strip()[:400]
        return True, self.pcap

    def cleanup(self, keep_pcap=False):
        try:
            if os.path.exists(self.etl):
                os.remove(self.etl)
            if not keep_pcap and os.path.exists(self.pcap):
                os.remove(self.pcap)
        except OSError:
            pass


class Tcpdump:
    """tcpdump 生命周期封装（Linux/macOS），接口与 Pktmon 一致。调用方需 root。
    Linux 缺省 -i any（抓全部网卡，SLL 链路类型）；macOS 无 any，缺省选建议的有线口。
    iface 可传设备名（eth0/en0）或网卡 IP（自动解析为设备名）。"""
    name = 'tcpdump'

    def __init__(self, workdir, iface=None):
        self.workdir = workdir
        self.pcap = os.path.join(workdir, 'iptv_cap.pcap')
        self.exe = netutil.tcpdump_path()
        self.iface = iface
        self.proc = None
        self.running = False
        self.started_at = None

    def available(self):
        return self.exe is not None

    def _resolve_iface(self):
        if self.iface:
            # 允许传 IP：解析成设备名
            for i in netutil.list_interfaces():
                if self.iface in (i['name'], i['ipv4']):
                    return i['name']
            return self.iface  # 信任用户给的设备名
        if netutil.IS_LINUX:
            return 'any'
        ip = netutil.pick_multicast_iface(netutil.list_interfaces())
        for i in netutil.list_interfaces():
            if i['ipv4'] == ip:
                return i['name']
        return ''

    def start(self):
        if not self.exe:
            return False, '未找到 tcpdump（Linux: sudo apt install tcpdump；macOS 系统自带）'
        if not netutil.is_admin():
            return False, '抓包需要 root 权限，请用 sudo 运行'
        iface = self._resolve_iface()
        if not iface:
            return False, '未找到可用网卡，请用 --iface 指定抓包网卡（设备名或 IP）'
        os.makedirs(self.workdir, exist_ok=True)
        try:
            if os.path.exists(self.pcap):
                os.remove(self.pcap)
        except OSError:
            pass
        try:
            self.proc = subprocess.Popen(
                [self.exe, '-i', iface, '-s', '0', '-U', '-w', self.pcap],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        except Exception as e:
            return False, 'tcpdump 启动失败: %s' % e
        time.sleep(0.4)
        if self.proc.poll() is not None:
            err = b''
            try:
                err = self.proc.stderr.read() or b''
            except Exception:
                pass
            self.proc = None
            return False, 'tcpdump 启动失败: %s' % err.decode('utf-8', 'replace').strip()[:400]
        self.running = True
        self.started_at = time.time()
        return True, '抓包已开始（tcpdump -i %s）' % iface

    def stop(self):
        if not self.proc:
            self.running = False
            return False, 'tcpdump 未在运行'
        try:
            self.proc.send_signal(signal.SIGINT)  # 让 tcpdump 正常刷盘并输出统计
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        except Exception:
            pass
        stats = ''
        try:
            stats = (self.proc.stderr.read() or b'').decode('utf-8', 'replace').strip()
        except Exception:
            pass
        self.proc = None
        self.running = False
        return True, stats[:400] or '抓包已停止'

    def convert(self):
        # tcpdump 直接写 pcap，无需转换；保持与 Pktmon 相同的接口
        if not os.path.exists(self.pcap):
            return False, '未找到抓包文件 %s' % self.pcap
        return True, self.pcap

    def cleanup(self, keep_pcap=False):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.proc = None
        try:
            if not keep_pcap and os.path.exists(self.pcap):
                os.remove(self.pcap)
        except OSError:
            pass


def get_engine(workdir, iface=None):
    """平台工厂：Windows→Pktmon；Linux/macOS→Tcpdump。GUI 与 CLI 共用。"""
    if netutil.IS_WIN:
        return Pktmon(workdir)
    return Tcpdump(workdir, iface=iface)


def iter_pcap(path):
    """yield (ts, linktype, bytes)，支持 classic pcap 与 pcapng（pktmon 产物）。"""
    with open(path, 'rb') as f:
        magic = f.read(4)
        if magic in (b'\xd4\xc3\xb2\xa1', b'\xa1\xb2\xc3\xd4', b'\x4d\x3c\xb2\xa1', b'\xa1\xb2\x3c\x4d'):
            endian = '<' if magic in (b'\xd4\xc3\xb2\xa1', b'\x4d\x3c\xb2\xa1') else '>'
            nano = magic in (b'\x4d\x3c\xb2\xa1', b'\xa1\xb2\x3c\x4d')
            hdr = f.read(20)
            linktype = struct.unpack(endian + 'I', hdr[16:20])[0]
            while True:
                h = f.read(16)
                if len(h) < 16:
                    return
                ts_s, ts_frac, incl, orig = struct.unpack(endian + 'IIII', h)
                pkt = f.read(incl)
                if len(pkt) < incl:
                    return
                yield ts_s + ts_frac / (1e9 if nano else 1e6), linktype, pkt
        elif magic == b'\x0a\x0d\x0d\x0a':
            f.seek(0)
            endian = '<'
            ifaces = []
            while True:
                h = f.read(8)
                if len(h) < 8:
                    return
                btype, blen = struct.unpack(endian + 'II', h)
                if btype == 0x0A0D0D0A:
                    body = f.read(blen - 12)
                    f.read(4)
                    if len(body) >= 4:
                        bom = struct.unpack('<I', body[0:4])[0]
                        endian = '<' if bom == 0x1A2B3C4D else '>'
                    continue
                if blen < 12 or blen > 100 * 1024 * 1024:
                    return
                body = f.read(blen - 12)
                f.read(4)
                if btype == 0x00000001:  # IDB
                    lt, _res, snap = struct.unpack(endian + 'HHI', body[0:8])
                    resol = 1e-6
                    r = 8
                    while r + 4 <= len(body):
                        code, ln = struct.unpack(endian + 'HH', body[r:r + 4])
                        val = body[r + 4:r + 4 + ln]
                        if code == 9 and ln >= 1:
                            b0 = val[0]
                            resol = (2.0 ** -(b0 & 0x7f)) if (b0 & 0x80) else (10.0 ** -b0)
                        if code == 0:
                            break
                        r += 4 + ((ln + 3) // 4) * 4
                    ifaces.append((lt, resol))
                elif btype == 0x00000006:  # EPB
                    iid, th, tl, caplen, origlen = struct.unpack(endian + 'IIIII', body[0:20])
                    pkt = body[20:20 + caplen]
                    lt, resol = ifaces[iid] if iid < len(ifaces) else (1, 1e-6)
                    ts = ((th << 32) | tl) * resol
                    yield ts, lt, pkt
        else:
            raise ValueError('无法识别的抓包文件格式: %r' % magic)


def _ip4(b):
    return '%d.%d.%d.%d' % (b[0], b[1], b[2], b[3])


def analyze(path, progress_cb=None, dedup=True):
    """分析抓包文件，返回 dict：
    flows: [{group, port, pkts, bytes, srcs, first, last, proto}]
    joins: {group: 次数}, leaves: {group: 次数}
    stb: {mac, ip, account, hostname} 或 None
    stats: {packets, unique, duration}
    """
    flows = {}
    joins = {}
    leaves = {}
    stb = None
    seen = set()
    n = 0
    uniq = 0
    t_first = None
    t_last = None
    for ts, linktype, pkt in iter_pcap(path):
        n += 1
        if progress_cb and n % 20000 == 0:
            progress_cb(n)
        if t_first is None:
            t_first = ts
        t_last = ts
        if linktype == 1:
            if len(pkt) < 14:
                continue
            eth_type = struct.unpack('!H', pkt[12:14])[0]
            p = 14
            while eth_type in (0x8100, 0x88a8) and len(pkt) >= p + 4:
                eth_type = struct.unpack('!H', pkt[p + 2:p + 4])[0]
                p += 4
            if eth_type != 0x0800:
                continue
        elif linktype == 113:  # LINUX_SLL（tcpdump -i any，旧版）
            if len(pkt) < 16:
                continue
            if struct.unpack('!H', pkt[14:16])[0] != 0x0800:
                continue
            p = 16
        elif linktype == 276:  # LINUX_SLL2（tcpdump -i any，新版）
            if len(pkt) < 20:
                continue
            if struct.unpack('!H', pkt[0:2])[0] != 0x0800:
                continue
            p = 20
        elif linktype == 101:  # raw IP
            p = 0
        else:
            continue
        if len(pkt) < p + 20:
            continue
        ihl = (pkt[p] & 0x0f) * 4
        if ihl < 20 or len(pkt) < p + ihl:
            continue
        proto = pkt[p + 9]
        total_len = struct.unpack('!H', pkt[p + 2:p + 4])[0]
        ip_id = struct.unpack('!H', pkt[p + 4:p + 6])[0]
        src_ip = _ip4(pkt[p + 12:p + 16])
        dst_ip = _ip4(pkt[p + 16:p + 20])
        if dedup:
            key = (src_ip, dst_ip, ip_id, total_len, proto)
            if key in seen:
                continue
            if len(seen) > 1_500_000:
                seen.clear()
            seen.add(key)
        uniq += 1
        q = p + ihl
        if proto == 2:  # IGMP
            if len(pkt) < q + 8:
                continue
            t = pkt[q]
            if t == 0x22:  # IGMPv3 report
                if len(pkt) < q + 8:
                    continue
                nrec = struct.unpack('!H', pkt[q + 6:q + 8])[0]
                r = q + 8
                for _ in range(nrec):
                    if len(pkt) < r + 8:
                        break
                    rt, aux, ns = pkt[r], pkt[r + 1], struct.unpack('!H', pkt[r + 2:r + 4])[0]
                    g = _ip4(pkt[r + 4:r + 8])
                    if not g.startswith('224.0.0.') and rt in (1, 2, 3, 4):
                        joins[g] = joins.get(g, 0) + 1
                    r += 8 + ns * 4 + aux * 4
            elif t in (0x12, 0x16):  # v1/v2 report
                g = _ip4(pkt[q + 4:q + 8])
                if not g.startswith('224.0.0.'):
                    joins[g] = joins.get(g, 0) + 1
            elif t == 0x17:  # leave
                g = _ip4(pkt[q + 4:q + 8])
                leaves[g] = leaves.get(g, 0) + 1
        elif proto == 17:  # UDP
            if len(pkt) < q + 8:
                continue
            sport, dport, ulen = struct.unpack('!HHH', pkt[q:q + 6])
            payload = pkt[q + 8:q + ulen] if 8 <= ulen <= len(pkt) - q else pkt[q + 8:]
            if sport in (67, 68) or dport in (67, 68):
                if len(payload) >= 240 and payload[236:240] == b'\x63\x82\x53\x63':
                    stb = _parse_dhcp_stb(payload, stb)
                continue
            first = int(dst_ip.split('.')[0])
            if 224 <= first <= 239:
                key = (dst_ip, dport)
                e = flows.get(key)
                if e is None:
                    proto_hint = 'TS'
                    if payload:
                        if payload[0] == 0x47:
                            proto_hint = 'TS'
                        elif (payload[0] & 0xC0) == 0x80:
                            proto_hint = 'RTP'
                        else:
                            proto_hint = '?'
                    e = flows[key] = {'group': dst_ip, 'port': dport, 'pkts': 0,
                                      'bytes': 0, 'srcs': set(), 'first': ts,
                                      'last': ts, 'proto': proto_hint}
                e['pkts'] += 1
                e['bytes'] += len(pkt)
                e['srcs'].add(src_ip)
                e['last'] = ts
    fl = sorted(flows.values(), key=lambda e: -e['bytes'])
    for e in fl:
        e['srcs'] = sorted(e['srcs'])[:4]
        e['noise'] = is_noise(e['group'], e['port'])
    return {
        'flows': fl,
        'joins': joins,
        'leaves': leaves,
        'stb': stb,
        'stats': {'packets': n, 'unique': uniq,
                  'duration': (t_last - t_first) if (t_first and t_last) else 0},
    }


def _parse_dhcp_stb(payload, stb):
    """从 DHCP 报文提取机顶盒鉴权信息（option60 账号 / option12 STBID）。"""
    try:
        opts = {}
        r = 240
        while r < len(payload):
            code = payload[r]
            if code == 255:
                break
            if code == 0:
                r += 1
                continue
            if r + 1 >= len(payload):
                break
            ln = payload[r + 1]
            opts[code] = payload[r + 2:r + 2 + ln]
            r += 2 + ln
        o60 = opts.get(60, b'')
        m = re.search(rb'(tv\d+@itv)', o60)
        hostname = opts.get(12, b'').decode('utf-8', 'replace').strip('\x00')
        yiaddr = _ip4(payload[16:20])
        chaddr = payload[28:28 + payload[2]].hex(':')
        if m or (hostname and hostname.startswith('A5')):
            info = dict(stb or {})
            if m:
                info['account'] = m.group(1).decode()
            if hostname:
                info['hostname'] = hostname
            if yiaddr != '0.0.0.0':
                info['ip'] = yiaddr
            info['mac'] = chaddr
            return info
    except Exception:
        pass
    return stb
