from PIL import Image, ImageDraw, ImageFont

size = 256
img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
for i in range(size):
    t = i / (size - 1)
    r = int(59 + (139 - 59) * t)
    g = int(130 + (92 - 130) * t)
    b = 246
    d.line([(0, i), (size, i)], fill=(r, g, b, 255))

mask = Image.new("L", (size, size), 0)
md = ImageDraw.Draw(mask)
md.rounded_rectangle([14, 14, 242, 242], radius=56, fill=255)
img.putalpha(mask)

d = ImageDraw.Draw(img)
font = ImageFont.truetype(r"C:\Windows\Fonts\segoeui.ttf", 132)
bbox = d.textbbox((0, 0), "S", font=font)
w = bbox[2] - bbox[0]
h = bbox[3] - bbox[1]
d.text(
    ((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1] - 8),
    "S",
    font=font,
    fill=(255, 255, 255, 255),
)

img.save(
    r"C:\Working_Files\AIMade\SnowBotLauncher\app.ico",
    sizes=[(256, 256), (64, 64), (48, 48), (32, 32), (16, 16)],
)
print("icon saved")
