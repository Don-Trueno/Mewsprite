"""Weapons and trinkets, which are not part of a cat at all.

A cat's equipment is exactly the three worn armour slots.  A weapon and a
trinket are standalone parts: ``ItemPool`` says which item artwork a slot refers
to, and the animation alone decides whether that slot is drawn, where, and at
how many different depths.  A trinket falls back to
:data:`custom_cats.DEFAULT_TRINKET`; a weapon with no source at all stays empty.

The second character has no handheld slots whatsoever.
"""

import os
import shutil
import sys
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main

from src import custom_cats
from src import items as items_mod
from src.catgen import animations
from src.catgen import catparts as catpart
from src.catgen import palette
from src.catgen import reusable
from src.catgen import swf_tree as tree
from src.util import ffdec_tools as ffdec
from src.util import parse_swf as swf

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FFDEC = main.ffdecDefault


def make_frame(entries):
    """One frame from ``{tag: (x, y, depth)}`` or ``{tag: [(x, y, depth), ...]}``."""
    frame = animations.CatFrame()
    for tag, value in entries.items():
        placements = value if isinstance(value, list) else [value]
        for xoffset, yoffset, depth in placements:
            matrix = swf.Matrix()
            matrix.xoffset = xoffset
            matrix.yoffset = yoffset
            frame.used.setdefault(tag, []).append((matrix, depth))
    return animations.finalizeFrame(frame)


class SlotDefinitionTests(unittest.TestCase):
    def test_equipment_is_exactly_the_three_armour_slots(self):
        self.assertEqual(custom_cats.EQUIP_SLOTS, ("head", "face", "neck"))
        self.assertEqual(len(custom_cats.EQUIP_SLOTS), 3)

    def test_handheld_slots_are_named_separately(self):
        self.assertEqual(custom_cats.HANDHELD_SLOTS, ("weapon", "trinket"))
        self.assertFalse(set(custom_cats.EQUIP_SLOTS)
                         & set(custom_cats.HANDHELD_SLOTS))
        for slot in custom_cats.HANDHELD_SLOTS:
            self.assertIn(slot, items_mod.ANIMATED_ITEM_SLOTS)

    def test_each_handheld_slot_has_its_own_sprite(self):
        self.assertEqual(items_mod.ITEM_SLOT_SYMBOLS["weapon"], ("Weapon", None))
        self.assertEqual(items_mod.ITEM_SLOT_SYMBOLS["trinket"], ("Trinket", None))


class EquipmentVsHandheldTests(unittest.TestCase):
    """The two are asked for, resolved and cached independently."""

    def setUp(self):
        self.cats = {c.id: c for c in custom_cats.getCustomCats()}

    def test_equipment_defaults_never_mention_a_handheld_item(self):
        names = custom_cats.getDefaultEquipNames("ButcherCat")
        self.assertEqual(len(names), 3)
        self.assertEqual(names, (None, "ButcherMask", None))

    def test_handheld_defaults_are_read_separately(self):
        self.assertEqual(custom_cats.getDefaultHandheldNames("ButcherCat"),
                         ("ButcherHook", custom_cats.DEFAULT_TRINKET))

    def test_an_equipment_selection_is_always_three_wide(self):
        for override in ((), ("Hat",), ("Hat", "Face"),
                         ("Hat", "Face", "Neck"),
                         ("Hat", "Face", "Neck", "Sword", "Chicken")):
            names, _explicit = custom_cats.resolve_equipment_names(
                self.cats["ButcherCat"], "custom", override)
            self.assertEqual(len(names), 3, override)
            self.assertEqual(names[:len(override)], tuple(override[:3]))

    def test_medicat_keeps_her_handheld_items(self):
        """Her armour is disabled for GIF export; her trinket is unaffected."""
        names, explicit = custom_cats.resolve_equipment_names(
            self.cats["MedicCat"], "default")

        self.assertEqual(names, (None, None, None))
        self.assertFalse(explicit)
        pool = custom_cats.normalize_handheld(self.cats["MedicCat"])
        self.assertIsNone(pool.item_name("weapon"))
        self.assertEqual(pool.item_name("trinket"), custom_cats.DEFAULT_TRINKET)

    def test_none_disables_the_armour_only(self):
        names, explicit = custom_cats.resolve_equipment_names(
            self.cats["ButcherCat"], "none")

        self.assertEqual(names, (None, None, None))
        self.assertTrue(explicit)
        pool = custom_cats.normalize_handheld(self.cats["ButcherCat"])
        self.assertEqual(pool.item_name("weapon"), "ButcherHook")

    def test_an_item_pool_only_reads_handheld_slots(self):
        pool = custom_cats.ItemPool({"weapon": "Sword", "trinket": "Chicken"})
        self.assertEqual(pool.cache_names(), {"Sword.svg", "Chicken.svg"})

    def test_a_cat_part_name_never_mentions_an_item(self):
        with_weapon = reusable.shape_cache_name(
            "ButcherCat", "head", expression="smile",
            equip=(None, "ButcherMask", None), defaults=(None, "ButcherMask", None))
        self.assertEqual(with_weapon, "ButcherCat-head-smile.svg")


