# -*- coding: utf-8 -*-
"""网络工具（跨平台）：管理员/root 检测、网卡枚举、抓包后端探测。
Windows: ipconfig /all 解析（中英文系统均可）+ pktmon；
Linux:   ip -j addr（缺 ip 时回退 ifconfig）+ /sys/class/net 无线识别 + tcpdump；
macOS:   ifconfig + networksetup（Wi-Fi 口识别）+ route/ipconfig（网关/DHCP）+ tcpdump。
各平台 list_interfaces() 返回同一结构，供 pick_multicast_iface / GUI / CLI 共用。
"""
import ctypes
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys

IS_WIN = sys.platform == 'win32'
IS_MAC = sys.platform == 'darwin'
IS_LINUX = sys.platform.startswith('linux')

CREATE_NO_WINDOW = 0x08000000 if IS_WIN else 0


def is_admin():
    """Windows=管理员；Linux/macOS=root（抓包需要）。"""
    if IS_WIN:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


def pktmon_path():
    if not IS_WIN:
        return None
    p = shutil.which('pktmon')
    if p:
        return p
    cand = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'pktmon.exe')
    return cand if os.path.exists(cand) else None


def tcpdump_path():
    """Linux/macOS 抓包后端。macOS 系统自带；Linux 多数发行版自带或 apt/yum 安装。"""
    p = shutil.which('tcpdump')
    if p:
        return p
    for cand in ('/usr/sbin/tcpdump', '/usr/bin/tcpdump', '/sbin/tcpdump',
                 '/usr/local/bin/tcpdump', '/opt/homebrew/bin/tcpdump'):
        if os.path.exists(cand):
            return cand
    return None


def capture_backend():
    """返回 (名称, 路径)：Windows→pktmon，Linux/macOS→tcpdump；不可用→(None, None)。"""
    if IS_WIN:
        p = pktmon_path()
        return ('pktmon', p) if p else (None, None)
    p = tcpdump_path()
    return ('tcpdump', p) if p else (None, None)


def run_hidden(args, timeout=120, env=None, cwd=None):
    """运行子进程（Windows 无窗口），返回 (returncode, stdout+stderr 文本)。"""
    try:
        kw = {'env': env, 'cwd': cwd}
        if IS_WIN:
            kw['creationflags'] = CREATE_NO_WINDOW
        r = subprocess.run(args, capture_output=True, timeout=timeout, **kw)
        out = (r.stdout or b'') + (r.stderr or b'')
        try:
            txt = out.decode('utf-8')
        except UnicodeDecodeError:
            txt = out.decode('gbk', 'replace')
        return r.returncode, txt
    except subprocess.TimeoutExpired:
        return -1, '命令超时: %s' % ' '.join(args)
    except Exception as e:
        return -1, str(e)


_SKIP_WORDS = ('隧道', 'Tunnel', 'isatap', 'Teredo', 'Loopback', 'Bluetooth',
               '蓝牙', '虚拟', 'Virtual', 'VMware', 'vEthernet', 'Hyper-V',
               'WSL', 'Pseudo', '6to4', 'IP-HTTPS')
_WIFI_WORDS = ('WLAN', 'Wireless', '无线', 'Wi-Fi', 'WiFi', '802.11')


def list_interfaces():
    """返回网卡列表。每项: {name, desc, mac, ipv4, gateway, dhcp, kind: 'wired'|'wifi'|'other'}
    Windows 的 name 是连接名（如「以太网」）；Linux/macOS 的 name 是设备名（eth0/en0）。"""
    if IS_WIN:
        return _win_interfaces()
    if IS_MAC:
        return _mac_interfaces()
    return _linux_interfaces()


# ---------------- Windows（原有实现，保持不变） ----------------

