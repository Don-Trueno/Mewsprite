from ..util import svg_tools as svg
from ..util import parse_swf as swf
from . import swf_tree as tree

import copy
import io
import os
import uuid

from typing import Sequence

from PIL import Image as PILImage
from wand.color import Color
from wand.image import Image


class Sprite:
    @staticmethod
    def _coerce_sprite(source: "str | Sprite | svg.SvgData") -> "Sprite":
        if isinstance(source, Sprite):
            return source
        if isinstance(source, svg.SvgData):
            return Sprite(source)

        if isinstance(source, os.PathLike):
            source = os.fspath(source)

        if isinstance(source, str):
            if os.path.isfile(source):
                return Sprite(svg.parse_svg(source))
            if "<svg" in source:
                return Sprite(svg.SvgData.parseSVG(source.splitlines()))
            raise ValueError(f"Unsupported SVG input: {source!r}")

        raise TypeError(f"Unsupported SVG source type: {type(source)!r}")

    @staticmethod
    def matrixToSVG(matrix: swf.Matrix) -> str:
        return f"matrix({matrix.xscale}, {matrix.skew1}, {matrix.skew2}, {matrix.yscale}, {matrix.xoffset}, {matrix.yoffset})"

    @staticmethod
    def matrixFromSVG(matrix: str) -> swf.Matrix:
        if (matrix == ""):
            return swf.Matrix()

        components = matrix.removeprefix(
            "matrix(").removesuffix(')').split(',')

        out = swf.Matrix()
        out.xscale = float(components[0])
        out.skew1 = float(components[1])
        out.skew2 = float(components[2])
        out.yscale = float(components[3])
        out.xoffset = float(components[4])
        out.yoffset = float(components[5])
        return out

    @staticmethod
    def rgbToSVG(r: int, g: int, b: int) -> str:
        return f"#{r:02x}{g:02x}{b:02x}"

    @staticmethod
    def rgbFromSVG(rgb: str) -> tuple[int, int, int]:
        rgb = rgb.removeprefix('#')
        s = 1 if len(rgb) == 3 else 2

        r = int(rgb[0:s], 16)
        g = int(rgb[s:s+s], 16)
        b = int(rgb[s+s:s*3], 16)
        return (r, g, b)

    @staticmethod
    def getNonTransparentBounds(source: "str | Sprite | svg.SvgData") -> tuple[float, float, float, float]:
        """返回最小不透明边界框的左、上、右、下坐标"""
        sprite = Sprite._coerce_sprite(source)

        with Color('transparent') as bg:
            with Image(blob=sprite.compile().encode("utf-8"), background=bg, resolution=72) as img:
                png = img.make_blob("png")

        with PILImage.open(io.BytesIO(png)) as rgba_img:
            alpha = rgba_img.convert("RGBA").getchannel("A")
            bbox = alpha.getbbox()
            if bbox is None:
                width, height = rgba_img.size
                return (0.0, 0.0, float(width), float(height))

            left, top, right, bottom = bbox
            return (float(left), float(top), float(right), float(bottom))

    def cropToBounds(self, left: float, top: float, right: float, bottom: float) -> "Sprite":
        if right <= left or bottom <= top:
            raise ValueError("Crop bounds must satisfy left < right and top < bottom")

        width, height = self.getDimensions()
        left = max(0.0, float(left))
        top = max(0.0, float(top))
        right = min(float(right), float(width))
        bottom = min(float(bottom), float(height))

        if right <= left or bottom <= top:
            raise ValueError("Crop bounds are empty after clamping to the SVG dimensions")

        out = copy.deepcopy(self)
        root = out.data.data
        crop_w = right - left
        crop_h = bottom - top

        root.setField("width", f"{crop_w}px")
        root.setField("height", f"{crop_h}px")
        root.setField("viewBox", f"{left} {top} {crop_w} {crop_h}")
        root.subcomponents = [svg.SvgData.Composite(
            f'<g transform="translate({-left}, {-top})">\n',
            root.subcomponents,
        )]

        return out

    data: "svg.SvgData | None"

    def __init__(self, data: svg.SvgData):
        self.data = data

    def getImportantComponents(self) -> list[svg.SvgData.Composite]:
        # <svg> is not important
        return self.data.data.subcomponents

    def getDimensions(self) -> tuple[float, float]:
        w = float(self.data.data.getField("width").removesuffix("px"))
        h = float(self.data.data.getField("height").removesuffix("px"))

        return (w, h)

    def applyTransform(self, xform: swf.CXFORM | swf.Matrix | None):
        if (xform == None):  # makes things a bit simpler
            return self

        def applyCXFORM(data: svg.SvgData.Composite):
            if ("fill=\"#" in data.header):
                r, g, b = Sprite.rgbFromSVG(data.getField("fill"))
                astr = data.getField("opacity")
                a = float(astr if astr != "" else 1.0) * 255.0

                nr, ng, nb, na = xform.transform(
                    float(r), float(g), float(b), a)
                data.setField("fill", Sprite.rgbToSVG(
                    int(nr), int(ng), int(nb)))

                if (na != 255.0 or astr != ""):
                    data.setField("opacity", str(na / 255.0))

            if ("stop-color=\"#" in data.header):
                # @TODO handle opacity?
                r, g, b = Sprite.rgbFromSVG(data.getField("stop-color"))
                nr, ng, nb, na = xform.transform(
                    float(r), float(g), float(b), 1.0)
                data.setField(
                    "stop-color", Sprite.rgbToSVG(int(nr), int(ng), int(nb)))

        if isinstance(xform, swf.CXFORM):
            self.data.forEach(applyCXFORM)

        else:
            comp = svg.SvgData.Composite(
                f"<g transform=\"{Sprite.matrixToSVG(xform)}\">\n", self.getImportantComponents())
            self.data.data.subcomponents = [comp]

        return self

    def compile(self) -> str:
        dx, dy = self.getDimensions()
        rebaseCenter = swf.Matrix()
        rebaseCenter.xoffset += dx / 2.0
        rebaseCenter.yoffset += dy / 2.0

        # self.applyTransform(rebaseCenter)
        return self.data.compile()

    def free(self):
        """Drop this sprite's parsed SVG tree.

        Frames carry a deep copy of a whole SVG tree, so a long animation keeps
        hundreds of trees alive after their markup has been written out.  The
        data of a freed sprite must not be used again.
        """
        self.data = None


