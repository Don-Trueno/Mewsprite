"""Head component stacking order.

The order is fixed by hand instead of being derived from the `CatHeadPlacements`
sprite, listed from the bottom (drawn first, covered by later layers) to the top:

    front pose: neckItem < lear < rear < head < mouth < leye < lbrow
                       < reye < rbrow < headItem < faceItem
    back pose:  faceItem < leye < lbrow < reye < rbrow < mouth
                       < lear < rear < head < headItem < neckItem

These tuples are the contract: if the order in `custom_cats` is changed on
purpose, update them here in the same commit.
"""

import os
import shutil
import sys
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.catgen import catparts as catpart
from src.catgen import sprite as sprite_mod
from src.catgen import swf_tree as tree
from src.util import svg_tools
from src import custom_cats

FRONT_ORDER = ("neckItem", "lear", "rear", "head", "mouth", "leye", "lbrow",
               "reye", "rbrow", "headItem", "faceItem")
BACK_ORDER = ("faceItem", "leye", "lbrow", "reye", "rbrow", "mouth",
              "lear", "rear", "head", "headItem", "neckItem")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def painted_order(back: bool, tmp: str) -> list[str]:
    """Layers of an assembled head sprite, in the order they are painted."""
    catTree = tree.getSwfTree(catpart.CATPARTS_SWF)
    depths = custom_cats._head_layer_depths(back=back)

    svg = (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        '<svg width="4px" height="4px" xmlns="http://www.w3.org/2000/svg">\n'
        '<g id="L">\n'
        '<path d="M0,0 L1,0 L1,1 Z" fill="#ff0000"/>\n'
        '</g>\n'
        '</svg>\n'
    )
    path = os.path.join(tmp, "layer.svg")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(svg)

    assembly = []
    # deliberately appended in a scrambled order; only the depths should matter
    for layer in reversed(FRONT_ORDER):
        part = sprite_mod.Sprite(svg_tools.parse_svg(path))
        # the root <svg> element is dropped by mergeSprites, so tag the <g> that
        # actually survives into the merged document
        part.getImportantComponents()[0].setID(f"layer_{layer}")
        assembly.append(sprite_mod.PlacedSprite(part, 0, depths[layer], None, layer))

    merged = sprite_mod.spriteFromPlacedObjects(tmp, catTree, assembly)
    seen: list[str] = []

    def walk(comp):
        if comp.getID().startswith("layer_"):
            seen.append(comp.getID().removeprefix("layer_"))
        for sub in comp.subcomponents:
            walk(sub)

    walk(merged.data.data)
    return seen


class HeadLayerOrderTests(unittest.TestCase):
    def test_front_pose_order(self):
        depths = custom_cats._head_layer_depths(back=False)
        self.assertEqual([name for name, _ in sorted(depths.items(), key=lambda kv: kv[1])],
                         list(FRONT_ORDER))

    def test_back_pose_order(self):
        depths = custom_cats._head_layer_depths(back=True)
        self.assertEqual([name for name, _ in sorted(depths.items(), key=lambda kv: kv[1])],
                         list(BACK_ORDER))

    def test_every_layer_has_a_unique_depth(self):
        for back in (False, True):
            depths = custom_cats._head_layer_depths(back=back)
            self.assertEqual(len(set(depths.values())), len(depths))
            self.assertEqual(set(depths), set(FRONT_ORDER))

    def test_front_pose_relations_from_the_spec(self):
        depths = custom_cats._head_layer_depths(back=False)
        # neck item at the very bottom, behind the ears and the head
        self.assertLess(depths["neckItem"], depths["lear"])
        self.assertLess(depths["lear"], depths["rear"])
        self.assertLess(depths["rear"], depths["head"])
        # face features on top of the head, mouth below the left eye
        self.assertLess(depths["head"], depths["mouth"])
        self.assertLess(depths["mouth"], depths["leye"])
        self.assertLess(depths["leye"], depths["lbrow"])
        self.assertLess(depths["lbrow"], depths["reye"])
        self.assertLess(depths["reye"], depths["rbrow"])
        # gear: head item, then face item on top
        self.assertLess(depths["rbrow"], depths["headItem"])
        self.assertLess(depths["headItem"], depths["faceItem"])

    def test_back_pose_relations_from_the_spec(self):
        depths = custom_cats._head_layer_depths(back=True)
        # face item at the very bottom, then the face features behind the head
        self.assertLess(depths["faceItem"], depths["leye"])
        self.assertLess(depths["rbrow"], depths["mouth"])
        self.assertLess(depths["mouth"], depths["lear"])
        self.assertLess(depths["lear"], depths["rear"])
        self.assertLess(depths["rear"], depths["head"])
        # head item, then neck item on top
        self.assertLess(depths["head"], depths["headItem"])
        self.assertLess(depths["headItem"], depths["neckItem"])


class HeadAssemblyOrderTests(unittest.TestCase):
    """The assembled head sprite must end up painted in that order."""

    def setUp(self):
        self.tmp = os.path.join(REPO_ROOT, f"_test_headorder_{os.getpid()}_{uuid.uuid4().hex[:8]}")
        os.makedirs(self.tmp, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_front_layers_are_painted_bottom_to_top(self):
        seen = painted_order(back=False, tmp=self.tmp)
        self.assertEqual(len(seen), len(FRONT_ORDER), "not every layer reached the sprite")
        self.assertEqual(seen, list(FRONT_ORDER))

    def test_back_layers_are_painted_bottom_to_top(self):
        seen = painted_order(back=True, tmp=self.tmp)
        self.assertEqual(len(seen), len(BACK_ORDER), "not every layer reached the sprite")
        self.assertEqual(seen, list(BACK_ORDER))


if __name__ == "__main__":
    unittest.main()
