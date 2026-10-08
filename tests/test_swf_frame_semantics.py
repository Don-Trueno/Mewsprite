"""Regression tests for the frame-rendering flow.

Steps covered:
  1. a frame inherits the objects left over by the previous frame
  2. PlaceObject2 at a known depth only updates that part's transform,
     PlaceObject2 at a new depth adds the part, stacking stays depth-ordered
  3. RemoveObject2 hides the part from that frame on, until it is placed again
  4. tags we cannot handle yet (e.g. PlaceObject3) are skipped and recorded
"""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.catgen import swf_tree as tree
from src.util import parse_swf as swf


class BitWriter:
    def __init__(self):
        self.bits: list[int] = []

    def u(self, value: int, count: int):
        for shift in range(count - 1, -1, -1):
            self.bits.append((value >> shift) & 1)

    def s(self, value: int, count: int):
        if value < 0:
            value += 1 << count
        self.u(value, count)

    def bytes(self) -> bytes:
        out = bytearray()
        for start in range(0, len(self.bits), 8):
            chunk = self.bits[start:start + 8]
            byte = 0
            for bit in chunk:
                byte = (byte << 1) | bit
            out.append(byte << (8 - len(chunk)))
        return bytes(out)


def matrix_bytes(translate=(0.0, 0.0), scale=(1.0, 1.0), rotate=(0.0, 0.0)) -> bytes:
    """Encode a SWF MATRIX exactly the way `SWF.parseMATRIX` reads it."""
    writer = BitWriter()

    has_scale = scale != (1.0, 1.0)
    writer.u(1 if has_scale else 0, 1)
    if has_scale:
        writer.u(16, 5)
        writer.s(int(round(scale[0] * 65536)), 16)
        writer.s(int(round(scale[1] * 65536)), 16)

    has_rotate = rotate != (0.0, 0.0)
    writer.u(1 if has_rotate else 0, 1)
    if has_rotate:
        writer.u(16, 5)
        writer.s(int(round(rotate[0] * 65536)), 16)
        writer.s(int(round(rotate[1] * 65536)), 16)

    writer.u(16, 5)
    writer.s(int(round(translate[0] * 20)), 16)
    writer.s(int(round(translate[1] * 20)), 16)
    return writer.bytes()


def place_object2(depth, character=None, name=None, matrix=None, move=False) -> tuple[int, bytes]:
    flags = 0
    if move:
        flags |= 0b00000001
    if character is not None:
        flags |= 0b00000010
    if matrix is not None:
        flags |= 0b00000100
    if name is not None:
        flags |= 0b00100000

    data = bytes([flags]) + struct.pack("<H", depth)
    if character is not None:
        data += struct.pack("<H", character)
    if matrix is not None:
        data += matrix
    if name is not None:
        data += name.encode("utf-8") + b"\x00"

    return swf.SWF.PLACE_OBJECT2, data


def remove_object2(depth) -> tuple[int, bytes]:
    return swf.SWF.REMOVE_OBJECT2, struct.pack("<H", depth)


def place_object3(depth, character=1) -> tuple[int, bytes]:
    """Minimal PlaceObject3: just enough for the depth field to be readable."""
    return swf.SWF.PLACE_OBJECT3, bytes([0b00000010]) + struct.pack("<H", depth) + struct.pack("<H", character)


def encode_tag(type_: int, data: bytes) -> bytes:
    return struct.pack("<H", (type_ << 6) | len(data)) + data


def show_frame() -> bytes:
    return encode_tag(swf.SWF.SHOW_FRAME, b"")


def make_tag(type_: int, data: bytes) -> swf.SWF.Tag:
    tag = swf.SWF.Tag()
    tag.type = type_
    tag.length = len(data)
    tag.data = data
    return tag


def define_sprite(symbol_id: int, frames: list[list[tuple[int, bytes]]]) -> swf.DefineSprite:
    data = struct.pack("<HH", symbol_id, len(frames))
    for frame in frames:
        for type_, payload in frame:
            data += encode_tag(type_, payload)
        data += show_frame()
    data += encode_tag(0, b"")

    return swf.DefineSprite(make_tag(swf.SWF.DEFINE_SPRITE, data))


def build_tree(sprite: swf.DefineSprite) -> tree.SWF_Tree:
    swf_tree = tree.SWF_Tree({})
    swf_tree.addSprite(sprite)
    return swf_tree


def frames_of(swf_tree: tree.SWF_Tree, sprite_id: int) -> list[tree.Frame]:
    return swf_tree.characterLUT[sprite_id].frames