class HandheldPoolTests(unittest.TestCase):
    def setUp(self):
        self.cats = {c.id: c for c in custom_cats.getCustomCats()}

    def test_no_request_uses_the_character_file(self):
        pool = custom_cats.normalize_handheld(self.cats["ButcherCat"], None)
        self.assertEqual(pool.item_name("weapon"), "ButcherHook")
        self.assertEqual(pool.item_name("trinket"), custom_cats.DEFAULT_TRINKET)

    def test_an_explicit_request_wins(self):
        pool = custom_cats.normalize_handheld(
            self.cats["ButcherCat"], ["CaveCatClub", "Chicken"])
        self.assertEqual(pool.item_name("weapon"), "CaveCatClub")

    def test_an_explicit_none_leaves_the_slot_empty(self):
        pool = custom_cats.normalize_handheld(
            self.cats["ButcherCat"], [None, None])
        self.assertTrue(pool.is_empty())

    def test_a_half_request_leaves_the_other_slot_empty(self):
        """Only an absent ``--weapon``/``--trinket`` pair defers to the file."""
        pool = custom_cats.normalize_handheld(self.cats["ButcherCat"], ["Log", None])
        self.assertEqual(pool.item_name("weapon"), "Log")
        self.assertIsNone(pool.item_name("trinket"))

    def test_a_cat_without_a_weapon_gets_none(self):
        """FighterCat's character file names no weapon, only a neck item."""
        pool = custom_cats.normalize_handheld(self.cats["FighterCat"])
        self.assertIsNone(pool.item_name("weapon"))
        self.assertEqual(pool.item_name("trinket"), custom_cats.DEFAULT_TRINKET)

    def test_two_cats_holding_the_same_weapon_share_one_part(self):
        a = custom_cats.ItemPool({"weapon": "ButcherHook"})
        b = custom_cats.ItemPool({"weapon": "ButcherHook"})
        self.assertEqual(a.cache_names(), b.cache_names())
        self.assertEqual(a, b)

    def test_pools_compare_by_content_not_by_identity(self):
        self.assertEqual(custom_cats.ItemPool({"weapon": "Log", "trinket": "Chicken"}),
                         custom_cats.ItemPool({"trinket": "Chicken", "weapon": "Log"}))
        self.assertEqual(hash(custom_cats.ItemPool({"weapon": "Log"})),
                         hash(custom_cats.ItemPool({"weapon": "Log"})))

    def test_the_pool_is_cached_under_the_item_names(self):
        pool = custom_cats.ItemPool({"weapon": "ButcherHook", "trinket": "Chicken"})
        self.assertEqual(pool.cache_names(), {"ButcherHook.svg", "Chicken.svg"})


class HandheldConfirmationTests(unittest.TestCase):
    """The animation metadata, not the pool, decides what is drawn."""

    def setUp(self):
        self.pool = custom_cats.ItemPool({"weapon": "ButcherHook",
                                          "trinket": "Chicken"})

    def test_a_slot_the_animation_never_places_is_dropped(self):
        anim = [make_frame({"head": (0.0, 0.0, 13), "trinket": (0.0, 0.0, 15)})]
        confirmed = self.pool.confirmed_by(anim)

        self.assertEqual(confirmed.item_name("trinket"), "Chicken")
        self.assertIsNone(confirmed.item_name("weapon"))

    def test_an_animation_without_handheld_objects_confirms_nothing(self):
        anim = [make_frame({"head": (0.0, 0.0, 13)})]
        self.assertTrue(self.pool.confirmed_by(anim).is_empty())

    def test_the_frame_metadata_confirms_the_same_way(self):
        anim = [make_frame({"head": (0.0, 0.0, 13), "weapon": (0.0, 0.0, 15)})]
        _tag_pool, frames_info = custom_cats.extract_anim_tag_pool_and_frames_info(anim)

        confirmed = self.pool.confirmed_by_frames(frames_info)
        self.assertEqual(confirmed.item_name("weapon"), "ButcherHook")
        self.assertIsNone(confirmed.item_name("trinket"))


