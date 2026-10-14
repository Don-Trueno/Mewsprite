"""SWF `colorTransform` support.

A placement's `colorTransform` tints a part and, more importantly, carries its
alpha: the `headblend_*` cross-fade layers are invisible (alpha 0) most of the
time and fade in/out with it, and animations such as `imbuePoisonF` wash the whole
cat towards another colour.  The tag was parsed but dropped, so none of that ever
reached the render.
"""

import os
import shutil
import sys
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.catgen import animations
from src.catgen import sprite as sprite_mod
from src.catgen import swf_tree as tree
from src.util import parse_swf as swf
from src.util import svg_tools
from src import custom_cats

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RED_SVG = (
    '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
    '<svg width="10px" height="10px" xmlns="http://www.w3.org/2000/svg">\n'
    '<g id="art">\n'
    '<path d="M0,0 L10,0 L10,10 Z" fill="#ff0000"/>\n'
    '</g>\n'
    '</svg>\n'
)


def color_transform(mult=1.0, add=0):
    cx = swf.CXFORM()
    cx.redMult = cx.greenMult = cx.blueMult = cx.alphaMult = mult
    cx.redAdd = cx.greenAdd = cx.blueAdd = cx.alphaAdd = add
    return cx


def placed_object(name, depth, xoffset=0.0, cxform=None):
    """A PlacedObject with the given fields, bypassing the tag encoder.

    The tag-level encoding is covered by test_swf_frame_semantics; here the point
    is that the field survives the trip through `CatFrame`.
    """
    obj = tree.PlacedObject.__new__(tree.PlacedObject)
    obj.id = 100
    obj.name = name
    obj.depth = depth
    obj.clipDepth = None
    obj.move = False
    matrix = swf.Matrix()
    matrix.xoffset = xoffset
    obj.xform = matrix
    obj.cxform = cxform
    return obj


def frames_of(objs_list):
    return [animations.catFrameFromObjs(objs) for objs in objs_list]


class PlacementColorTransformTests(unittest.TestCase):
    def test_cat_frame_keeps_the_color_transform(self):
        frame = frames_of([[placed_object("body", 7, cxform=color_transform(0.5))]])[0]

        matrix, depth, cxform = frame.used["body"][0]
        self.assertEqual(depth, 7)
        self.assertIsNotNone(cxform, "the color transform was dropped")
        self.assertAlmostEqual(cxform.redMult, 0.5)

    def test_legacy_two_element_placements_still_work(self):
        frame = animations.CatFrame()
        matrix = swf.Matrix()
        frame.used["body"] = [(matrix, 7)]
        animations.finalizeFrame(frame)

        self.assertEqual(frame.body[0], matrix)
        self.assertIsNone(frame.body[2], "a legacy placement has no color transform")

    def test_part_attribute_keeps_the_color_transform(self):
        frame = frames_of([[placed_object("head", 13, cxform=color_transform(0.25))]])[0]

        self.assertAlmostEqual(frame.head[2].alphaMult, 0.25)

    def test_extra_keeps_the_color_transform(self):
        frame = frames_of([[placed_object("other_head", 27, cxform=color_transform(0.75))]])[0]

        self.assertAlmostEqual(frame.extra["other_head"][2].alphaMult, 0.75)

    def test_second_cat_parts_keep_the_color_transform(self):
        anim = frames_of([[placed_object("other_head", 27, cxform=color_transform(0.75))]])

        parts = custom_cats._second_character_parts(anim)

        self.assertIn("other_head", parts[0])
        self.assertAlmostEqual(parts[0]["other_head"][2].alphaMult, 0.75)


class ColorTransformRoundTripTests(unittest.TestCase):
    def test_cache_serialisation_round_trips(self):
        original = color_transform(0.5, 20)

        restored = animations.colorTransformFromCache(
            animations.colorTransformToCache(original))

        self.assertIsNotNone(restored)
        self.assertAlmostEqual(restored.redMult, 0.5)
        self.assertAlmostEqual(restored.redAdd, 20)

    def test_absent_transform_stays_absent(self):
        self.assertIsNone(animations.colorTransformToCache(None))
        self.assertIsNone(animations.colorTransformFromCache(None))

    def test_identity_detection(self):
        self.assertTrue(animations.isIdentityColorTransform(None))
        self.assertTrue(animations.isIdentityColorTransform(color_transform()))
        self.assertFalse(animations.isIdentityColorTransform(color_transform(0.5)))


class ColorTransformRenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.join(REPO_ROOT, f"_test_cxform_{os.getpid()}_{uuid.uuid4().hex[:8]}")
        os.makedirs(self.tmp, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _red_sprite(self):
        path = os.path.join(self.tmp, "red.svg")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(RED_SVG)
        return sprite_mod.Sprite(svg_tools.parse_svg(path))

    def _fill_of(self, sprite):
        node = sprite.data.data
        while node.subcomponents:
            node = node.subcomponents[0]
        return node.getField("fill").lower()

    def test_plan_entry_applies_the_color_transform(self):
        template = self._red_sprite()
        plan = [custom_cats._frame_plan_entry(
            "Body", 7, swf.Matrix(), template, color_transform(0.5))]

        assembly = custom_cats._instantiate_frame_plan(plan)

        # #ff0000 * 0.5 -> #7f0000
        self.assertEqual(self._fill_of(assembly[0].sprite), "#7f0000")
        self.assertEqual(self._fill_of(template), "#ff0000",
                         "the cached template must not be recoloured in place")

    def test_plan_entry_without_a_transform_keeps_the_colour(self):
        plan = [custom_cats._frame_plan_entry(
            "Body", 7, swf.Matrix(), self._red_sprite(), None)]

        assembly = custom_cats._instantiate_frame_plan(plan)

        self.assertEqual(self._fill_of(assembly[0].sprite), "#ff0000")

    def test_opacity_is_written_for_a_partial_alpha(self):
        sprite = self._red_sprite()
        sprite.applyTransform(color_transform(1.0))
        cx = swf.CXFORM()
        cx.alphaMult = 0.5
        sprite.applyTransform(cx)

        node = sprite.data.data
        while node.subcomponents:
            node = node.subcomponents[0]
        self.assertAlmostEqual(float(node.getField("opacity")), 0.5, places=3)


class HeadBlendPlacementTests(unittest.TestCase):
    """A `headblend_` replaces the head rather than fading over it."""

    def _frame(self):
        return frames_of([[
            placed_object("headblend_mad", 1, xoffset=71.55,
                          cxform=color_transform(0.5)),
            placed_object("body", 7),
            placed_object("head", 17, xoffset=13.95),
        ]])[0]

    def test_blend_replaces_the_head(self):
        frame = self._frame()

        layers = custom_cats.frame_head_layers(frame)

        self.assertEqual([tag for tag, _p in layers], ["headblend_mad"])
        self.assertAlmostEqual(layers[0][1][0].xoffset, 13.95,
                               msg="the blend must keep the head layer's position")
        self.assertIsNone(layers[0][1][2],
                          "the blend's alpha must be dropped, not applied")

    def test_frame_without_a_blend_keeps_its_head(self):
        frame = frames_of([[placed_object("body", 7),
                            placed_object("head", 17, xoffset=13.95)]])[0]

        layers = custom_cats.frame_head_layers(frame)

        self.assertEqual([tag for tag, _p in layers], ["head"])

    def test_blend_without_a_head_layer_draws_nothing(self):
        frame = frames_of([[placed_object("headblend_mad", 1,
                                          cxform=color_transform(0.5))]])[0]

        self.assertEqual(custom_cats.frame_head_layers(frame), [])

    def test_zero_alpha_blend_still_replaces_the_head(self):
        """No fade: even a fully transparent blend names the pose to show."""
        frame = frames_of([[placed_object("headblend_mad", 1,
                                          cxform=color_transform(0.0)),
                            placed_object("head", 17)]])[0]

        self.assertEqual([tag for tag, _p in custom_cats.frame_head_layers(frame)],
                         ["headblend_mad"])

    def test_specific_head_pose_outranks_the_blend(self):
        frame = frames_of([[placed_object("headblend_overshoot", 1,
                                          cxform=color_transform(0.8)),
                            placed_object("head_real_wink", 15)]])[0]

        self.assertEqual([tag for tag, _p in custom_cats.frame_head_layers(frame)],
                         ["head_real_wink"])


if __name__ == "__main__":
    unittest.main()
