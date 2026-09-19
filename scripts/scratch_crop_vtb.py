from PIL import Image

im = Image.open("artifacts/recovery/screen1_cscape.png")
crop = im.crop((105, 200, 135, 520))
crop.save("artifacts/recovery/vertical_toolbar_crop.png")
print("Saved vertical toolbar crop, size:", crop.size)
