# -*- coding: utf-8 -*-
"""参考库在线更新（用户主动触发，不后台联网）：
策略1 国内 GitHub 加速镜像直取 raw 文件（不占 API 配额）
策略2 GitHub API blobs（匿名 60 次/小时，超限自动切换）
策略3 git 稀疏克隆（本机装有 git 时）
更新产物写入程序目录 refdb.json，覆盖内嵌库；也可手动导入该文件离线更新。
"""
import base64
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import channeldb

REPO = 'xisohi/CHINA-IPTV'
BRANCH = 'main'
UA = {'User-Agent': 'wushuang-iptv-tool'}
MIRRORS = [
    'https://ghproxy.net/https://raw.githubusercontent.com/',
    'https://gh-proxy.com/https://raw.githubusercontent.com/',
    'https://ghfast.top/https://raw.githubusercontent.com/',
    'https://raw.githubusercontent.com/',
]
CREATE_NO_WINDOW = 0x08000000


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _default_files():
    files = channeldb.db().get('files')
    if files:
        return list(files)
    out = []
    for py in channeldb.PROV:
        for c in ('telecom', 'unicom', 'mobile'):
            out.append('Multicast/%s/%s.txt' % (py, c))
    return out


def fetch_online(progress_cb=None, stop_event=None):
    """返回 (ok, message)。progress_cb(done, total, text)。"""
    stop_event = stop_event or threading.Event()
    files = _default_files()
    texts = {}
    total = len(files)
    done = 0
    lock = threading.Lock()

    def report(text):
        nonlocal done
        with lock:
            done += 1
            if progress_cb:
                progress_cb(done, total, text)

    # ---- 策略1：加速镜像 ----
    for mirror in MIRRORS:
        if stop_event.is_set():
            return False, '已取消'
        missing = [f for f in files if f not in texts]
        if not missing:
            break
        base = mirror + '%s/%s/%s/' % (REPO, BRANCH, '')
        fails = []

        def dl(path):
            if stop_event.is_set():
                return
            try:
                data = _get(base + path)
                if data and b'#genre#' in data or (data and b',' in data):
                    texts[path] = data.decode('utf-8', 'replace')
                report(path)
            except Exception:
                fails.append(path)
                report(path)
        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(dl, missing))
        if len(texts) >= total * 0.9:
            break
        if len(fails) == len(missing):
            continue  # 该镜像完全不可用，换下一个
    # ---- 策略2：GitHub API ----
    if len(texts) < total * 0.9 and not stop_event.is_set():
        try:
            tree = json.loads(_get('https://api.github.com/repos/%s/git/trees/%s?recursive=1'
                                   % (REPO, BRANCH), timeout=30))
            sha_map = {e['path']: e['sha'] for e in tree.get('tree', [])
                       if e['type'] == 'blob' and e['path'] in files and e['path'] not in texts}
            for path, sha in sha_map.items():
                if stop_event.is_set():
                    break
                try:
                    blob = json.loads(_get('https://api.github.com/repos/%s/git/blobs/%s'
                                           % (REPO, sha), timeout=30))
                    texts[path] = base64.b64decode(blob['content']).decode('utf-8', 'replace')
                except Exception:
                    pass
                report(path)
        except Exception:
            pass
    # ---- 策略3：git 稀疏克隆 ----
    if len(texts) < total * 0.5 and not stop_event.is_set():
        git = shutil.which('git')
        if git:
            tmp = tempfile.mkdtemp(prefix='iptv_refdb_')
            try:
                env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
                subprocess.run([git, 'clone', '--depth', '1', '--filter=blob:none', '--sparse',
                                'https://github.com/%s.git' % REPO, tmp],
                               capture_output=True, timeout=300, env=env,
                               creationflags=CREATE_NO_WINDOW)
                subprocess.run([git, 'sparse-checkout', 'set', 'Multicast'],
                               cwd=tmp, capture_output=True, timeout=300, env=env,
                               creationflags=CREATE_NO_WINDOW)
                for path in files:
                    if path in texts:
                        continue
                    fp = os.path.join(tmp, path.replace('/', os.sep))
                    if os.path.exists(fp):
                        with open(fp, encoding='utf-8', errors='replace') as f:
                            texts[path] = f.read()
                        report(path)
            except Exception:
                pass
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

    if stop_event.is_set():
        return False, '已取消'
    if not texts:
        return False, '所有更新源均不可达。可稍后重试，或从 QQ 群下载 refdb.json 后放到程序目录。'
    d = channeldb.build_db(texts)
    n = sum(len(r['channels']) for r in d['regions'])
    if n == 0:
        return False, '下载成功但未解析出频道，数据源可能已变化。'
    channeldb.save_external(d)
    channeldb.reload_db()
    info = channeldb.db_info()
    return True, '更新完成：%d 省 %d 列表 %d 频道（%s）。已写入程序目录 refdb.json。' % (
        info['provinces'], info['regions'], info['channels'], info['updated'])


def import_file(path):
    """离线导入参考库文件（refdb.json / refdb.json.gz）。"""
    d = channeldb._load_file(path)
    if d.get('format') != 'wushuang-iptv-refdb' or not d.get('regions'):
        raise ValueError('不是有效的无双参考库文件（format=wushuang-iptv-refdb）')
    channeldb.save_external(d)
    channeldb.reload_db()
    info = channeldb.db_info()
    return '导入完成：%d 省 %d 列表 %d 频道。' % (info['provinces'], info['regions'], info['channels'])
