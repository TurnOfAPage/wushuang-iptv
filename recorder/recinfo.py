# -*- coding: utf-8 -*-
"""无双IPTV录像工具 · 产品元信息（独立产品，独立版本号；与主工具 appinfo 互不影响）。"""
import sys

REC_NAME = '无双IPTV录像工具'
REC_VER = '1.0.0'
IS_POSIX = sys.platform != 'win32'
REC_VER_DISPLAY = REC_VER + '-beta' if IS_POSIX else REC_VER
BETA_NOTE = 'Linux/macOS 测试版：未做真机测试，仅供参考。' if IS_POSIX else ''
AUTHOR = '锤无双'
AUTHOR_URL = 'https://www.bilibili.com/video/BV17SWk6VEPZ/'
QQ_GROUP = '170621740'
REPO_URL = 'https://github.com/chuiziyao/wushuang-iptv'
