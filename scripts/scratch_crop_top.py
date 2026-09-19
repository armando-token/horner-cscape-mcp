from PIL import Image

im = Image.open("artifacts/recovery/screen1_cscape.png")
crop = im.crop((140, 5, 500, 35))
crop.save("artifacts/recovery/top_toolbar_crop.png")
print("Saved crop, size:", crop.size)
