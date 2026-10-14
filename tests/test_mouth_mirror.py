"""A left-looking face must keep the mouth's placement offset.

`CatHeadPlacements` places the mouth at `matrix(1, 0, 0, 1, -0.6, 7.5)`, i.e. 7.5
units below the face origin.  When the cat looks left the mouth is mirrored, and
the old code did that by overwriting the outermost `<g>` -- which *is* that
placement -- so the mouth lost the +7.5 and jumped 7.5 units up.  The mirror has
to go inside the placement instead.
"""

import copy
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


def effective_transform(component) -> swf.Matrix:
    """Compose every transform from the sprite root down to its first leaf."""
    composed = swf.Matrix()
    node = component.data.data
    while node.subcomponents:
        node = node.subcomponents[0]
        transform = sprite_mod.Sprite.matrixFromSVG(node.getTransform())
        composed = swf.matrix_multiply(composed, transform)
    return composed


class MouthMirrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catTree = tree.getSwfTree(catpart.CATPARTS_SWF)
        cls.palettes = palette_mod.loadPalettes("./data/textures/palette.png")
        cls.cats = {cat.id: cat for cat in custom_cats.getCustomCats()}

    def _mouths(self, cat_id: str):
        cat = self.cats[cat_id]
        placements = catpart.HeadPlacements(
            self.catTree.get("CatHeadPlacements").frames[cat.head.frame])
        _headXForm, face = custom_cats.makeCatHead(
            cat, PART_DIR, self.palettes, self.catTree)
        return placements, {
            "mouth_closed": face.mouth_closed,
            "mouth_open": face.mouth_open,
            "mouth_smile": face.mouth_smile,
        }

    def test_placement_declares_a_downward_offset(self):
        """Guards the test below: the mouth placement must not be a no-op."""
        for cat_id in ("HunterCat", "ButcherCat", "ThiefCat"):
            placements, _ = self._mouths(cat_id)
            self.assertEqual(placements.mouth.xform.yoffset, 7.5,
                             f"{cat_id}: mouth placement changed")
            self.assertNotEqual(placements.mouth.xform.yoffset, 0.0)

    def test_left_looking_mouth_keeps_its_placement(self):
        for cat_id in ("HunterCat", "ButcherCat", "ThiefCat"):
            placements, mouths = self._mouths(cat_id)
            expected_y = placements.mouth.xform.yoffset

            for pose_name, expect_mirror in (("default", False), ("faceleft", True)):
                pose = custom_cats.resolve_face_pose(pose_name)

                for name, component in mouths.items():
                    if component is None:
                        continue

                    part = copy.deepcopy(component)
                    if pose.offset[0] < 0:
                        custom_cats.mirror_sprite_x(part)

                    onlyoffset = swf.Matrix()
                    onlyoffset.xoffset = pose.offset[0]
                    onlyoffset.yoffset = -pose.offset[1]
                    part.applyTransform(onlyoffset)

                    effective = effective_transform(part)

                    self.assertAlmostEqual(
                        effective.yoffset, expected_y + (-pose.offset[1]), places=4,
                        msg=f"{cat_id}/{name}/{pose_name}: the vertical placement "
                            f"was lost (got {effective.yoffset}, want "
                            f"{expected_y + (-pose.offset[1])})")

                    if expect_mirror:
                        self.assertLess(effective.xscale, 0.0,
                                        f"{cat_id}/{name}: the mouth was not mirrored")
                    else:
                        self.assertGreater(effective.xscale, 0.0)

    def test_upward_looking_face_is_shifted_by_its_own_offset(self):
        """A pose with a vertical offset must still move the mouth by it."""
        placements, mouths = self._mouths("HunterCat")
        pose = custom_cats.resolve_face_pose("faceup")
        self.assertEqual(pose.offset, (0.0, -10.0))

        part = copy.deepcopy(mouths["mouth_closed"])
        onlyoffset = swf.Matrix()
        onlyoffset.xoffset = pose.offset[0]
        onlyoffset.yoffset = -pose.offset[1]
        part.applyTransform(onlyoffset)

        effective = effective_transform(part)
        self.assertAlmostEqual(
            effective.yoffset,
            placements.mouth.xform.yoffset + 10.0, places=4)


class MirrorHelperTests(unittest.TestCase):
    def test_mirror_keeps_a_synthetic_placement(self):
        from src.catgen import sprite as sprite_mod_local
        from src.util import svg_tools

        tmp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           f"_test_mirror_{os.getpid()}")
        os.makedirs(tmp, exist_ok=True)
        try:
            path = os.path.join(tmp, "part.svg")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
                    '<svg width="10px" height="10px" xmlns="http://www.w3.org/2000/svg">\n'
                    '<g id="art">\n'
                    '<path d="M0,0 L10,0 L10,10 Z" fill="#ff0000"/>\n'
                    '</g>\n'
                    '</svg>\n')

            part = sprite_mod_local.Sprite(svg_tools.parse_svg(path))
            placement = swf.Matrix()
            placement.xoffset = -0.6
            placement.yoffset = 7.5
            part.applyTransform(placement)

            custom_cats.mirror_sprite_x(part)

            root = part.data.data
            self.assertEqual(root.subcomponents[0].getTransform(),
                             sprite_mod_local.Sprite.matrixToSVG(placement),
                             "the placement transform was overwritten")
            self.assertEqual(
                root.subcomponents[0].subcomponents[0].getTransform(),
                "matrix(-1.0, 0.0, 0.0, 1.0, 0.0, 0.0)")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
