"""``headblend_*`` is a head layer family of its own.

The SWF names three families of head layers: ``head``, ``head_<pose>`` and
``headblend_<pose>``.  A `headblend_` layer is the expression the frame
cross-fades *away* from: the artist parks it at a fixed spot and a low depth, so
it belongs in the tag pool and in the cached metadata but must not be painted --
painting it drops a second, stray head into the frame.

The old code only knew the ``head_`` prefix, so `headblend_*` matched neither the
head layers nor the `extra` bucket and vanished from the tag pool entirely.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.catgen import animations
from src.catgen import sprite as sprite_mod
from src.util import parse_swf as swf
from src import custom_cats


def make_frame(tags: dict[str, float]) -> animations.CatFrame:
    frame = animations.CatFrame()
    for tag, xoffset in tags.items():
        matrix = swf.Matrix()
        matrix.xoffset = xoffset
        frame.used.setdefault(tag, []).append((matrix, 7))
    return animations.finalizeFrame(frame)



class TagFamilyClassificationTests(unittest.TestCase):
    def test_head_families_are_recognised(self):
        for tag in ("head", "head_eyes_closed", "headblend_face_down_wince",
                    "headblend_bloodthirsty_eyes_closed"):
            self.assertTrue(animations.isHeadTag(tag), tag)

        for tag in ("body", "other_head", "tail", "headband"):
            self.assertFalse(animations.isHeadTag(tag), tag)

    def test_only_headblend_is_a_blend_layer(self):
        self.assertTrue(animations.isHeadBlendTag("headblend_face_down_wince"))
        for tag in ("head", "head_eyes_closed", "body"):
            self.assertFalse(animations.isHeadBlendTag(tag), tag)

    def test_expression_is_stripped_from_both_families(self):
        self.assertEqual(animations.headTagExpression("head_eyes_closed"), "eyes_closed")
        self.assertEqual(animations.headTagExpression("headblend_face_down_wince"),
                         "face_down_wince")
        self.assertIsNone(animations.headTagExpression("head"))

    def test_finalize_keeps_headblend_out_of_extra(self):
        frame = make_frame({"head": 1.0, "head_eyes_closed": 2.0,
                            "headblend_face_down_wince": 3.0, "body": 4.0})

        self.assertEqual(set(frame.extra), set(),
                         "head layers must not leak into `extra`")
        self.assertEqual(frame.face, "", "the plain `head` tag means the frame pose")

    def test_finalize_extracts_the_pose_of_a_headblend_only_frame(self):
        frame = make_frame({"headblend_face_down_wince": 3.0, "body": 4.0})

        self.assertEqual(frame.face, "face_down_wince",
                         "the blend tag's whole name used to end up in `face`")

    def test_frame_used_tag_entries_returns_blend_layers(self):
        frame = make_frame({"head": 1.0, "head_eyes_closed": 2.0,
                            "headblend_face_down_wince": 3.0})

        tags = [name for name, _m, _d in custom_cats.frame_used_tag_entries(frame, "head")]

        self.assertIn("head", tags)
        self.assertIn("head_eyes_closed", tags)
        self.assertIn("headblend_face_down_wince", tags)
        self.assertEqual(len(tags), 3)


class HeadBlendRenderingTests(unittest.TestCase):
    """The blend layer is pooled and recorded, and drawn on top of the head."""

    @classmethod
    def setUpClass(cls):
        from src.catgen import catparts as catpart
        from src.catgen import palette as palette_mod
        from src.catgen import swf_tree as tree

        cls.partDir = "./cache/swfdump/catparts"
        cls.catTree = tree.getSwfTree(catpart.CATPARTS_SWF)
        cls.palettes = palette_mod.loadPalettes("./data/textures/palette.png")
        cls.cat = {c.id: c for c in custom_cats.getCustomCats()}["HunterCat"]
        cls.equip = custom_cats.CatEquipment()

    def _blend_frame(self) -> animations.CatFrame:
        return make_frame({
            "headblend_face_down_wince": 3.0,
            "headblend_face_left_wince": 4.0,
        })

    def test_blend_layer_is_pooled_and_recorded(self):
        frame = self._blend_frame()

        _frames, tag_pool, frames_info = custom_cats._assemble_frames_for_first_cat(
            self.cat, self.partDir, self.palettes, [frame], self.catTree, self.equip)

        self.assertIn("headblend_face_down_wince", tag_pool)
        self.assertIn("headblend_face_left_wince", tag_pool)

        recorded = sorted(tag for _depth, tag, _matrix, _cx in frames_info[0]
                          if tag.startswith("head"))
        self.assertEqual(recorded,
                         ["headblend_face_down_wince", "headblend_face_left_wince"],
                         "the placements must still be recorded in the metadata")

    def test_blend_layer_is_not_assembled_without_a_head(self):
        plan = custom_cats._build_frame_plan(
            self.cat, self.partDir, self.palettes, self.catTree,
            self.equip, self._blend_frame())

        heads = [entry["name"] for entry in plan if entry["name"].startswith("Whole Head")]

        self.assertEqual(heads, [], f"a headblend layer reached the assembly plan: {heads}")

    def test_blend_replaces_a_generic_head(self):
        """While the head tag is the generic `head`, the blend is the pose shown."""
        frame = make_frame({"head": 3.0,
                            "headblend_face_down_wince": 4.0})

        plan = custom_cats._build_frame_plan(
            self.cat, self.partDir, self.palettes, self.catTree, self.equip, frame)

        heads = [entry["name"] for entry in plan if entry["name"].startswith("Whole Head")]

        self.assertEqual(heads,
                         ["Whole Head:headblend_face_down_wince"],
                         "the blend must replace the head, not stack on it")

    def test_specific_head_pose_outranks_the_blend(self):
        """A `head_<pose>` names the destination pose and wins over the blend."""
        frame = make_frame({"head_real_wink": 3.0,
                            "headblend_real_wink_overshoot": 4.0})

        plan = custom_cats._build_frame_plan(
            self.cat, self.partDir, self.palettes, self.catTree, self.equip, frame)

        heads = [entry["name"] for entry in plan if entry["name"].startswith("Whole Head")]

        self.assertEqual(heads, ["Whole Head:head_real_wink"])
    def test_ordinary_head_family_still_reaches_the_plan(self):
        """Guard: nothing swallows the normal head families."""
        frame = make_frame({"head_eyes_closed": 3.0})

        plan = custom_cats._build_frame_plan(
            self.cat, self.partDir, self.palettes, self.catTree, self.equip, frame)

        heads = [entry["name"] for entry in plan if entry["name"].startswith("Whole Head")]

        self.assertEqual(heads, ["Whole Head:head_eyes_closed"])


if __name__ == "__main__":
    unittest.main()

