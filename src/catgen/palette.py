import logging

from ..util import resource_sync as sync

from PIL import Image
logging.getLogger("pillow").setLevel(logging.WARNING)

from typing import cast

from ..util import svg_tools as svg

#: what `PixelAccess` yields for an RGB image
RGB = tuple[int, int, int]

PALETTE_PATH = "./data/textures/palette.png"

class Palette:
    colors: list[tuple[int, int, int]]

    def __init__(self, colors: list[tuple[int, int, int]]):
        self.colors = colors

    def get(self, red: int, green: int, blue: int) -> tuple[int, int, int]:
        if (abs(red - green) >= 1 or abs(red - blue) >= 1):
            return (red, green, blue)
    
        return self.colors[int(red / 16)]

def palettesProduce(filepath: str) -> list[Palette]:
    with Image.open(filepath) as img:
        converted = img.convert("RGB")
        pixels = converted.load()
        height = converted.height

    # PIL only returns None when the image could not be loaded at all
    if pixels is None:
        raise RuntimeError(f"could not read the pixels of '{filepath}'")

    palettes: list[Palette] = []
    for y in range(height):
        cur: list[tuple[int, int, int]] = []
        for x in range(16):
            # an RGB image always yields three channels, which PIL's stubs cannot say
            cur.append(cast(RGB, pixels[x, y]))

        palettes.append(Palette(cur))

    return palettes

paletteMap = sync.MapSync[list[Palette]](palettesProduce)
    
def loadPalettes(src: str) -> list[Palette]:
    return paletteMap.get(src, src)

def applyPalette(palette: Palette, svgdata: svg.SvgData | svg.SvgData.Composite):
    if isinstance(svgdata, svg.SvgData):
        applyPalette(palette, svgdata.data)
        return
    
    if "fill=\"#" in svgdata.header:
        f = svgdata.header.find("fill=\"#") + 7
        fe = svgdata.header.find('"', f)

        if fe - f == 3:
            red = int(svgdata.header[f:f + 1], 16)
            green = int(svgdata.header[f + 1:f + 2], 16)
            blue = int(svgdata.header[f + 2:f + 3], 16)
        else:
            red = int(svgdata.header[f:f + 2], 16)
            green = int(svgdata.header[f + 2:f + 4], 16)
            blue = int(svgdata.header[f + 4:f + 6], 16)

        color = palette.get(red, green, blue)

        svgdata.header = svgdata.header[:f] + f"{color[0]:02x}{color[1]:02x}{color[2]:02x}" + svgdata.header[fe:]

    elif "stop-color=\"#" in svgdata.header:
        f = svgdata.header.find("stop-color=\"#") + 13
        fe = svgdata.header.find('"', f)

        red = int(svgdata.header[f:f + 2], 16)
        green = int(svgdata.header[f + 2:f + 4], 16)
        blue = int(svgdata.header[f + 4:f + 6], 16)

        color = palette.get(red, green, blue)

        svgdata.header = svgdata.header[:f] + f"{color[0]:x}{color[1]:x}{color[2]:x}" + svgdata.header[fe:]

    for sub in svgdata.subcomponents:
        applyPalette(palette, sub)