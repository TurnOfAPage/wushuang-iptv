# -*- coding: utf-8 -*-
"""CI 用：拉取社区参考数据并生成 src/refdb.json.gz。
仓库出于许可证考虑不捆绑社区数据（见 README），CI 构建时现拉现建。
用 git 浅克隆（单次请求），避免 GitHub API 匿名配额限制。
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
NAT = os.path.join(HERE, '..', 'ref', 'national')


def main():
    if os.path.isdir(NAT) and os.listdir(NAT):
        print('ref/national 已存在，跳过抓取')
    else:
        tmp = tempfile.mkdtemp(prefix='iptv_ci_')
        try:
            subprocess.run(['git', 'clone', '--depth', '1',
                            'https://github.com/xisohi/CHINA-IPTV.git', tmp],
                           check=True, timeout=600)
            src = os.path.join(tmp, 'Multicast')
            os.makedirs(NAT, exist_ok=True)
            for prov in os.listdir(src):
                shutil.copytree(os.path.join(src, prov), os.path.join(NAT, prov),
                                dirs_exist_ok=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    sys.path.insert(0, HERE)
    import build_refdb
    build_refdb.main()


if __name__ == '__main__':
    main()