class FrameItemTagTests(unittest.TestCase):
    def test_a_frame_without_the_objects_places_nothing(self):
        frame = make_frame({"head": (0.0, 0.0, 13), "body": (0.0, 0.0, 7)})
        self.assertEqual(custom_cats.getFrameItemTags(frame), {})

    def test_every_placement_of_a_slot_is_kept(self):
        """One slot may be placed several times, at different depths."""
        frame = make_frame({"weapon": [(1.0, 2.0, 15), (3.0, 4.0, 20)]})
        tags = custom_cats.getFrameItemTags(frame)

        self.assertEqual(len(tags["weapon"]), 2)
        self.assertEqual([placement[1] for placement in tags["weapon"]], [15, 20])
        self.assertEqual([placement[0].xoffset for placement in tags["weapon"]], [1.0, 3.0])

    def test_the_placements_come_back_sorted_by_depth(self):
        frame = make_frame({"trinket": [(5.0, 6.0, 30), (7.0, 8.0, 10)]})
        self.assertEqual([placement[1]
                          for placement in custom_cats.getFrameItemTags(frame)["trinket"]],
                         [10, 30])

    def test_the_animation_transform_and_depth_are_kept(self):
        frame = make_frame({"weapon": (59.45, 24.15, 15)})
        matrix, depth, cxform = custom_cats.getFrameItemTags(frame)["weapon"][0]

        self.assertEqual((matrix.xoffset, matrix.yoffset), (59.45, 24.15))
        self.assertEqual(depth, 15)
        self.assertIsNone(cxform, "this frame carries no color transform")


class ItemLayerTests(unittest.TestCase):
    """Every handheld placement becomes an ordinary layer of the frame."""

    def setUp(self):
        self.tmp = os.path.join(REPO_ROOT, f"_test_items_{os.getpid()}_{uuid.uuid4().hex[:8]}")
        os.makedirs(self.tmp, exist_ok=True)
        self._old_shapes = reusable.SHAPES_DIR
        self._old_anims = reusable.ANIMS_DIR
        reusable.SHAPES_DIR = os.path.join(self.tmp, "shapes")
        reusable.ANIMS_DIR = os.path.join(self.tmp, "anims")
        reusable._SHAPE_MEMORY.clear()
        custom_cats._HEAD_POSE_CACHE.clear()

        self.partDir = ffdec.exportShapesIfNeeded(FFDEC, catpart.CATPARTS_SWF)
        self.catTree = tree.getSwfTree(catpart.CATPARTS_SWF)
        self.pool = custom_cats.ItemPool({"weapon": "ButcherHook",
                                          "trinket": "Chicken"})

    def tearDown(self):
        reusable.SHAPES_DIR = self._old_shapes
        reusable.ANIMS_DIR = self._old_anims
        reusable._SHAPE_MEMORY.clear()
        custom_cats._HEAD_POSE_CACHE.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _entries(self, frame):
        return custom_cats._animation_item_plan_entries(
            self.partDir, self.catTree, frame, self.pool)

    def test_the_layer_keeps_the_animation_depth(self):
        frame = make_frame({"weapon": (5.0, 6.0, 15)})
        entries = self._entries(frame)

        self.assertEqual([e["name"] for e in entries], ["Weapon Item"])
        self.assertEqual(entries[0]["depth"], 15)
        self.assertEqual(entries[0]["matrix"].xoffset, 5.0)

    def test_several_depths_become_several_layers(self):
        frame = make_frame({"weapon": [(1.0, 1.0, 15), (2.0, 2.0, 25)]})
        entries = self._entries(frame)

        self.assertEqual(len(entries), 2)
        self.assertEqual([e["depth"] for e in entries], [15, 25])

    def test_a_frame_that_places_nothing_adds_nothing(self):
        frame = make_frame({"head": (0.0, 0.0, 13), "body": (0.0, 0.0, 7)})
        self.assertEqual(self._entries(frame), [])

    def test_a_slot_outside_the_pool_is_not_drawn(self):
        frame = make_frame({"weapon": (0.0, 0.0, 15), "trinket": (0.0, 0.0, 15)})
        pool = custom_cats.ItemPool({"weapon": "ButcherHook"})
        entries = custom_cats._animation_item_plan_entries(
            self.partDir, self.catTree, frame, pool)

        self.assertEqual([e["name"] for e in entries], ["Weapon Item"])

    def test_an_empty_pool_draws_nothing(self):
        frame = make_frame({"weapon": (0.0, 0.0, 15)})
        self.assertEqual(custom_cats._animation_item_plan_entries(
            self.partDir, self.catTree, frame, custom_cats.ItemPool()), [])


