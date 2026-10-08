"""Character overlay (`character`) layout invariants.

`terminatorPunchF` places its second cat through a single `character`
PlaceObject2 whose symbol is `catanis2_fla.CHARACTEREFFECTSPLACEHOLDER_48` -- a
1-frame marker with no cat artwork.  `terminatorPunchCatF` is the very same
animation, but the second cat is written out explicitly as `other_*` parts, so it
is usable as ground truth for the placeholder's geometry.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.catgen import animations as anim_mod
from src.util import parse_swf as swf

PARTS = ("body", "head", "leg1", "leg2", "arm1", "arm2", "tail")


def layout(frame) -> dict:
    out = {}
    for key in PARTS:
        values = (frame.used or {}).get(key)
        if values:
            out[key] = values[-1][0]
    return out


class RestPoseTranslationTests(unittest.TestCase):
    """Every `character` animation starts from the very same rest pose."""

    @classmethod
    def setUpClass(cls):
        cls.anims = anim_mod.getCatAnims()
        cls.idle = layout(cls.anims["idleF"][0])
        cls.character_anims = sorted(
            name for name, frames in cls.anims.items()
            if any("character" in (frame.extra or {}) for frame in frames))

    def test_character_animations_exist(self):
        self.assertTrue(self.character_anims)

    def test_frame_zero_is_the_idle_pose_shifted(self):
        checked = 0
        for name in self.character_anims:
            frames = self.anims[name]
            if not any((frame.extra or {}).get("character") for frame in frames):
                continue

            rest = layout(frames[0])
            if not rest or not all(key in rest and key in self.idle for key in PARTS):
                continue

            deltas = []
            for key in PARTS:
                if key not in rest or key not in self.idle:
                    continue
                if abs(self.idle[key].xscale - rest[key].xscale) > 1e-3:
                    deltas = []
                    break
                deltas.append((rest[key].xoffset - self.idle[key].xoffset,
                               rest[key].yoffset - self.idle[key].yoffset))

            if not deltas:
                continue

            checked += 1
            first = deltas[0]
            for key, delta in zip([k for k in PARTS if k in rest and k in self.idle], deltas):
                self.assertAlmostEqual(
                    delta[0], first[0], places=2,
                    msg=f"{name}: part '{key}' is not a pure translation of the idle pose")
                self.assertAlmostEqual(
                    delta[1], first[1], places=2,
                    msg=f"{name}: part '{key}' is not a pure translation of the idle pose")

        self.assertGreater(checked, 0, "no character animation could be checked")


class PlaceholderGeometryTests(unittest.TestCase):
    """The placeholder transform must be applied to the animation's rest pose."""

    @classmethod
    def setUpClass(cls):
        cls.anims = anim_mod.getCatAnims()

    def _mean_body_error(self, base_fn) -> float:
        char_frames = self.anims["terminatorPunchF"]
        part_frames = self.anims["terminatorPunchCatF"]
        total = 0.0
        count = 0
        for i in range(len(char_frames)):
            transform = (char_frames[i].extra or {}).get("character")
            truth = (part_frames[i].extra or {}).get("other_body")
            if not transform or not truth:
                continue
            composed = swf.matrix_multiply(transform[0], base_fn(char_frames, i)["body"])
            total += ((composed.xoffset - truth[0].xoffset) ** 2
                      + (composed.yoffset - truth[0].yoffset) ** 2) ** 0.5
            count += 1
        self.assertGreater(count, 0)
        return total / count

    def test_idle_pose_base_is_wrong(self):
        error = self._mean_body_error(lambda frames, i: layout(self.anims["idleF"][0]))
        self.assertGreater(error, 30.0,
                           "the idle animation's in-frame placement must not leak into "
                           "the placeholder geometry")

    def test_rest_pose_base_tracks_the_real_second_cat(self):
        error = self._mean_body_error(lambda frames, i: layout(frames[0]))
        self.assertLess(error, 20.0,
                        "the animation's own rest frame should place the second cat "
                        "close to the explicit other_* parts")


if __name__ == "__main__":
    unittest.main()
