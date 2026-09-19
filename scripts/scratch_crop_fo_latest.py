from PIL import Image

im = Image.open("artifacts/recovery/screen1_cscape.png")
crop = im.crop((110, 140, 240, 360))
crop.save("artifacts/recovery/toolbox_fixed_crop.png")
print("Saved toolbox_fixed_crop.png, size:", crop.size)