# first element is drawn last, last is drawn first
def mergeSprites(sprites: list[Sprite], mwid: float = 200.0, mhig: float = 200.0) -> Sprite:
    for sprite in sprites:
        dims = sprite.getDimensions()
        mwid = max(dims[0], mwid)
        mhig = max(dims[1], mhig)

    # The trailing newline matters: `svg_tools.parse_svg` reads SVG files line by
    # line, so a root tag glued to its first child makes the file unreadable
    # again (this is what the reusable/shapes cache round-trips through).
    svgTag = f"<svg width=\"{mwid}px\" height=\"{mhig}px\" xmlns:xlink=\"http://www.w3.org/1999/xlink\" xmlns=\"http://www.w3.org/2000/svg\" xmlns:ffdec=\"https://www.free-decompiler.com/flash\">\n"

    if len(sprites) == 0:
        return Sprite(svg.SvgData("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"no\"?>\n", svg.SvgData.Composite(svgTag, [])))

    out = Sprite(svg.SvgData(
        sprites[0].data.xmlVersion, svg.SvgData.Composite(svgTag, [])))

    for sprite in sprites:
        out.data.data.subcomponents += sprite.getImportantComponents()

    return out


def getShape(dumpdir: str, id: int, name: str = "") -> Sprite:
    s = Sprite(svg.parse_svg(os.path.join(
        dumpdir, "shapes", str(id) + ".svg")))

    # make everything 0,0 based so it's possible to work with
    comps = s.getImportantComponents()
    assert (len(comps) > 0 and comps[0].getTagname() == "g")
    if (comps[0].getField("transform") != ""):
        comps[0].setField("transform", "matrix(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)")

    if (comps[0].getField("id") == ""):
        if name == "":
            comps[0].setField("id", "DefineShape_" + str(id))
        else:
            comps[0].setField("id", name + '_' + str(id))

    return s