class CliParsingTests(unittest.TestCase):
    def test_an_equipment_selection_is_three_slots(self):
        self.assertEqual(main.parse_equipment_override("Hat;Face;Neck"),
                         ("Hat", "Face", "Neck"))

    def test_extra_fields_are_dropped(self):
        self.assertEqual(main.parse_equipment_override("Hat;Face;Neck;Sword;Chicken"),
                         ("Hat", "Face", "Neck"))

    def test_missing_fields_mean_nothing_worn(self):
        self.assertEqual(main.parse_equipment_override("Hat"), ("Hat", None, None))
        self.assertEqual(main.parse_equipment_override(";;"), None)

    def test_an_empty_selection_is_no_selection(self):
        for raw in (None, "", "  "):
            self.assertIsNone(main.parse_equipment_override(raw))

    def test_no_handheld_flags_means_no_request(self):
        self.assertIsNone(main.parse_handheld(None, None))

    def test_the_handheld_flags_are_parsed_on_their_own(self):
        self.assertEqual(main.parse_handheld("Sword", "Chicken"), ["Sword", "Chicken"])
        self.assertEqual(main.parse_handheld("Sword", None), ["Sword", None])

    def test_none_asks_for_an_empty_slot(self):
        self.assertEqual(main.parse_handheld("none", "none"), [None, None])
        self.assertEqual(main.parse_handheld("none", "Chicken"), [None, "Chicken"])

    def test_the_equipment_option_never_carries_a_weapon(self):
        cat_id, mode, override = main.parse_cat_selection(
            ["ButcherCat", "custom", "Hat;Face;Neck;Sword;Chicken"])
        self.assertEqual(mode, "custom")
        self.assertEqual(override, ("Hat", "Face", "Neck"))


class ItemSpriteTests(unittest.TestCase):
    """The handheld artwork is extracted once and cached by name."""

    def setUp(self):
        self.partDir = ffdec.exportShapesIfNeeded(FFDEC, catpart.CATPARTS_SWF)
        self.catTree = tree.getSwfTree(catpart.CATPARTS_SWF)

    def test_the_items_frame_selects_the_sprite_frame(self):
        item = custom_cats.getItem("ButcherHook")
        sprite = items_mod.buildItemSprite(
            self.partDir, self.catTree, "weapon", item)
        self.assertGreater(len(sprite.getImportantComponents()), 0)

    def test_a_trinket_id_is_rejected_in_the_weapon_slot(self):
        item = custom_cats.getItem("Chicken")
        with self.assertRaises(ValueError):
            items_mod.buildItemSprite(
                self.partDir, self.catTree, "weapon", item)

    def test_an_unknown_item_is_reported(self):
        with self.assertRaises(KeyError):
            custom_cats.getItem("NoSuchItem")

    def test_the_cache_file_is_named_after_the_item_alone(self):
        self.assertEqual(items_mod.itemSpriteCacheName("ButcherHook"),
                         "ButcherHook.svg")

    def test_reading_an_item_writes_it_to_reusable_shapes(self):
        """The cache file is what later runs read instead of the SWF."""
        held = os.path.join(REPO_ROOT, "_test_itemcache")
        os.makedirs(held, exist_ok=True)
        old_shapes = reusable.SHAPES_DIR
        reusable.SHAPES_DIR = held
        reusable._SHAPE_CACHE_CURRENT = None
        reusable._SHAPE_MEMORY.clear()
        try:
            loaded = items_mod.getItemSprite("trinket", "Chicken")
            self.assertGreater(len(loaded.getImportantComponents()), 0)
            self.assertTrue(
                os.path.isfile(reusable.shape_cache_path("Chicken.svg")),
                "the item artwork must land in reusable/shapes/Chicken.svg")
        finally:
            reusable.SHAPES_DIR = old_shapes
            reusable._SHAPE_CACHE_CURRENT = None
            reusable._SHAPE_MEMORY.clear()
            shutil.rmtree(held, ignore_errors=True)


