# -*- coding: utf-8 -*-
"""无双IPTV-CLI.exe 入口（控制台版，不强制管理员；抓包子命令自行检测权限）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cli

if __name__ == '__main__':
    sys.exit(cli.main(sys.argv[1:]))
