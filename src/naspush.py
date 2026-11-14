# -*- coding: utf-8 -*-
"""一键推送播放列表到 NAS（纯标准库，保持单文件绿色）。
支持：SMB 共享/映射盘（UNC 或盘符路径）、WebDAV（群晖/威联通等开启 WebDAV 服务）。
"""
import base64
import os
import shutil
import subprocess
import urllib.request

CREATE_NO_WINDOW = 0x08000000


def _smb_connect(target, user, password):
    """若提供凭据，先 net use 建立到共享根的连接（已连接则忽略）。"""
    if not user:
        return
    parts = target.replace('/', '\\').split('\\')
    # \\server\share\... -> \\server\share
    root = '\\\\' + parts[2] + '\\' + parts[3] if len(parts) >= 4 and not parts[0] else target
    try:
        subprocess.run(['net', 'use', root, '/user:%s' % user, password, '/persistent:no'],
                       capture_output=True, timeout=20, creationflags=CREATE_NO_WINDOW)
    except Exception:
        pass


def push_file(local_path, method, target, user='', password='', remote_name=None):
    """把本地文件推送到 NAS，返回目标位置描述。失败抛异常。"""
    name = remote_name or os.path.basename(local_path)
    if method in ('smb', 'local'):
        if not target:
            raise ValueError('请填写 NAS 共享路径（如 \\\\192.168.1.84\\共享\\iptv 或映射盘 Z:\\iptv）')
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
