"""Tests for the reusable/anims + reusable/shapes caches"""

import json
import os
import shutil
import sys
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.catgen import reusable
from src.catgen import sprite as sprite_mod
from src.util import parse_swf as swf
from src.util import svg_tools

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# `svg_tools.parse_svg` reads files line by line, so every tag needs its own line.
SIMPLE_SVG = (
    '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
    '<svg width="10px" height="10px" xmlns="http://www.w3.org/2000/svg">\n'
    '<g id="part">\n'
    '<path d="M0,0 L10,0 L10,10 Z" fill="#ff0000"/>\n'
    '</g>\n'
    '</svg>\n'
)


def make_sprite(directory: str) -> sprite_mod.Sprite:
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "fixture.svg")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(SIMPLE_SVG)
    return sprite_mod.Sprite(svg_tools.parse_svg(path))


class ShapeCacheNameTests(unittest.TestCase):
    def test_equip_independent_parts_use_cat_and_part_only(self):
        for part in ("body", "tail", "arm1", "arm2", "leg1", "leg2"):
            self.assertEqual(reusable.shape_cache_name("ButcherCat", part),
                             f"ButcherCat-{part}.svg")

    def test_named_examples_from_the_spec(self):
        self.assertEqual(reusable.shape_cache_name("ButcherCat", "tail"),
                         "ButcherCat-tail.svg")
        self.assertEqual(reusable.shape_cache_name("ButcherCat", "head"),
                         "ButcherCat-head.svg")
        self.assertEqual(
            reusable.shape_cache_name("ButcherCat", "head", expression="smile"),
            "ButcherCat-head-smile.svg")
        self.assertEqual(reusable.shape_cache_name("ButcherCat", "character"),
                         "ButcherCat-character.svg")

    def test_default_equipment_has_no_suffix(self):
        self.assertEqual(
            reusable.shape_cache_name("DruidCat", "head", equip=None,
                                      defaults=("Hat", "Face", "Neck")),
            "DruidCat-head.svg")

    def test_explicit_selection_equal_to_the_default_has_no_suffix(self):
        self.assertEqual(
            reusable.shape_cache_name("DruidCat", "head", equip=("Hat", "Face", "Neck"),
                                      defaults=("Hat", "Face", "Neck")),
            "DruidCat-head.svg")

    def test_explicitly_wearing_nothing_is_marked_none(self):
        self.assertEqual(
            reusable.shape_cache_name("DruidCat", "head", equip=(None, None, None),
                                      defaults=("Hat", "Face", "Neck")),
            "DruidCat-head-None.svg")

    def test_equipment_items_follow_cli_order(self):
        # head;face;neck, exactly like the --equip argument.
        self.assertEqual(
            reusable.shape_cache_name("DruidCat", "head",
                                      equip=("Hat", "FaceMask", "Necklace"),
                                      defaults=(None, None, None)),
            "DruidCat-head-Hat-FaceMask-Necklace.svg")

    def test_expression_precedes_equipment(self):
        self.assertEqual(
            reusable.shape_cache_name("DruidCat", "head", expression="smile",
                                      equip=("Hat", None, None),
                                      defaults=(None, None, None)),
            "DruidCat-head-smile-Hat-None-None.svg")

    def test_unknown_part_is_rejected(self):
        with self.assertRaises(ValueError):
            reusable.shape_cache_name("ButcherCat", "claws")


