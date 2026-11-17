# -*- coding: utf-8 -*-
"""CI 用：拉取社区参考数据并生成 src/refdb.json.gz。
仓库出于许可证考虑不捆绑社区数据（见 README），CI 构建时现拉现建。
策略：git 浅克隆（重试 3 次）→ 失败则镜像逐文件下载兜底（避免 API 配额与网络波动）。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
NAT = os.path.join(HERE, '..', 'ref', 'national')
REPO = 'xisohi/CHINA-IPTV'
UA = {'User-Agent': 'iptv-ci-refdb'}
MIRRORS = ['https://ghproxy.net/https://raw.githubusercontent.com/',
           'https://ghfast.top/https://raw.githubusercontent.com/',
           'https://raw.githubusercontent.com/']


def _clone(tmp):
    subprocess.run(['git', 'clone', '--depth', '1',
                    'https://github.com/%s.git' % REPO, tmp],
                   check=True, timeout=600)
    src = os.path.join(tmp, 'Multicast')
    for prov in os.listdir(src):
        shutil.copytree(os.path.join(src, prov), os.path.join(NAT, prov),
                        dirs_exist_ok=True)


def _raw_fallback():
    req = urllib.request.Request(
        'https://api.github.com/repos/%s/git/trees/main?recursive=1' % REPO, headers=UA)
    tree = json.load(urllib.request.urlopen(req, timeout=30))
    files = [e['path'] for e in tree['tree']
             if e['type'] == 'blob' and re.match(r'Multicast/[^/]+/[^/]+\.txt$', e['path'])]
    print('raw fallback: %d files' % len(files))

    def dl(path):
        for mirror in MIRRORS:
            try:
                r = urllib.request.Request(mirror + '%s/main/%s' % (REPO, path), headers=UA)
                data = urllib.request.urlopen(r, timeout=20).read()
                if data:
                    out = os.path.join(NAT, path[len('Multicast/'):].replace('/', os.sep))
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    with open(out, 'wb') as f:
                        f.write(data)
                    return True
            except Exception:
                continue
        return False

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(dl, files))
    ok = sum(1 for r in results if r)
    print('raw fallback done: %d/%d' % (ok, len(files)))
    if ok < len(files) * 0.5:
        raise RuntimeError('参考数据抓取失败（不足半数），放弃构建')


def main():
    if os.path.isdir(NAT) and os.listdir(NAT):
        print('ref/national 已存在，跳过抓取')
    else:
        os.makedirs(NAT, exist_ok=True)
        cloned = False
        for attempt in range(3):
            tmp = tempfile.mkdtemp(prefix='iptv_ci_')
            try:
                _clone(tmp)
                cloned = True
                break
            except Exception as e:
                print('git clone 第 %d 次失败: %s' % (attempt + 1, e))
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        if not cloned:
            _raw_fallback()
    sys.path.insert(0, HERE)
    import build_refdb
    build_refdb.main()


if __name__ == '__main__':
    main()
