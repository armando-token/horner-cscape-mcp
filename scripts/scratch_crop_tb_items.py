from PIL import Image

im = Image.open("artifacts/recovery/screen1_cscape.png")
crop = im.crop((130, 190, 305, 360))
crop.save("artifacts/recovery/toolbox_items_crop.png")
print("Saved crop, size:", crop.size)