def getText(dumpdir: str, id: int, name: str = "") -> Sprite:
    s = Sprite(svg.parse_svg(os.path.join(dumpdir, "texts", str(id) + ".svg")))

    # make everything 0,0 based so it's possible to work with
    comps = s.getImportantComponents()
    assert (len(comps) > 0 and comps[0].getTagname() == "g")
    if (comps[0].getField("transform") != ""):
        comps[0].setField("transform", "matrix(1.0, 0.0, 0.0, 1.0, 0.0, 0.0)")

    if (comps[0].getField("id") == ""):
        if name == "":
            comps[0].setField("id", "DefineText_" + str(id))
        else:
            comps[0].setField("id", name + '_' + str(id))

    return s


def spriteFromDefineShape(dumpdir: str, tag: swf.DefineShape) -> Sprite:
    return getShape(dumpdir, tag.id)


def spriteFromPlacedObject(dumpdir: str, swfTree: tree.SWF_Tree, obj: tree.PlacedObject, frame: int = 0) -> Sprite:
    refNode = swfTree.get(obj.id)
    assert (refNode != None)

    s = spriteFromNode(dumpdir, swfTree, refNode)
    s.applyTransform(obj.cxform).applyTransform(obj.xform)

    return s


def spriteFromNode(dumpdir: str, swfTree: tree.SWF_Tree, node: tree.SWF_Tree.ShapeNode | tree.SWF_Tree.TextNode | tree.SWF_Tree.SpriteNode, frame: int = 0) -> Sprite:
    if isinstance(node, tree.SWF_Tree.ShapeNode):
        return getShape(dumpdir, node.id, node.name)
    elif isinstance(node, tree.SWF_Tree.TextNode):
        return getText(dumpdir, node.id, node.name)

    f = node.frames[frame]
    if (len(f.objs) == 0):
        return Sprite(svg.SvgData("<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"no\"?>\n", svg.SvgData.Composite("<svg width=\"0.0px\" height=\"0.0px\">\n", [])))

    return spriteFromPlacedObjects(dumpdir, swfTree, f.objs)


class PlacedSprite:
    sprite: Sprite
    id: int
    name: str
    depth: int
    clipDepth: int | None

    def __init__(self, sprite: Sprite, id: int, depth: int, clipDepth: int | None = None, name: str = ""):
        self.sprite = sprite
        self.id = id
        self.name = name
        self.depth = depth
        self.clipDepth = clipDepth


def spriteFromPlacedObjects(dumpdir: str, swfTree: tree.SWF_Tree, objs: Sequence[tree.PlacedObject | PlacedSprite]) -> Sprite:
    sprites: list[Sprite] = []
    clips: list[tuple[int, int, str]] = []
    for obj in objs:
        if (obj.clipDepth != None):
            obj.name += '_' + str(obj.id) + str(uuid.uuid4())
            clips.append((obj.depth, obj.clipDepth, obj.name))

            if (isinstance(obj, PlacedSprite)):
                sprite = obj.sprite
            else:
                sprite = spriteFromPlacedObject(dumpdir, swfTree, obj)

            comp = svg.SvgData.Composite(
                f"<clipPath id=\"{obj.name}\">\n", sprite.getImportantComponents())
            comp.removeRedundantGs(True)

            ic = sprite.getImportantComponents()
            if (len(ic) == 1 and ic[0].getTagname() == "g"):
                comp.setField("transform", ic[0].getField("transform"))
                comp.subcomponents = ic[0].subcomponents

            sprite.data.data.subcomponents = [comp]
            sprites.append(sprite)

    clips = sorted(clips, key=lambda dn: dn[0], reverse=True)
    objs = sorted(objs, key=lambda obj: obj.depth)
    for obj in objs:
        if (obj.clipDepth != None and obj.clipDepth != 0):
            continue

        if (isinstance(obj, PlacedSprite)):
            sprite = obj.sprite
        else:
            sprite = spriteFromPlacedObject(dumpdir, swfTree, obj)

        for clipStart, clipEnd, id in clips:
            if (obj.depth >= clipStart and obj.depth <= clipEnd):
                comp = svg.SvgData.Composite(
                    f"<g clip-path=\"url(#{id})\">\n", sprite.getImportantComponents())
                sprite.data.data.subcomponents = [comp]

        sprite.data.data.removeRedundantGs()
        sprites.append(sprite)

    return mergeSprites(sprites)
