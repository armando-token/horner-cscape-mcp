from PIL import Image

im = Image.open("artifacts/recovery/screen1_cscape.png")
crop = im.crop((340, 5, 650, 35))
crop.save("artifacts/recovery/top_toolbar_crop2.png")
print("Saved crop 2, size:", crop.size)
