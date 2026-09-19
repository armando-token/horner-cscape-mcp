from PIL import Image

im = Image.open("artifacts/recovery/screen1_cscape.png")
crop = im.crop((135, 170, 170, 600))
crop.save("artifacts/recovery/vtb_actual.png")
print("Saved actual vertical toolbar, size:", crop.size)