def _win_interfaces():
    code, out = run_hidden(['ipconfig', '/all'], timeout=30)
    if code != 0:
        return []
    ifaces = []
    cur = None
    for line in out.splitlines():
        if line and not line[0].isspace() and line.rstrip().endswith(':'):
            header = line.rstrip()[:-1]
            if any(w.lower() in header.lower() for w in _SKIP_WORDS):
                cur = None
                continue
            # 形如 "以太网适配器 以太网" / "Ethernet adapter Ethernet" / "无线局域网适配器 WLAN"
            name = re.sub(r'^(以太网适配器|无线局域网适配器|Ethernet adapter|Wireless LAN adapter|'
                          r'未知适配器|Unknown adapter)\s*', '', header).strip()
            kind = 'wifi' if any(w.lower() in header.lower() for w in _WIFI_WORDS) else 'wired'
            cur = {'name': name or header, 'desc': '', 'mac': '', 'ipv4': '',
                   'gateway': '', 'dhcp': False, 'kind': kind}
            ifaces.append(cur)
            continue
        if cur is None:
            continue
        m = re.search(r'(?:描述|Description)[^\n:]*:\s*(.+)', line)
        if m:
            cur['desc'] = m.group(1).strip()
            if any(w.lower() in cur['desc'].lower() for w in _WIFI_WORDS):
                cur['kind'] = 'wifi'
            continue
        m = re.search(r'(?:物理地址|Physical Address)[^\n:]*:\s*([0-9A-Fa-f\-]+)', line)
        if m:
            cur['mac'] = m.group(1).replace('-', ':').upper()
            continue
        m = re.search(r'IPv4[^\n:]*:\s*([0-9.]+)', line)
        if m and not cur['ipv4']:
            cur['ipv4'] = m.group(1)
            continue
        m = re.search(r'(?:默认网关|Default Gateway)[^\n:]*:\s*([0-9A-Fa-f:.%]+)', line)
        if m and not cur['gateway']:
            cur['gateway'] = m.group(1)
            continue
        m = re.search(r'(?:DHCP 已启用|DHCP Enabled)[^\n:]*:\s*(是|Yes)', line)
        if m:
            cur['dhcp'] = True
    return [i for i in ifaces if not i['ipv4'].startswith('127.')]


# ---------------- Linux ----------------

# 虚拟/隧道口前缀（与 Windows 版跳过虚拟网卡的策略一致；VLAN 子接口如 eth0.100 保留）
_LINUX_SKIP_PREFIX = ('docker', 'veth', 'br-', 'virbr', 'tun', 'tap', 'vmnet',
                      'vboxnet', 'flannel', 'cni', 'weave', 'vxlan', 'dummy',
                      'ifb', 'sit', 'ip6tnl', 'gre', 'gretap', 'erspan',
                      'ip_vti', 'ip6_vti', 'wg', 'zt', 'tailscale', 'utun',
                      'ovs-system', 'genev_sys', 'bonding_masters')


def _linux_is_wifi(name):
    base = '/sys/class/net/%s' % name
    return os.path.isdir(base + '/wireless') or os.path.islink(base + '/phy80211')


def _linux_default_route():
    """返回 (dev, gateway)。优先 ip -j route，回退 /proc/net/route（纯文件，无依赖）。"""
    code, out = run_hidden(['ip', '-j', 'route', 'show', 'default'], timeout=15)
    if code == 0:
        try:
            for r in json.loads(out):
                if r.get('gateway') and r.get('dev'):
                    return r['dev'], r['gateway']
        except (ValueError, TypeError):
            pass
    try:
        with open('/proc/net/route', encoding='ascii') as f:
            for line in f.readlines()[1:]:
                p = line.split()
                if len(p) >= 4 and p[1] == '00000000' and p[2] != '00000000':
                    gw = socket.inet_ntoa(struct.pack('<I', int(p[2], 16)))
                    return p[0], gw
    except (OSError, ValueError):
        pass
    return '', ''


def _linux_interfaces():
    code, out = run_hidden(['ip', '-j', 'addr', 'show'], timeout=15)
    if code == 0:
        try:
            data = json.loads(out)
        except ValueError:
            data = []
        gw_dev, gw = _linux_default_route()
        ifaces = []
        for link in data:
            name = link.get('ifname', '')
            if (not name or name == 'lo' or name.startswith(_LINUX_SKIP_PREFIX)
                    or link.get('link_type', 'ether') != 'ether'):
                continue
            ipv4 = ''
            for a in link.get('addr_info', []):
                if a.get('family') == 'inet' and a.get('local'):
                    ipv4 = a['local']
                    break
            if not ipv4 or ipv4.startswith('127.'):
                continue
            ifaces.append({
                'name': name, 'desc': link.get('link_type', ''),
                'mac': (link.get('address') or '').upper(),
                'ipv4': ipv4, 'gateway': gw if name == gw_dev else '',
                'dhcp': False,
                'kind': 'wifi' if _linux_is_wifi(name) else 'wired',
            })
        if ifaces:
            return ifaces
    # 回退：ifconfig（老系统/精简系统无 iproute2 时）
    return _parse_ifconfig(wifi_probe=_linux_is_wifi)


# ---------------- macOS ----------------

