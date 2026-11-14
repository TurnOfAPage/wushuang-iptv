# -*- coding: utf-8 -*-
"""生成程序图标：电视机 + 播放三角 + 信号波。"""
import os
from PIL import Image, ImageDraw

S = 256
img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# 背景圆角方块（深蓝渐变用纯色代替）
d.rounded_rectangle([8, 8, 248, 248], radius=48, fill=(24, 60, 120, 255))
# 天线
d.line([100, 66, 128, 40], fill=(255, 255, 255, 255), width=8)
d.line([156, 66, 128, 40], fill=(255, 255, 255, 255), width=8)
d.ellipse([122, 32, 134, 44], fill=(255, 200, 60, 255))
# 电视机身
d.rounded_rectangle([36, 66, 220, 196], radius=20, fill=(240, 246, 255, 255))
# 屏幕
d.rounded_rectangle([50, 80, 178, 182], radius=10, fill=(30, 120, 200, 255))
# 播放三角
d.polygon([(96, 104), (96, 158), (146, 131)], fill=(255, 255, 255, 255))
# 右侧旋钮/格栅
d.ellipse([190, 92, 210, 112], fill=(24, 60, 120, 255))
for y in (128, 144, 160):
    d.rounded_rectangle([188, y, 212, y + 6], radius=3, fill=(24, 60, 120, 255))
# 底座
d.rectangle([96, 196, 160, 208], fill=(240, 246, 255, 255))
d.rounded_rectangle([72, 208, 184, 220], radius=6, fill=(240, 246, 255, 255))
# 信号波（右上）
for r, w in ((26, 6), (40, 6)):
    d.arc([200 - r, 40 - r, 200 + r, 40 + r], start=-70, end=20, fill=(255, 200, 60, 255), width=w)

img.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.ico'),
         sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print('icon saved')
