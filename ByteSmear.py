from PIL import Image


with open(r"C:\Users\Matthew\Documents\Games\Visual Boy Advance\roms\wram.dmp","rb") as f:
    data = f.read()

img = Image.new("RGB",(512,512))
pixels = img.load()

for y in range(512):
    for x in range(512):
        color = data[(y<<9) + x]
        pixels[x,y] = (color,color,color)

img.save("Untitled.png")