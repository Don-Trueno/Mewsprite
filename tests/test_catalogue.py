"""The name lists under `reusable/`.

Each list is written once, the first time it is missing, so the ids the CLI takes
are readable without digging through the SWFs or the ``.gon`` tables.  An existing
file is never touched -- a trimmed or hand-edited list has to survive -- which also
keeps the expensive producers (listing the animations parses both SWFs) from
running on a checkout that already has the list.
"""

import os
import shutil
import sys
import unittest
import uuid
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.catgen import catalogue
from src import items as items_mod

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: the seven files the feature has to produce
EXPECTED_FILES = (
    "cat-id.txt",
    "anims.txt",
    "head-items.txt",
    "face-items.txt",
    "neck-items.txt",
    "weapon-items.txt",
    "trinket-items.txt",
)


def read_names(path):
    with open(path, encoding="utf-8") as handle:
        return [line.rstrip("\n") for line in handle if line.strip()]


class NameListWritingTests(unittest.TestCase):
    """The plumbing: which files, in which format, and when."""

    def setUp(self):
        self.tmp = os.path.join(REPO_ROOT, f"_test_catalogue_{os.getpid()}_{uuid.uuid4().hex[:8]}")
        os.makedirs(self.tmp, exist_ok=True)
        self._old_dir = catalogue.NAME_LISTS_DIR
        catalogue.NAME_LISTS_DIR = self.tmp
        self.calls = []

    def tearDown(self):
        catalogue.NAME_LISTS_DIR = self._old_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _stub_lists(self, names=(("a.txt", ["x", "y"]), ("b.txt", ["z"]))):
        def produce(label):
            def producer():
                self.calls.append(label)
                return ["x", "y"] if label == "a.txt" else ["z"]
            return producer

        return [(fileName, produce(fileName)) for fileName, _ in names]

    def test_one_name_per_line(self):
        with mock.patch.object(catalogue, "_name_lists", self._stub_lists):
            catalogue.ensure_name_lists()

        self.assertEqual(read_names(os.path.join(self.tmp, "a.txt")), ["x", "y"])
        self.assertEqual(read_names(os.path.join(self.tmp, "b.txt")), ["z"])

    def test_files_end_with_a_newline_and_use_lf(self):
        with mock.patch.object(catalogue, "_name_lists", self._stub_lists):
            catalogue.ensure_name_lists()

        with open(os.path.join(self.tmp, "a.txt"), "rb") as handle:
            raw = handle.read()
        self.assertEqual(raw, b"x\ny\n")

    def test_a_missing_file_is_written(self):
        with mock.patch.object(catalogue, "_name_lists", self._stub_lists):
            written = catalogue.ensure_name_lists()

        self.assertEqual([os.path.basename(path) for path in written], ["a.txt", "b.txt"])

    def test_comment_lines_are_written_verbatim(self):
        """`anims.txt` is the one list with comments, so they must pass through."""
        with mock.patch.object(catalogue, "_name_lists",
                               lambda: [("anims.txt", lambda: ["// x.swf", "aF"])]):
            catalogue.ensure_name_lists()

        with open(os.path.join(self.tmp, "anims.txt"), "rb") as handle:
            self.assertEqual(handle.read(), b"// x.swf\naF\n")

    def test_an_existing_file_is_left_alone(self):
        path = os.path.join(self.tmp, "a.txt")
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("mine\n")

        with mock.patch.object(catalogue, "_name_lists", self._stub_lists):
            written = catalogue.ensure_name_lists()

        self.assertEqual(read_names(path), ["mine"], "an existing list was overwritten")
        self.assertEqual([os.path.basename(p) for p in written], ["b.txt"])

    def test_the_producer_only_runs_for_a_missing_file(self):
        path = os.path.join(self.tmp, "a.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("mine\n")

        with mock.patch.object(catalogue, "_name_lists", self._stub_lists):
            catalogue.ensure_name_lists()

        self.assertEqual(self.calls, ["b.txt"],
                         "the producer of an existing list must not run")

    def test_a_nested_directory_is_created(self):
        nested = os.path.join(self.tmp, "inner")
        catalogue.NAME_LISTS_DIR = nested

        with mock.patch.object(catalogue, "_name_lists", self._stub_lists):
            catalogue.ensure_name_lists()

        self.assertTrue(os.path.isfile(os.path.join(nested, "a.txt")))

    def test_the_shipped_lists_are_the_expected_seven(self):
        self.assertEqual(tuple(name for name, _ in catalogue._name_lists()), EXPECTED_FILES)


class NameListContentTests(unittest.TestCase):
    """The producers themselves: what ends up in each file."""

    def test_cat_ids_are_the_custom_cats(self):
        from src import custom_cats

        expected = sorted(cat.id for cat in custom_cats.getCustomCats())

        self.assertEqual(catalogue.catIds(), expected)
        self.assertTrue(expected)

    def test_anim_names_are_the_sorted_keys(self):
        with mock.patch.object(catalogue.animations, "getCatAnims",
                               return_value={"bF": [], "aF": []}):
            self.assertEqual(catalogue.animNames(), ["aF", "bF"])

    def test_anims_txt_groups_the_names_by_source_file(self):
        # `getCatAnimSources` hands its groups over already sorted
        sources = [("./data/swfs/catanis.swf", ["aF", "bF"]),
                   ("./data/swfs/catanis2.swf", ["cF"]),
                   ("./data/swfs/2d_catanis.swf", ["angryIdle"])]

        with mock.patch.object(catalogue.animations, "getCatAnimSources",
                               return_value=sources):
            lines = catalogue.animLines()

        self.assertEqual(lines, [
            "// catanis.swf", "aF", "bF",
            "// catanis2.swf", "cF",
            "// 2d_catanis.swf", "angryIdle",
        ])

    def test_every_group_starts_with_a_comment_and_has_names(self):
        sources = [("./d/x.swf", ["one"]), ("./d/y.swf", ["two"])]

        with mock.patch.object(catalogue.animations, "getCatAnimSources",
                               return_value=sources):
            lines = catalogue.animLines()

        comments = [line for line in lines if line.startswith(catalogue.COMMENT_PREFIX)]
        self.assertEqual(comments, ["// x.swf", "// y.swf"])
        self.assertEqual([line for line in lines
                          if not line.startswith(catalogue.COMMENT_PREFIX)],
                         ["one", "two"])
        for index, line in enumerate(lines):
            if line.startswith(catalogue.COMMENT_PREFIX):
                self.assertLess(index + 1, len(lines),
                                "a group comment must be followed by its names")

    def test_a_group_without_names_is_still_labelled(self):
        """A SWF that is present but empty should not vanish from the file."""
        with mock.patch.object(catalogue.animations, "getCatAnimSources",
                               return_value=[("./d/empty.swf", [])]):
            self.assertEqual(catalogue.animLines(), ["// empty.swf"])

    def test_every_item_list_matches_its_kind(self):
        table = items_mod.getItemDict()

        for slot in catalogue.ITEM_SLOTS:
            names = catalogue.itemNames(slot)

            self.assertTrue(names, f"{slot} list is empty")
            self.assertEqual(names, sorted(names), f"{slot} list is not sorted")
            self.assertEqual(len(names), len(set(names)), f"{slot} list has duplicates")
            for name in names:
                self.assertEqual(table[name].kind, slot,
                                 f"'{name}' is not a {slot} item")

    def test_variants_are_left_out(self):
        """A `variant_of` entry has no kind or frame, so it cannot be worn."""
        table = items_mod.getItemDict()
        variants = {name for name, item in table.items() if item.variant is not None}
        self.assertTrue(variants, "the item table is expected to hold variants")

        for slot in catalogue.ITEM_SLOTS:
            self.assertEqual(variants & set(catalogue.itemNames(slot)), set(),
                             f"{slot} list contains variants")

    def test_every_item_belongs_to_exactly_one_list(self):
        table = items_mod.getItemDict()
        wearable = {name for name, item in table.items() if item.variant is None}
        listed: set[str] = set()

        for slot in catalogue.ITEM_SLOTS:
            names = set(catalogue.itemNames(slot))
            self.assertEqual(listed & names, set(), f"an item is listed twice ({slot})")
            listed |= names

        self.assertEqual(listed, wearable)


if __name__ == "__main__":
    unittest.main()
