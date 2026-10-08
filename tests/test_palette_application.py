"""The palette must be applied to a part exactly once.

`_get_cached_cat_component` already recolours every face part, so `makeCatHead`
must not recolour them again.  `Palette.get` is only idempotent while the mapped
colour stops looking like the greyscale source key; Pebbles' palette 4 and
MonkCat's palette 66 map one grey onto another grey, so a second pass shifted the
colour again -- their ears ended up the wrong colour while the head (recoloured
once) stayed correct.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.catgen import palette as palette_mod
from src.catgen import swf_tree as tree
from src.catgen import catparts as catpart
from src import custom_cats

PALETTE_PATH = "./data/textures/palette.png"

# cats whose palette is not idempotent, i.e. the ones the bug was visible on
NON_IDEMPOTENT_CATS = {"Pebbles": 4, "MonkCat": 66}


def fills_of(part) -> set[str]:
    found: set[str] = set()

    def walk(comp):
        fill = comp.getField("fill")
        if fill:
            found.add(fill.lower())
        for sub in comp.subcomponents:
            walk(sub)

    walk(part.data.data)
    return found


class PaletteIdempotencyTests(unittest.TestCase):
    def test_the_affected_palettes_really_are_not_idempotent(self):
        palettes = palette_mod.loadPalettes(PALETTE_PATH)

        for cat_id, index in NON_IDEMPOTENT_CATS.items():
            palette = palettes[index]
            offenders = [value for value in range(0, 256, 16)
                         if palette.get(value, value, value) != palette.get(*palette.get(value, value, value))]
            self.assertTrue(offenders,
                            f"{cat_id} (palette {index}) is idempotent; the regression test below "
                            f"would be vacuous")


class HeadPaletteApplicationTests(unittest.TestCase):
    """Assembled face parts must keep exactly the colours of the cached part."""

    @classmethod
    def setUpClass(cls):
        cls.partDir = "./cache/swfdump/catparts"
        cls.catpartTree = tree.getSwfTree(catpart.CATPARTS_SWF)
        cls.palettes = palette_mod.loadPalettes(PALETTE_PATH)
        cls.cats = {cat.id: cat for cat in custom_cats.getCustomCats()}

    def _expected_ear_fills(self, cat):
        sprite = custom_cats._get_cached_cat_component(
            self.partDir, self.catpartTree, "CatEar", cat,
            cat.leftear.frame, cat.leftear.texture)
        return fills_of(sprite)

    def test_ears_keep_the_single_pass_colours(self):
        for cat_id in NON_IDEMPOTENT_CATS:
            cat = self.cats[cat_id]
            _headXForm, face = custom_cats.makeCatHead(
                cat, self.partDir, self.palettes, self.catpartTree)

            self.assertIsNotNone(face.lear, f"{cat_id} has no left ear")

            expected = self._expected_ear_fills(cat)
            actual = fills_of(face.lear)

            self.assertEqual(
                actual, expected,
                f"{cat_id}: the assembled ear was recoloured more than once "
                f"(expected {sorted(expected)}, got {sorted(actual)})")

    def test_second_palette_pass_would_change_the_ear(self):
        """Guards the test above: applying the palette twice does differ."""
        cat = self.cats["Pebbles"]

        expected = self._expected_ear_fills(cat)
        doubled = set()
        for fill in expected:
            rgb = tuple(int(fill.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
            doubled.add("%02x%02x%02x" % self.palettes[cat.palette].get(*rgb))

        self.assertNotEqual(expected, doubled,
                            "a second palette pass would not change Pebbles' ears")


if __name__ == "__main__":
    unittest.main()
