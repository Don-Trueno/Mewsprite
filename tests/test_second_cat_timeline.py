"""Regression tests for the second-cat (character / other_) frame timeline.

Step 2/3: a part that is placed on frame N must appear from frame N on,
so the per-frame plan has to keep one slot per animation frame.  The previous
implementation compacted the frames that contained `other_*` tags into a dense
list, which pulled the whole second cat earlier by the number of leading frames
without it.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.catgen import animations
from src.util import parse_swf as swf
from src import custom_cats


SECOND_CAT_PART_KEYS = ("head", "body", "tail", "arm1", "arm2", "leg1", "leg2")


def make_frame(entries: dict[str, tuple[float, float, int]]) -> animations.CatFrame:
    """Build a CatFrame whose `used`/`extra` maps mirror the SWF tree output.

    `catFrameFromObjs` puts every name it does not know into `extra`, which is
    where the second-cat `other_*` parts end up.
    """
    frame = animations.CatFrame()
    for tag_name, (xoffset, yoffset, depth) in entries.items():
        matrix = swf.Matrix()
        matrix.xoffset = xoffset
        matrix.yoffset = yoffset
        frame.used.setdefault(tag_name, []).append((matrix, depth))

        part_name = tag_name.removeprefix("other_")
        is_known = (tag_name in ("body", "arm1", "arm2", "leg1", "leg2", "tail")
                    or tag_name == "head" or tag_name.startswith("head_"))
        if not is_known:
            frame.extra[tag_name] = (matrix, depth)

    return frame


def first_cat_frame(xoffset: float) -> animations.CatFrame:
    return make_frame({
        "body": (xoffset, 0.0, 7),
        "head": (xoffset, 0.0, 13),
    })


def second_cat_entries(base: float) -> dict[str, tuple[float, float, int]]:
    return {
        "other_body": (base, 0.0, 21),
        "other_head": (base, 0.0, 27),
    }


class SecondCatTimelineTests(unittest.TestCase):
    def setUp(self):
        # three frames of solo cat, then the second cat joins on frame 3
        self.anim = [first_cat_frame(1.0), first_cat_frame(2.0),
                     first_cat_frame(3.0)]
        self.anim.append(make_frame({
            "body": (4.0, 0.0, 7),
            "head": (4.0, 0.0, 13),
            **second_cat_entries(9.0),
        }))

    def test_plan_keeps_one_slot_per_animation_frame(self):
        mode, payload = custom_cats._second_cat_overlay_plan(self.anim)

        self.assertEqual(mode, "parts")
        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), len(self.anim),
                         "the per-frame plan must stay aligned with the animation")

    def test_second_cat_starts_on_the_frame_that_places_it(self):
        _mode, payload = custom_cats._second_cat_overlay_plan(self.anim)

        for index in range(3):
            self.assertEqual(payload[index], {},
                             f"frame {index} must not contain the second cat yet")

        self.assertEqual(sorted(payload[3]), ["other_body", "other_head"])
        self.assertEqual(payload[3]["other_head"][1], 27)

    def test_tag_metadata_reports_the_same_first_frame(self):
        _tag_pool, frames_info = custom_cats.extract_anim_tag_pool_and_frames_info(self.anim)

        self.assertEqual(len(frames_info), len(self.anim))
        first_other = next(
            (i for i, frame in enumerate(frames_info)
             if any(tag.startswith("other_") for _depth, tag, _matrix, _cx in frame)),
            None,
        )
        self.assertEqual(first_other, 3)

    def test_second_cat_parts_helper_is_frame_aligned(self):
        parts = custom_cats._second_character_parts(self.anim)
        self.assertEqual(len(parts), len(self.anim))
        self.assertEqual(parts[:3], [{}, {}, {}])
        self.assertTrue(parts[3])

    def test_no_second_cat_yields_no_mode(self):
        mode, payload = custom_cats._second_cat_overlay_plan([first_cat_frame(1.0)])
        self.assertIsNone(mode)
        self.assertIsNone(payload)


class SkippedTagMetadataTests(unittest.TestCase):
    def test_skipped_tags_are_written_into_the_frame_metadata(self):
        frame = animations.CatFrame()
        matrix = swf.Matrix()
        frame.used["body"] = [(matrix, 7)]
        frame.skipped = [{"tag": "UNSUPPORTED:PlaceObject3", "type": 70,
                          "note": "skipped", "depth": 5}]

        tag_pool, frames_info = custom_cats.extract_anim_tag_pool_and_frames_info([frame])

        self.assertEqual(tag_pool, ["body"])
        self.assertNotIn("UNSUPPORTED:PlaceObject3", tag_pool,
                         "a skipped tag is not a renderable part")

        entry = next(item for item in frames_info[0] if item[1].startswith("UNSUPPORTED:"))
        self.assertEqual(entry[0], 5)
        self.assertIsNone(entry[2])


class SecondCatResolverTests(unittest.TestCase):
    """Batch mode must ask for the second cat once and then reuse the answer."""

    def setUp(self):
        self.catList = custom_cats.getCustomCats()
        self._original = custom_cats.prompt_first_cat
        self.calls = []

        def counting(catList, catId=None, allowPrompt=True):
            self.calls.append(catId)
            return self._original(catList, catId, allowPrompt=allowPrompt)

        custom_cats.prompt_first_cat = counting

    def tearDown(self):
        custom_cats.prompt_first_cat = self._original

    def test_answer_is_resolved_once_and_reused(self):
        resolver = custom_cats.SecondCatResolver(self.catList, "ThiefCat", "default", None)

        first = resolver.resolve()
        second = resolver.resolve()
        third = resolver.resolve()

        self.assertIsNotNone(first)
        self.assertIs(first, second)
        self.assertIs(first, third)
        self.assertEqual(len(self.calls), 1, "the second cat must only be resolved once")

        assert first is not None
        cat2, names, explicit, defaults = first
        self.assertEqual(cat2.id, "ThiefCat")
        self.assertFalse(explicit)
        # an equipment selection is always exactly the three armour slots
        self.assertEqual(len(names), len(custom_cats.EQUIP_SLOTS))
        self.assertEqual(len(defaults), len(custom_cats.EQUIP_SLOTS))

    def test_explicit_equipment_is_reported(self):
        resolver = custom_cats.SecondCatResolver(self.catList, "ThiefCat", "custom", ("Hat", None, None))
        resolved = resolver.resolve()
        self.assertIsNotNone(resolved)

        assert resolved is not None
        cat2, names, explicit, _defaults = resolved

        self.assertEqual(cat2.id, "ThiefCat")
        self.assertTrue(explicit)
        # the three armour slots are filled; a weapon or a trinket has no place
        # in the list at all
        self.assertEqual(names, ("Hat", None, None))

    def test_unknown_id_is_reported_without_prompting(self):
        resolver = custom_cats.SecondCatResolver(self.catList, "NoSuchCat", "default", None)

        self.assertIsNone(resolver.resolve())
        self.assertEqual(self.calls, ["NoSuchCat"])


if __name__ == "__main__":
    unittest.main()
