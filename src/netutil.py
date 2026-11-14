# -*- coding: utf-8 -*-
"""网络工具：管理员检测、网卡枚举（ipconfig 解析，中英文系统均可）、pktmon 可用性。"""
import ctypes
import os
import re
import shutil
import subprocess

CREATE_NO_WINDOW = 0x08000000


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def pktmon_path():
    p = shutil.which('pktmon')
    if p:
        return p
    cand = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'pktmon.exe')
    return cand if os.path.exists(cand) else None


def run_hidden(args, timeout=120):
    """运行子进程（无窗口），返回 (returncode, stdout+stderr 文本)。"""
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout,
                           creationflags=CREATE_NO_WINDOW)
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
    """解析 ipconfig /all，返回网卡列表。
    每项: {name, desc, mac, ipv4, gateway, dhcp, kind: 'wired'|'wifi'|'other'}
    """
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