class FrameInheritanceTests(unittest.TestCase):
    def test_frames_inherit_previous_objects_and_only_update_transforms(self):
        sprite = define_sprite(1, [
            [place_object2(1, character=100, name="body", matrix=matrix_bytes((1.0, 1.0)))],
            [place_object2(1, move=True, matrix=matrix_bytes((2.0, 2.0)))],
            [],
            [place_object2(3, character=101, name="tail", matrix=matrix_bytes((3.0, 3.0)))],
        ])

        frames = frames_of(build_tree(sprite), 1)
        self.assertEqual(len(frames), 4)

        # frame 0: the part is added
        self.assertEqual([obj.name for obj in frames[0].objs], ["body"])
        self.assertAlmostEqual(frames[0].objs[0].xform.xoffset, 1.0)

        # frame 1: same depth -> transform only, identity is preserved
        self.assertEqual([obj.name for obj in frames[1].objs], ["body"])
        self.assertEqual(frames[1].objs[0].id, 100)
        self.assertAlmostEqual(frames[1].objs[0].xform.xoffset, 2.0)

        # frame 2: nothing happens, the object is still there
        self.assertEqual([obj.name for obj in frames[2].objs], ["body"])
        self.assertAlmostEqual(frames[2].objs[0].xform.xoffset, 2.0)

        # frame 3: a new depth adds a part, ordering stays by depth
        self.assertEqual([obj.name for obj in frames[3].objs], ["body", "tail"])
        self.assertEqual([obj.depth for obj in frames[3].objs], [1, 3])

    def test_each_frame_owns_its_own_matrices(self):
        sprite = define_sprite(1, [
            [place_object2(1, character=100, name="body", matrix=matrix_bytes((1.0, 1.0)))],
            [place_object2(1, move=True, matrix=matrix_bytes((5.0, 5.0)))],
        ])

        frames = frames_of(build_tree(sprite), 1)
        self.assertIsNot(frames[0].objs[0].xform, frames[1].objs[0].xform)
        self.assertAlmostEqual(frames[0].objs[0].xform.xoffset, 1.0)
        self.assertAlmostEqual(frames[1].objs[0].xform.xoffset, 5.0)

    def test_remove_object2_hides_the_part_until_it_is_placed_again(self):
        sprite = define_sprite(1, [
            [place_object2(1, character=100, name="body", matrix=matrix_bytes((1.0, 1.0)))],
            [remove_object2(1)],
            [],
            [place_object2(1, character=100, name="body", matrix=matrix_bytes((4.0, 4.0)))],
        ])

        frames = frames_of(build_tree(sprite), 1)

        self.assertEqual([obj.name for obj in frames[0].objs], ["body"])
        self.assertEqual(frames[1].objs, [])
        self.assertEqual(frames[2].objs, [])
        self.assertEqual([obj.name for obj in frames[3].objs], ["body"])
        self.assertAlmostEqual(frames[3].objs[0].xform.xoffset, 4.0)

    def test_remove_object2_only_removes_the_matching_depth(self):
        sprite = define_sprite(1, [
            [place_object2(1, character=100, name="body", matrix=matrix_bytes((1.0, 1.0))),
             place_object2(3, character=101, name="tail", matrix=matrix_bytes((3.0, 3.0)))],
            [remove_object2(1)],
        ])

        frames = frames_of(build_tree(sprite), 1)
        self.assertEqual([obj.name for obj in frames[1].objs], ["tail"])


class UnsupportedTagTests(unittest.TestCase):
    def test_place_object3_is_skipped_and_recorded(self):
        sprite = define_sprite(1, [
            [place_object2(1, character=100, name="body", matrix=matrix_bytes((1.0, 1.0)))],
            [place_object3(5)],
        ])

        frames = frames_of(build_tree(sprite), 1)

        # the part is not added
        self.assertEqual([obj.name for obj in frames[1].objs], ["body"])

        skipped = frames[1].skipped
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["tag"], "UNSUPPORTED:PlaceObject3")
        self.assertEqual(skipped[0]["note"], "skipped")
        self.assertEqual(skipped[0]["depth"], 5)

    def test_skips_are_per_frame(self):
        sprite = define_sprite(1, [
            [place_object3(5)],
            [],
        ])

        frames = frames_of(build_tree(sprite), 1)
        self.assertEqual(len(frames[0].skipped), 1)
        self.assertEqual(frames[1].skipped, [])


if __name__ == "__main__":
    unittest.main()