class RequiredPartsTests(unittest.TestCase):
    """The handheld artwork joins the set of parts a render needs."""

    def setUp(self):
        self.tmp = os.path.join(REPO_ROOT, f"_test_pool_{os.getpid()}_{uuid.uuid4().hex[:8]}")
        os.makedirs(self.tmp, exist_ok=True)
        self._old_shapes = reusable.SHAPES_DIR
        self._old_anims = reusable.ANIMS_DIR
        reusable.SHAPES_DIR = os.path.join(self.tmp, "shapes")
        reusable.ANIMS_DIR = os.path.join(self.tmp, "anims")
        reusable._SHAPE_MEMORY.clear()
        reusable._SHAPE_CACHE_CURRENT = None

    def tearDown(self):
        reusable.SHAPES_DIR = self._old_shapes
        reusable.ANIMS_DIR = self._old_anims
        reusable._SHAPE_CACHE_CURRENT = None
        reusable._SHAPE_MEMORY.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_item_cache_names_are_required(self):
        frames = [make_frame({"head": (0.0, 0.0, 13), "weapon": (0.0, 0.0, 15)})]
        pool = custom_cats.ItemPool({"weapon": "ButcherHook", "trinket": "Chicken"})

        required = custom_cats._required_shape_names(
            frames, "ButcherCat", None, None, items=pool)

        self.assertIn("ButcherHook.svg", required)
        self.assertIn("Chicken.svg", required)
        self.assertIn("ButcherCat-head.svg", required)

    def test_without_a_pool_no_item_part_is_required(self):
        frames = [make_frame({"head": (0.0, 0.0, 13)})]
        required = custom_cats._required_shape_names(frames, "ButcherCat", None, None)
        self.assertNotIn("ButcherHook.svg", required)

    def test_a_missing_item_part_rejects_the_animation_cache(self):
        frames = [make_frame({"head": (0.0, 0.0, 13), "weapon": (0.0, 0.0, 15)})]
        pool = custom_cats.ItemPool({"weapon": "ButcherHook"})
        tag_pool, frames_info = custom_cats.extract_anim_tag_pool_and_frames_info(frames)
        custom_cats._write_anim_metadata("poolTestF", tag_pool, frames_info,
                                         complete=True, items=pool)

        required = custom_cats._required_shape_names(
            frames, "ButcherCat", None, None, items=pool)
        reusable.mark_shape_cache_current()
        for name in required - {"ButcherHook.svg"}:
            with open(reusable.shape_cache_path(name), "w", encoding="utf-8") as handle:
                handle.write("<svg/>\n")

        cat = {c.id: c for c in custom_cats.getCustomCats()}["ButcherCat"]
        self.assertIsNone(
            custom_cats.load_cached_animation(
                "poolTestF", cat, None, None, None, None, None, items=pool),
            "an animation whose weapon part is missing must fall back to the SWF")

    def test_the_animation_file_confirms_the_items_it_places(self):
        frames = [make_frame({"head": (0.0, 0.0, 13), "weapon": (0.0, 0.0, 15)})]
        pool = custom_cats.ItemPool({"weapon": "ButcherHook", "trinket": "Chicken"})
        tag_pool, frames_info = custom_cats.extract_anim_tag_pool_and_frames_info(frames)

        payload = custom_cats._write_anim_metadata(
            "poolItemsF", tag_pool, frames_info, complete=True, items=pool)

        self.assertEqual(payload["items"], {"weapon": "ButcherHook"})
        self.assertIn("weapon", payload["tag_pool"])

    def test_an_animation_that_places_nothing_records_none(self):
        frames = [make_frame({"head": (0.0, 0.0, 13)})]
        pool = custom_cats.ItemPool({"weapon": "ButcherHook"})
        tag_pool, frames_info = custom_cats.extract_anim_tag_pool_and_frames_info(frames)

        payload = custom_cats._write_anim_metadata(
            "poolNoItemsF", tag_pool, frames_info, complete=True, items=pool)

        self.assertNotIn("items", payload)


if __name__ == "__main__":
    unittest.main()
