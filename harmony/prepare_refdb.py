# -*- coding: utf-8 -*-
"""构建前注入参考库（可选）：抓取社区数据 → 生成 refdb → 写入 rawfile。
仓库出于许可证考虑不捆绑社区数据（见主 README）；不运行本脚本也能构建，
应用首次使用时点「在线更新参考库」即可。
用法: python prepare_refdb.py   （需要网络；依赖 ../src 的抓取/构建脚本）
"""
import gzip
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', 'src')
sys.path.insert(0, SRC)

import fetch_national
import build_refdb


def main():
    nat = os.path.join(SRC, '..', 'ref', 'national')
    if not (os.path.isdir(nat) and os.listdir(nat)):
        fetch_national.main()
    build_refdb.main()
    gz = os.path.join(SRC, 'refdb.json.gz')
    out = os.path.join(HERE, 'entry', 'src', 'main', 'resources', 'rawfile', 'refdb.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with gzip.open(gz, 'rb') as f, open(out, 'wb') as o:
        shutil.copyfileobj(f, o)
    print('已注入: %s (%d bytes)' % (out, os.path.getsize(out)))
    print('注意: rawfile/refdb.json 已被 .gitignore 排除，不会进入仓库。')


if __name__ == '__main__':
    main()
