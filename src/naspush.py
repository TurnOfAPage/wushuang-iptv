# -*- coding: utf-8 -*-
"""一键推送播放列表到 NAS（纯标准库，保持单文件绿色）。
支持：SMB 共享/映射盘（Windows: UNC 或盘符路径；Linux/macOS: 已挂载目录或 smb:// URL）、
WebDAV（群晖/威联通等开启 WebDAV 服务）。
"""
import base64
import os
import shutil
import subprocess
import urllib.request

import netutil

CREATE_NO_WINDOW = netutil.CREATE_NO_WINDOW


def _smb_connect(target, user, password):
    """Windows：若提供凭据，先 net use 建立到共享根的连接（已连接则忽略）。POSIX 无需。"""
    if not user or not netutil.IS_WIN:
        return
    parts = target.replace('/', '\\').split('\\')
    # \\server\share\... -> \\server\share
    root = '\\\\' + parts[2] + '\\' + parts[3] if len(parts) >= 4 and not parts[0] else target
    try:
        subprocess.run(['net', 'use', root, '/user:%s' % user, password, '/persistent:no'],
                       capture_output=True, timeout=20, creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass


def _smbclient_run(base_args, cmds):
    r = subprocess.run(base_args + ['-c', '; '.join(cmds)],
                       capture_output=True, timeout=60)
    out = ((r.stdout or b'') + (r.stderr or b'')).decode('utf-8', 'replace')
    return r.returncode, out


def _posix_smb_put(local_path, target, user, password, name):
    """Linux/macOS：smb://server/share[/dir] 用系统 smbclient 推送（无需挂载）。"""
    exe = shutil.which('smbclient')
    if not exe:
        raise ValueError('smb:// 目标需要 smbclient（sudo apt install smbclient / brew install samba）；'
                         '或先把共享挂载到本地目录，再用普通路径推送')
    parts = [p for p in target[len('smb://'):].split('/') if p]
    if len(parts) < 2:
        raise ValueError('SMB 地址格式应为 smb://服务器/共享名[/目录]：%s' % target)
    server, share, subdir = parts[0], parts[1], '/'.join(parts[2:])
    base = [exe, '//%s/%s' % (server, share)]
    base += ['-U', '%s%%%s' % (user, password)] if user else ['-N']
    if subdir:
        rc, out = _smbclient_run(base, ['cd "%s"' % subdir])
        if rc != 0:
            # 逐级建目录（已存在的 mkdir 报错忽略），再进入
            prefix = ''
            for d in subdir.split('/'):
                prefix = (prefix + '/' + d).lstrip('/')
                _smbclient_run(base, ['mkdir "%s"' % prefix, 'cd "%s"' % prefix])
            rc, out = _smbclient_run(base, ['cd "%s"' % subdir])
            if rc != 0:
                raise ValueError('smbclient 进入目录失败: %s' % out.strip()[:300])
    rc, out = _smbclient_run(base, ['put "%s" "%s"' % (local_path, name)])
    if rc != 0 or 'NT_STATUS_' in out:
        raise ValueError('smbclient 推送失败: %s' % out.strip()[:300])
    return 'smb://%s/%s/%s%s' % (server, share, subdir + '/' if subdir else '', name)


def push_file(local_path, method, target, user='', password='', remote_name=None):
    """把本地文件推送到 NAS，返回目标位置描述。失败抛异常。"""
    name = remote_name or os.path.basename(local_path)
    if method in ('smb', 'local'):
        if not target:
            raise ValueError('请填写 NAS 共享路径（Windows: \\\\192.168.1.84\\共享\\iptv 或映射盘 Z:\\iptv；'
                             'Linux/macOS: 已挂载目录 /mnt/nas、/Volumes/共享 或 smb://192.168.1.84/共享/iptv）')
        if target.lower().startswith('smb://'):
            if netutil.IS_WIN:
                raise ValueError('Windows 请用 UNC 路径（\\\\服务器\\共享）而不是 smb:// URL')
            return _posix_smb_put(local_path, target, user, password, name)
        if method == 'smb' and target.startswith('\\'):
            _smb_connect(target, user, password)
        dest = os.path.join(target, name)
        d = os.path.dirname(dest)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        shutil.copyfile(local_path, dest)
        return dest
    if method == 'webdav':
        if not target:
            raise ValueError('请填写 WebDAV 地址（如 http://192.168.1.84:5005/iptv）')
        url = target.rstrip('/') + '/' + name
        with open(local_path, 'rb') as f:
            data = f.read()
        req = urllib.request.Request(url, data=data, method='PUT')
        req.add_header('Content-Type', 'application/octet-stream')
        if user:
            token = base64.b64encode(('%s:%s' % (user, password)).encode()).decode()
            req.add_header('Authorization', 'Basic ' + token)
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        return url
    raise ValueError('未知推送方式: %s' % method)


def push_many(paths, method, target, user='', password='', remote_dir_name=None):
    """推送多个文件，返回 [(path, dest_or_error)]。"""
    out = []
    for p in paths:
        if not p or not os.path.exists(p):
            continue
        try:
            dest = push_file(p, method, target, user, password)
            out.append((p, dest))
        except Exception as e:
            out.append((p, '失败: %s' % e))
    return out