def _mac_wifi_devs():
    devs = set()
    code, out = run_hidden(['networksetup', '-listallhardwareports'], timeout=15)
    if code != 0:
        return devs
    port = ''
    for line in out.splitlines():
        m = re.match(r'Hardware Port:\s*(.+)', line)
        if m:
            port = m.group(1).strip().lower()
        m = re.match(r'Device:\s*(\S+)', line)
        if m and ('wi-fi' in port or 'wifi' in port or 'airport' in port):
            devs.add(m.group(1))
    return devs


def _mac_default_route():
    code, out = run_hidden(['route', '-n', 'get', 'default'], timeout=15)
    if code != 0:
        return '', ''
    dev = re.search(r'interface:\s*(\S+)', out)
    gw = re.search(r'gateway:\s*([0-9.]+)', out)
    return (dev.group(1) if dev else ''), (gw.group(1) if gw else '')


def _mac_interfaces():
    wifi = _mac_wifi_devs()
    gw_dev, gw = _mac_default_route()
    ifaces = _parse_ifconfig(wifi_probe=lambda n: n in wifi,
                             skip_prefix=('lo', 'gif', 'stf', 'anpi', 'utun', 'awdl',
                                          'llw', 'bridge', 'ap', 'XHC', 'vmnet', 'vnic'))
    for i in ifaces:
        if i['name'] == gw_dev:
            i['gateway'] = gw
        # ipconfig getpacket 仅在该口由 DHCP 配置时返回 0
        code, _ = run_hidden(['ipconfig', 'getpacket', i['name']], timeout=10)
        i['dhcp'] = code == 0
        i['desc'] = 'Wi-Fi' if i['kind'] == 'wifi' else 'Ethernet'
    return ifaces


# ---------------- 通用 ifconfig 解析（Linux 回退 / macOS 主路径） ----------------

def _parse_ifconfig(wifi_probe=None, skip_prefix=()):
    code, out = run_hidden(['ifconfig', '-a'], timeout=15)
    if code != 0:
        return []
    ifaces = []
    cur = None
    for line in out.splitlines():
        if line and not line[0].isspace():
            name = line.split(':')[0].strip()
            if not name or name.startswith(skip_prefix) or name == 'lo':
                cur = None
                continue
            flags = re.search(r'flags=[0-9a-fA-F]+<([^>]*)>', line)
            up = bool(flags) and 'UP' in flags.group(1).split(',')
            cur = {'name': name, 'desc': '', 'mac': '', 'ipv4': '',
                   'gateway': '', 'dhcp': False,
                   'kind': 'wifi' if (wifi_probe and wifi_probe(name)) else 'wired',
                   '_up': up}
            ifaces.append(cur)
            continue
        if cur is None:
            continue
        m = re.search(r'(?:ether|lladdr)\s+([0-9a-fA-F:]{17})', line)
        if m and not cur['mac']:
            cur['mac'] = m.group(1).upper()
        m = re.search(r'inet\s+([0-9.]+)', line)
        if m and not cur['ipv4']:
            cur['ipv4'] = m.group(1)
    out2 = []
    for i in ifaces:
        up = i.pop('_up', True)
        if not i['ipv4'] or i['ipv4'].startswith('127.') or not up:
            continue
        out2.append(i)
    return out2


# ---------------- 选口策略（跨平台共用，原有逻辑不变） ----------------

def pick_multicast_iface(ifaces):
    """经验：组播验证优先用有线口（IPTV 专网/桥接后的局域网都在有线侧）。"""
    wired = [i for i in ifaces if i['kind'] == 'wired' and i['ipv4']]
    if wired:
        # 有网关的优先（桥接合并后有线口能拿到路由器 DHCP）
        wired.sort(key=lambda i: (0 if i['gateway'] else 1))
        return wired[0]['ipv4']
    other = [i for i in ifaces if i['ipv4'] and i['kind'] != 'wifi']
    if other:
        return other[0]['ipv4']
    wifi = [i for i in ifaces if i['ipv4']]
    return wifi[0]['ipv4'] if wifi else ''


def lan_ip_for_udpxy(ifaces):
    """HTTP 转发版 M3U 里填的地址：家庭局域网侧 IP（有默认网关的口优先）。"""
    cands = [i for i in ifaces if i['ipv4'] and i['gateway']]
    if cands:
        cands.sort(key=lambda i: (0 if i['kind'] == 'wifi' else 1))
        return cands[0]['ipv4']
    cands = [i for i in ifaces if i['ipv4']]
    return cands[0]['ipv4'] if cands else '192.168.1.100'
