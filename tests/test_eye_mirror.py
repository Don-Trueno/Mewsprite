"""How the two eyes are drawn.

`leye` / `reye` name an eye by where it appears in the **exported frame**, not by
the cat's anatomical side: `leye` is the eye on the left of the rendered cat and
`reye` the one on the right (see `.github/instructions.md`).

The eye artwork is authored once and one side is flipped by the placement from
`CatHeadPlacements`: `leye` keeps a positive x-scale, `reye` carries a negative
one.  `makeCatHead` therefore mirrors `reye_open` / `reye_closed` as well, which
cancels that flip so both eyes end up drawn with the artwork's own orientation.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.catgen import catparts as catpart
from src.catgen import palette as palette_mod
from src.catgen import swf_tree as tree
from src.catgen import sprite as sprite_mod
from src.util import parse_swf as swf
from src import custom_cats

PART_DIR = "./cache/swfdump/catparts"

MIRROR = "matrix(-1.0, 0.0, 0.0, 1.0, 0.0, 0.0)"


def levels(component) -> list[str]:
    """The transforms from the sprite root downwards, outermost first."""
    out: list[str] = []
    node = component.data.data
    while node.subcomponents:
        node = node.subcomponents[0]
        out.append(node.getTransform())
    return out


def net_xscale(component) -> float:
    """The horizontal scale the whole chain ends up with."""
    composed = swf.Matrix()
    node = component.data.data
    while node.subcomponents:
        node = node.subcomponents[0]
        composed = swf.matrix_multiply(
            composed, sprite_mod.Sprite.matrixFromSVG(node.getTransform()))
    return composed.xscale


def x_scale(transform: str) -> float:
    if not transform:
        return 1.0
    body = transform.removeprefix("matrix(").removesuffix(")")
    return float(body.split(",")[0])


CATS = ("HunterCat", "ButcherCat", "Pebbles")


class EyeMirrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catTree = tree.getSwfTree(catpart.CATPARTS_SWF)
        cls.palettes = palette_mod.loadPalettes("./data/textures/palette.png")
        cls.cats = {cat.id: cat for cat in custom_cats.getCustomCats()}

    def _face(self, cat_id, mirror=True):
        original = custom_cats.mirror_sprite_x
        if not mirror:
            custom_cats.mirror_sprite_x = lambda part: None
        custom_cats._HEAD_FACE_CACHE.clear()
        try:
            _headXForm, face = custom_cats.makeCatHead(
                self.cats[cat_id], PART_DIR, self.palettes, self.catTree)
        finally:
            custom_cats.mirror_sprite_x = original
            custom_cats._HEAD_FACE_CACHE.clear()
        return face

    def test_the_right_eye_carries_the_extra_mirror(self):
        """`reye` is drawn on the right of the frame and gets its flip cancelled."""
        for cat_id in CATS:
            face = self._face(cat_id)

            for name in ("reye_open", "reye_closed"):
                part = getattr(face, name, None)
                if part is None:
                    continue
                chain = levels(part)
                self.assertLess(x_scale(chain[0]), 0.0,
                                f"{cat_id}/{name}: the placement should carry the flip")
                self.assertIn(MIRROR, chain[1:],
                              f"{cat_id}/{name}: the cancelling mirror is missing")

    def test_the_left_eye_is_not_mirrored(self):
        for cat_id in CATS:
            face = self._face(cat_id)

            for name in ("leye_open", "leye_closed"):
                part = getattr(face, name, None)
                if part is None:
                    continue
                chain = levels(part)
                self.assertGreater(x_scale(chain[0]), 0.0,
                                   f"{cat_id}/{name}: the placement should not be flipped")
                self.assertNotIn(MIRROR, chain, f"{cat_id}/{name}: the left eye was mirrored")

    def test_both_eyes_end_up_unflipped(self):
        """The invariant the two placements plus the mirror exist to produce."""
        for cat_id in CATS:
            face = self._face(cat_id)

            for name in ("leye_open", "leye_closed", "reye_open", "reye_closed"):
                part = getattr(face, name, None)
                if part is None:
                    continue
                self.assertAlmostEqual(net_xscale(part), 1.0, places=3,
                                       msg=f"{cat_id}/{name}: odd net x-scale")

    def test_the_brows_keep_their_placements(self):
        for cat_id in CATS:
            face = self._face(cat_id)
            for name in ("lbrow", "rbrow"):
                part = getattr(face, name, None)
                if part is None:
                    continue
                self.assertNotIn(MIRROR, levels(part),
                                 f"{cat_id}/{name}: the brows are not mirrored")

    def test_the_mirrored_eye_stays_where_it_was(self):
        """Mirroring flips the artwork about its own centre, it does not move it."""
        for cat_id in CATS:
            flipped = getattr(self._face(cat_id), "reye_open", None)
            plain = getattr(self._face(cat_id, mirror=False), "reye_open", None)
            if flipped is None or plain is None:
                continue

            a = custom_cats._measure_sprite_bounds(flipped, 1024.0)
            b = custom_cats._measure_sprite_bounds(plain, 1024.0)
            shift_x = abs((a[0] + a[2]) / 2.0 - (b[0] + b[2]) / 2.0)
            shift_y = abs((a[1] + a[3]) / 2.0 - (b[1] + b[3]) / 2.0)

            self.assertLess(shift_x, 6.0, f"{cat_id}: the mirrored eye moved sideways")
            self.assertLess(shift_y, 2.0, f"{cat_id}: the mirrored eye moved vertically")


if __name__ == "__main__":
    unittest.main()
