# -*- coding: utf-8 -*-
"""应用元信息（GUI 与 CLI 共用，避免版本号多处维护）。"""
import sys

APP_NAME = '无双IPTV抓源工具'
APP_VER = '2.1.0'
# Linux/macOS 移植版为测试版（未做真机测试，仅供参考）；Windows 保持正式版号不变
IS_POSIX = sys.platform != 'win32'
APP_VER_DISPLAY = APP_VER + '-beta' if IS_POSIX else APP_VER
BETA_NOTE = 'Linux/macOS 移植测试版：未做真机测试，仅供参考。' if IS_POSIX else ''
AUTHOR = '锤无双'
AUTHOR_URL = 'https://www.bilibili.com/video/BV17SWk6VEPZ/'
TUTORIAL_URL = 'https://www.bilibili.com/video/BV17SWk6VEPZ/'
QQ_GROUP = '170621740'
REPO_URL = 'https://github.com/chuiziyao/wushuang-iptv'
