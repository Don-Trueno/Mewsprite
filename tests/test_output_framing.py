"""Exported frames must be framed on a canvas that actually contains them.

The animation canvas is derived from the frames' own drawn pixels; a mistake
there silently produces blank or clipped SVGs, which is exactly what happened
when the measurement ignored ImageMagick's px-to-pixel scaling.
"""

import io
import os
import shutil
import sys
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image as PILImage
from wand.color import Color
from wand.image import Image

from src.catgen import sprite as sprite_mod
from src.util import parse_swf as swf
from src.util import svg_tools
from src import custom_cats

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# a 20x10 solid block, drawn at the origin of its own coordinate space
BLOCK_SVG = (
    '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
    '<svg width="20px" height="10px" xmlns="http://www.w3.org/2000/svg">\n'
    '<g>\n'
    '<path d="M0,0 L20,0 L20,10 L0,10 Z" fill="#ff0000"/>\n'
    '</g>\n'
    '</svg>\n'
)


def make_block(directory: str) -> sprite_mod.Sprite:
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "block.svg")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(BLOCK_SVG)
    return sprite_mod.Sprite(svg_tools.parse_svg(path))


# A solid block plus a barely visible speck far away, mirroring the faint pixels
# ImageMagick leaks from the `<clipPath>` geometry inside the part SVGs.
FAINT_SPECK_SVG = (
    '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
    '<svg width="400px" height="400px" xmlns="http://www.w3.org/2000/svg">\n'
    '<g>\n'
    '<path d="M0,0 L20,0 L20,20 L0,20 Z" fill="#ff0000"/>\n'
    '</g>\n'
    '<g opacity="0.05">\n'
    '<path d="M300,300 L340,300 L340,340 L300,340 Z" fill="#00ff00"/>\n'
    '</g>\n'
    '</svg>\n'
)


def make_faint_speck_sprite(directory: str) -> sprite_mod.Sprite:
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "speck.svg")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(FAINT_SPECK_SVG)
    return sprite_mod.Sprite(svg_tools.parse_svg(path))


def move(part: sprite_mod.Sprite, x: float, y: float) -> sprite_mod.Sprite:
    out = part
    matrix = swf.Matrix()
    matrix.xoffset = x
    matrix.yoffset = y
    out.applyTransform(matrix)
    return out


class FaintArtifactTests(unittest.TestCase):
    """Nearly transparent stray pixels must not pad the animation canvas."""

    def setUp(self):
        self.tmp = os.path.join(REPO_ROOT, f"_test_faint_{os.getpid()}_{uuid.uuid4().hex[:8]}")
        os.makedirs(self.tmp, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_far_faint_pixels_are_ignored(self):
        speck = make_faint_speck_sprite(self.tmp)

        left, top, right, bottom = custom_cats._measure_sprite_bounds(speck, 512.0)

        # only the solid 20x20 block counts, give or take the antialiasing halo
        self.assertLess(left, 2.0)
        self.assertLess(top, 2.0)
        self.assertGreater(right, 18.0)
        self.assertGreater(bottom, 18.0)
        self.assertLess(right, 30.0, "the faint speck inflated the right edge")
        self.assertLess(bottom, 30.0, "the faint speck inflated the bottom edge")

    def test_canvas_ignores_the_faint_speck(self):
        canvas = custom_cats.compute_frames_canvas([make_faint_speck_sprite(self.tmp)])
        left, top, right, bottom = canvas

        self.assertLess(right - left, 40.0, f"canvas padded by the speck: {canvas}")
        self.assertLess(bottom - top, 40.0, f"canvas padded by the speck: {canvas}")

    def test_solid_antialiasing_is_still_kept(self):
        block = make_block(self.tmp)
        left, top, right, bottom = custom_cats._measure_sprite_bounds(block, 512.0)

        # the block is 20x10 at the origin: nothing may be trimmed away
        self.assertLessEqual(left, 0.0)
        self.assertLessEqual(top, 0.0)
        self.assertGreaterEqual(right, 20.0)
        self.assertGreaterEqual(bottom, 10.0)


class CanvasMeasurementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.join(REPO_ROOT, f"_test_framing_{os.getpid()}_{uuid.uuid4().hex[:8]}")
        os.makedirs(self.tmp, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_bounds_are_measured_in_frame_coordinates(self):
        block = make_block(self.tmp)
        frames = [move(make_block(self.tmp), -50.0, -30.0),
                  move(make_block(self.tmp), 10.0, 25.0)]

        left, top, right, bottom = custom_cats.compute_frames_canvas(frames)

        self.assertAlmostEqual(left, -50.0, delta=2.0)
        self.assertAlmostEqual(top, -30.0, delta=2.0)
        self.assertAlmostEqual(right, 30.0, delta=2.0)
        self.assertAlmostEqual(bottom, 35.0, delta=2.0)

    def test_exported_frames_are_not_blank(self):
        frames = [move(make_block(self.tmp), -50.0, -30.0),
                  move(make_block(self.tmp), 10.0, 25.0)]

        outdir = os.path.join(self.tmp, "out")
        custom_cats.save_cat_output(outdir, "TestCat", "testF", frames, generate_gif=False)

        frame_dir = os.path.join(outdir, "TestCat-testF")
        svgs = sorted(os.listdir(frame_dir))
        self.assertEqual(len(svgs), 2)

        for name in svgs:
            path = os.path.join(frame_dir, name)
            with Color('transparent') as bg:
                with Image(filename=path, background=bg, resolution=custom_cats.MEASURE_DPI) as img:
                    png = img.make_blob("png")
            with PILImage.open(io.BytesIO(png)) as rendered:
                bbox = rendered.convert("RGBA").getchannel("A").getbbox()
                self.assertIsNotNone(bbox, f"{name} rendered completely blank")

                # the block must be inside the canvas, not pushed off an edge
                self.assertGreater(bbox[2] - bbox[0], 5, f"{name} lost its width")
                self.assertGreater(bbox[3] - bbox[1], 2, f"{name} lost its height")

    def test_gif_frames_share_the_canvas(self):
        frames = [move(make_block(self.tmp), -50.0, -30.0),
                  move(make_block(self.tmp), 10.0, 25.0)]

        outdir = os.path.join(self.tmp, "gifout")
        custom_cats.save_cat_output(outdir, "TestCat", "testF", frames,
                                    scaling=1.0, generate_gif=True)

        gif_path = os.path.join(outdir, "TestCat-testF.gif")
        self.assertTrue(os.path.isfile(gif_path))

        with PILImage.open(gif_path) as gif:
            self.assertEqual(gif.n_frames, 2)
            sizes = set()
            boxes = []
            for index in range(gif.n_frames):
                gif.seek(index)
                rgba = gif.convert("RGBA")
                sizes.add(rgba.size)
                boxes.append(rgba.getchannel("A").getbbox())

        self.assertEqual(len(sizes), 1, "every GIF frame must use the same canvas")
        for box in boxes:
            self.assertIsNotNone(box, "a GIF frame rendered blank")


if __name__ == "__main__":
    unittest.main()
