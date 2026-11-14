# -*- coding: utf-8 -*-
"""从 xisohi/CHINA-IPTV 下载全国组播参考源（GitHub API base64 方式，国内可用）。"""
import base64
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

REPO = 'xisohi/CHINA-IPTV'
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'ref', 'national')
UA = {'User-Agent': 'iptv-refdb-builder', 'Accept': 'application/vnd.github+json'}


def get(url, timeout=30, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(1 + i)


def main():
    tree = json.loads(get('https://api.github.com/repos/%s/git/trees/main?recursive=1' % REPO))
    files = [e for e in tree['tree']
             if e['type'] == 'blob' and re.match(r'Multicast/[^/]+/[^/]+\.txt$', e['path'])]
    print('found %d multicast files' % len(files))
    os.makedirs(OUT, exist_ok=True)
    results = []

    def dl(e):
        prov = e['path'].split('/')[1]
        fname = e['path'].split('/')[2]
        try:
            blob = json.loads(get('https://api.github.com/repos/%s/git/blobs/%s' % (REPO, e['sha'])))
            data = base64.b64decode(blob['content'])
            d = os.path.join(OUT, prov)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, fname), 'wb') as f:
                f.write(data)
            return (e['path'], len(data), None)
        except Exception as ex:
            return (e['path'], 0, str(ex))

    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, r in enumerate(ex.map(dl, files)):
            results.append(r)
            if (i + 1) % 20 == 0:
                print('progress %d/%d' % (i + 1, len(files)), flush=True)
    ok = [r for r in results if not r[2]]
    bad = [r for r in results if r[2]]
    print('DONE ok=%d bad=%d total_bytes=%d' % (len(ok), len(bad), sum(r[1] for r in ok)))
    for r in bad:
        print('BAD', r[0], r[2])
    provs = sorted({r[0].split('/')[1] for r in ok})
    print('provinces(%d): %s' % (len(provs), ','.join(provs)))


if __name__ == '__main__':
    main()
