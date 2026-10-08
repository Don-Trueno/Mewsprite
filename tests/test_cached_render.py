"""The reusable animation cache must be a faithful stand-in for the SWF data.

When the animation metadata and every needed cat part are cached, the
source SWFs must not be read at all -- so the rebuilt frames have to match the
parsed ones exactly, or the cached render would drift from the SWF.
"""

import os
import shutil
import sys
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.catgen import animations as anim_mod
from src.catgen import animations
from src.catgen import reusable
from src.util import parse_swf as swf
from src import custom_cats

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make_frame(entries, skipped=()):
    frame = animations.CatFrame()
    for tag, (xoffset, yoffset, depth) in entries.items():
        matrix = swf.Matrix()
        matrix.xoffset = xoffset
        matrix.yoffset = yoffset
        frame.used.setdefault(tag, []).append((matrix, depth))
    frame.skipped = list(skipped)
    return animations.finalizeFrame(frame)


def matrix_fields(value):
    matrix, depth = value
    return (round(matrix.xscale, 6), round(matrix.skew1, 6), round(matrix.skew2, 6),
            round(matrix.yscale, 6), round(matrix.xoffset, 6), round(matrix.yoffset, 6), depth)


class FrameCacheRoundTripTests(unittest.TestCase):
    def test_rebuilt_frames_match_the_written_metadata(self):
        anim = [
            make_frame({"body": (1.0, 2.0, 7), "head_smile": (3.0, 4.0, 13)}),
            make_frame({"body": (5.0, 6.0, 7), "head_smile": (7.0, 8.0, 13),
                        "other_head": (9.0, 10.0, 27)}),
            make_frame({"body": (11.0, 12.0, 7)},
                       skipped=[{"tag": "UNSUPPORTED:PlaceObject3", "note": "skipped", "depth": 42}]),
        ]

        tag_pool, frames_info = custom_cats.extract_anim_tag_pool_and_frames_info(anim)
        payload = {"anim_name": "unitTestF", "tag_pool": tag_pool, "frames": {
            str(i): [{"depth": d, "tag": t,
                      **({"transform": None, "note": "skipped"} if m is None
                         else {"transform": list(m)})}
                     for d, t, m in frame]
            for i, frame in enumerate(frames_info)
        }}

        rebuilt = animations.framesFromAnimCache(payload)

        self.assertEqual(len(rebuilt), len(anim))
        for index, (original, restored) in enumerate(zip(anim, rebuilt)):
            self.assertEqual(set(original.used), set(restored.used), f"frame {index}")
            for tag in original.used:
                self.assertEqual(
                    [matrix_fields(v) for v in original.used[tag]],
                    [matrix_fields(v) for v in restored.used[tag]],
                    f"frame {index} tag {tag}")
            self.assertEqual(original.face, restored.face)
            self.assertEqual(set(original.extra), set(restored.extra))
            for tag in original.extra:
                self.assertEqual(matrix_fields(original.extra[tag]),
                                 matrix_fields(restored.extra[tag]))
            self.assertEqual([item["tag"] for item in original.skipped],
                             [item["tag"] for item in restored.skipped])
            self.assertEqual([item["depth"] for item in original.skipped],
                             [item["depth"] for item in restored.skipped])
            self.assertEqual(original.head[1], restored.head[1])


class CompleteCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.join(REPO_ROOT, f"_test_cachedrender_{os.getpid()}_{uuid.uuid4().hex[:8]}")
        os.makedirs(self.tmp, exist_ok=True)
        self._old_shapes = reusable.SHAPES_DIR
        self._old_anims = reusable.ANIMS_DIR
        reusable.SHAPES_DIR = os.path.join(self.tmp, "shapes")
        reusable.ANIMS_DIR = os.path.join(self.tmp, "anims")
        reusable._SHAPE_MEMORY.clear()

        self.cat = {c.id: c for c in custom_cats.getCustomCats()}["ButcherCat"]

    def tearDown(self):
        reusable.SHAPES_DIR = self._old_shapes
        reusable.ANIMS_DIR = self._old_anims
        reusable._SHAPE_MEMORY.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_animation(self, anim_name, frames, complete=True, overlay_mode=None):
        tag_pool, frames_info = custom_cats.extract_anim_tag_pool_and_frames_info(frames)
        payload = {
            "anim_name": anim_name,
            "overlay_mode": overlay_mode,
            "complete": bool(complete),
            "tag_pool": tag_pool,
            "frames": {
                str(i): [{"depth": d, "tag": t,
                          **({"transform": None, "note": "skipped"} if m is None else {"transform": list(m)})}
                         for d, t, m in frame]
                for i, frame in enumerate(frames_info)},
        }
        reusable.save_anim_cache(anim_name, payload)
        return payload

    def _touch_shapes(self, names):
        os.makedirs(reusable.SHAPES_DIR, exist_ok=True)
        # pretend these parts were produced by the current pipeline version
        reusable.mark_shape_cache_current()
        for name in names:
            with open(reusable.shape_cache_path(name), "w", encoding="utf-8") as handle:
                handle.write("<svg/>\n")

    def test_missing_part_rejects_the_cache(self):
        frames = [make_frame({"body": (0.0, 0.0, 7), "head": (0.0, 0.0, 13)})]
        self._write_animation("idleF", frames)

        result = custom_cats.load_cached_animation(
            "idleF", self.cat, None, None, (None, None, None), None, (None, None, None))

        self.assertIsNone(result, "an incomplete shape cache must fall back to the SWF")

    def test_incomplete_metadata_is_rejected(self):
        frames = [make_frame({"body": (0.0, 0.0, 7), "head": (0.0, 0.0, 13)})]
        self._write_animation("idleF", frames, complete=False)
        self._touch_shapes(custom_cats._required_shape_names(frames, self.cat.id, None, (None, None, None)))

        self.assertIsNone(custom_cats.load_cached_animation(
            "idleF", self.cat, None, None, (None, None, None), None, (None, None, None)),
            "a metadata file that does not describe the whole animation must not be used")

    def test_complete_cache_is_accepted(self):
        frames = [make_frame({"body": (0.0, 0.0, 7), "head": (0.0, 0.0, 13)})]
        self._write_animation("idleF", frames)

        required = custom_cats._required_shape_names(frames, self.cat.id, None, (None, None, None))
        self._touch_shapes(required)

        result = custom_cats.load_cached_animation(
            "idleF", self.cat, None, None, (None, None, None), None, (None, None, None))

        self.assertIsNotNone(result)
        anim_name, loaded_frames, anims = result
        self.assertEqual(anim_name, "idleF")
        self.assertEqual(len(loaded_frames), 1)
        self.assertIn("idleF", anims)

    def test_second_cat_animation_needs_the_second_cat_and_its_parts(self):
        frames = [make_frame({"body": (0.0, 0.0, 7), "head": (0.0, 0.0, 13),
                              "other_head": (1.0, 1.0, 27)})]
        self._write_animation("punchF", frames)

        required = custom_cats._required_shape_names(frames, self.cat.id, None, (None, None, None))
        self._touch_shapes(required)

        # Without a second cat the cache cannot be used, because the overlay part
        # artwork has not been verified yet.
        self.assertIsNone(custom_cats.load_cached_animation(
            "punchF", self.cat, None, None, (None, None, None), None, (None, None, None)))

        cat2 = {c.id: c for c in custom_cats.getCustomCats()}["ThiefCat"]
        self.assertIsNone(custom_cats.load_cached_animation(
            "punchF", self.cat, cat2, None, (None, None, None), None, (None, None, None)),
            "cat2's own parts are still missing")

        self._touch_shapes(custom_cats._required_shape_names(frames, cat2.id, None, (None, None, None)))

        result = custom_cats.load_cached_animation(
            "punchF", self.cat, cat2, None, (None, None, None), None, (None, None, None))
        self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
