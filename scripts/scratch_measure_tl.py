from PIL import Image

im = Image.open("artifacts/recovery/toolbox_items_crop.png")
# Search for 'T' icon or 'Text Label' text
# Crop size is (175, 170).
# Let's inspect rows y=40..70
print("Crop dimensions:", im.size)
for y in range(40, 75, 5):
    colors = [im.getpixel((x, y)) for x in range(10, 60, 5)]
    print(f"y={y}: {colors[:5]}")
