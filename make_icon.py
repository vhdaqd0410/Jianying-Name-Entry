# -*- coding: utf-8 -*-
"""生成软件图标: 海外人名条批量生成 (256px ico + png)"""
from PIL import Image, ImageDraw, ImageFilter
import os

SIZE = 256
base = os.path.dirname(os.path.abspath(__file__))

def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

def rounded_gradient(size, top, bottom, radius):
    """渐变圆角背景"""
    img = Image.new('RGB', (size, size), top)
    d = ImageDraw.Draw(img)
    # 逐行渐变
    for y in range(size):
        t = y / (size - 1)
        d.line([(0, y), (size, y)], fill=lerp(top, bottom, t))
    # 圆角遮罩
    mask = Image.new('L', (size, size), 0)
    dm = ImageDraw.Draw(mask)
    dm.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return img, mask

# 主图标
img, mask = rounded_gradient(SIZE, (0, 122, 255), (0, 61, 153), radius=56)
d = ImageDraw.Draw(img)

# 中心: 白色人名条卡片
card_w, card_h = 168, 92
cx, cy = SIZE // 2, SIZE // 2 - 8
left, top = cx - card_w // 2, cy - card_h // 2
d.rounded_rectangle([left, top, left + card_w, top + card_h], radius=22, fill='#ffffff')

# 卡片里: 名字占位横线 (模拟"名字"文字)
name_w = 100
name_x = cx - name_w // 2
name_y = cy - 6
d.rounded_rectangle([name_x, name_y, name_x + name_w, name_y + 14], radius=7, fill='#c9d6e8')

# 卡片下方: 绿色下划线 (字幕条特征, 与进度色呼应)
line_w = 120
line_y = top + card_h + 12
d.rounded_rectangle([cx - line_w // 2, line_y, cx + line_w // 2, line_y + 14], radius=7, fill='#2ecc71')

# 应用圆角
out = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
out.paste(img, (0, 0), mask)

# 保存 png
png_path = os.path.join(base, 'icon.png')
out.save(png_path)

# 保存多尺寸 ico
ico_path = os.path.join(base, 'icon.ico')
out.save(ico_path, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print('PNG:', png_path, out.size)
print('ICO:', ico_path)
