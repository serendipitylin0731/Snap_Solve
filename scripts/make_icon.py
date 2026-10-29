"""Create the Windows executable icon from the app's simple mark."""

from pathlib import Path

from PIL import Image, ImageDraw


def main():
    size = 256
    scale = size / 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((3*scale, 3*scale, 61*scale, 61*scale), radius=15*scale, fill="#246aee")
    lines = [((17, 27), (17, 18)), ((17, 18), (27, 18)),
             ((47, 27), (47, 18)), ((47, 18), (37, 18)),
             ((17, 37), (17, 46)), ((17, 46), (27, 46)),
             ((47, 37), (47, 46)), ((47, 46), (37, 46)),
             ((26, 33), (38, 33))]
    for start, end in lines:
        draw.line((*[v*scale for v in start], *[v*scale for v in end]), fill="white", width=round(4*scale))
    output = Path(__file__).resolve().parent.parent / "assets" / "app.ico"
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="ICO", sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    print(output)


if __name__ == "__main__":
    main()