class ShapeCacheRoundTripTests(unittest.TestCase):
    def setUp(self):
        # the sandbox only allows writes into freshly created directories, so use
        # one unique directory per test process instead of the system temp dir.
        self.tmp = os.path.join(REPO_ROOT, f"_test_reusable_{os.getpid()}_{uuid.uuid4().hex[:8]}")
        os.makedirs(self.tmp, exist_ok=True)
        self._old_shapes = reusable.SHAPES_DIR
        self._old_anims = reusable.ANIMS_DIR
        reusable.SHAPES_DIR = os.path.join(self.tmp, "shapes")
        reusable.ANIMS_DIR = os.path.join(self.tmp, "anims")
        reusable._SHAPE_MEMORY.clear()

    def tearDown(self):
        reusable.SHAPES_DIR = self._old_shapes
        reusable.ANIMS_DIR = self._old_anims
        reusable._SHAPE_MEMORY.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_shape_survives_a_save_load_round_trip(self):
        original = make_sprite(self.tmp)
        compiled = original.compile()

        self.assertTrue(reusable.save_shape("ButcherCat-tail.svg", original))
        loaded = reusable.load_shape("ButcherCat-tail.svg")

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.compile(), compiled)

    def test_get_or_build_shape_only_builds_once(self):
        calls = []

        def builder():
            calls.append(1)
            return make_sprite(reusable.SHAPES_DIR)

        first = reusable.get_or_build_shape("ButcherCat-body.svg", builder)
        second = reusable.get_or_build_shape("ButcherCat-body.svg", builder)

        self.assertEqual(len(calls), 1)
        self.assertIsNot(first, second, "callers must get their own copy")
        self.assertEqual(first.compile(), second.compile())

    def test_missing_shape_returns_none(self):
        self.assertIsNone(reusable.load_shape("Nope-missing.svg"))

    def test_composed_sprite_round_trips(self):
        """A merged/transformed sprite must stay readable after the cache write.

        `mergeSprites` synthesises its own `<svg>` root; when that root is not
        newline-separated, `svg_tools.parse_svg` (which reads line by line) fails
        with "SVG tag g has no end tag" and the cache can never be reused.
        """
        part = make_sprite(self.tmp)
        part.applyTransform(swf.Matrix())

        composed = sprite_mod.mergeSprites([part, part])
        composed.applyTransform(swf.Matrix())

        self.assertTrue(reusable.save_shape("Composed-body.svg", composed))
        loaded = reusable.load_shape("Composed-body.svg")

        self.assertIsNotNone(loaded, "a composed sprite must be re-readable")
        self.assertEqual(loaded.compile(), composed.compile())
        self.assertEqual(len(loaded.getImportantComponents()),
                         len(composed.getImportantComponents()))

    def test_corrupt_shape_is_ignored(self):
        os.makedirs(reusable.SHAPES_DIR, exist_ok=True)
        with open(reusable.shape_cache_path("Broken-head.svg"), "w", encoding="utf-8") as handle:
            handle.write("this is not svg\n")
        self.assertIsNone(reusable.load_shape("Broken-head.svg"))

    def test_animation_cache_round_trip(self):
        payload = {
            "anim_name": "megaslapF",
            "metadata_version": reusable.ANIM_CACHE_VERSION,
            "tag_pool": ["head", "body", "other_head"],
            "frames": {
                "0": [{"depth": 1, "tag": "body", "transform": [1, 0, 0, 1, 0, 0]}],
                "1": [{"depth": 5, "tag": "UNSUPPORTED:PlaceObject3",
                       "transform": None, "note": "skipped"}],
            },
        }

        path = reusable.save_anim_cache("megaslapF", payload)
        self.assertIsNotNone(path)
        self.assertTrue(path.endswith(os.path.join("anims", "megaslapF.json")))

        loaded = reusable.load_anim_cache("megaslapF")
        self.assertEqual(loaded, payload)

    def test_stale_metadata_version_is_ignored(self):
        """Metadata from an older pipeline would render without its tints."""
        payload = {
            "anim_name": "staleF",
            "metadata_version": reusable.ANIM_CACHE_VERSION - 1,
            "tag_pool": ["body"],
            "frames": {"0": [{"depth": 1, "tag": "body",
                              "transform": [1, 0, 0, 1, 0, 0]}]},
        }
        reusable.save_anim_cache("staleF", payload)

        self.assertIsNone(reusable.load_anim_cache("staleF"),
                          "an older metadata version must not be reused")

    def test_missing_animation_cache_returns_none(self):
        self.assertIsNone(reusable.load_anim_cache("doesNotExist"))

    def test_malformed_animation_cache_returns_none(self):
        os.makedirs(reusable.ANIMS_DIR, exist_ok=True)
        with open(reusable.anim_cache_path("broken"), "w", encoding="utf-8") as handle:
            json.dump({"tag_pool": []}, handle)
        self.assertIsNone(reusable.load_anim_cache("broken"))


class EquipmentSuffixTests(unittest.TestCase):
    def test_none_equipment_argument_means_default(self):
        self.assertEqual(reusable.equipment_suffix(None, ("A", "B", "C")), "")

    def test_all_empty_is_none_token(self):
        self.assertEqual(reusable.equipment_suffix((None, None, None), ("A", None, None)),
                         "-None")
        self.assertEqual(reusable.equipment_suffix(("", "", ""), ("A", None, None)),
                         "-None")

    def test_empty_slots_use_the_none_token(self):
        self.assertEqual(
            reusable.equipment_suffix(("Hat", None, None), (None, None, None)),
            "-Hat-None-None")


if __name__ == "__main__":
    unittest.main()
