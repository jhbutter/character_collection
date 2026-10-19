from pathlib import Path
from PIL import Image, ImageDraw

path = Path(__file__).resolve().parents[1] / "data/demo_input/demo.png"
path.parent.mkdir(parents=True, exist_ok=True)
image = Image.new("RGB", (128, 128), "white")
draw = ImageDraw.Draw(image)
draw.rectangle((32, 32, 96, 96), fill="black")
draw.text((5, 5), "SYNTHETIC TEST", fill="black")
image.save(path)
print(path)
