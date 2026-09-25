from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path("assets")
OUT.mkdir(exist_ok=True)

size = 256
img = Image.new("RGBA", (size, size), (18, 22, 30, 255))
d = ImageDraw.Draw(img)

# Mechanical sandbox emblem: gear-like ring + hot physics core.
cx = cy = size // 2
for r, color, width in [
    (94, (95, 180, 255, 255), 18),
    (63, (35, 46, 62, 255), 12),
]:
    d.ellipse((cx-r, cy-r, cx+r, cy+r), outline=color, width=width)

for a in range(0, 360, 45):
    import math
    rad = math.radians(a)
    x = cx + math.cos(rad) * 108
    y = cy + math.sin(rad) * 108
    w = 22
    d.rectangle((x-w/2, y-w/2, x+w/2, y+w/2), fill=(95, 180, 255, 255))

d.ellipse((82, 82, 174, 174), fill=(255, 83, 43, 255))
d.ellipse((105, 105, 151, 151), fill=(255, 210, 85, 255))

img.save(OUT / "app_icon.ico", sizes=[(16,16), (32,32), (48,48), (64,64), (128,128), (256,256)])
