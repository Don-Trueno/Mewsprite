# this file does *magic* :)

from .catgen import catparts as catpart
from .catgen import swf_tree as swf
from .catgen import sprite
from .catgen import animations
from .catgen import palette
from .catgen import reusable
from import_paths import *

from .util import parse_gon as gon
from .util import ffdec_tools as ffdec
from .util import svg_tools as svg

from . import items

import copy
import io
import os
import shutil
import logging
from typing import Any

from PIL import Image as PILImage
from wand.image import Image
from wand.color import Color

logging.getLogger("PIL").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

BATCH_CAT_NAMES = ["Pebbles", "TankCat", "FighterCat", "MageCat", "HunterCat",
                   "MedicCat", "ThiefCat", "NecroCat", "ButcherCat", "JesterCat",
                   "TinkererCat", "DruidCat", "MonkCat", "PsychicCat", "TrailerCat",
                   "TerminatorCat", "Terminator2Cat", "Dclaude"]

#: half-size of the window used to measure how far a frame's artwork reaches;
#: it doubles automatically when a frame touches the border.
FRAME_BOUNDS_WINDOW = 512.0
FRAME_BOUNDS_MAX_WINDOW = 8192.0

#: ImageMagick maps an SVG `width="Npx"` to N * dpi / 96 raster pixels, so the
#: probes have to be rendered at 96 dpi for 1 user unit to be 1 pixel.
MEASURE_DPI = 96.0

#: a pixel counts towards the artwork extent only above this alpha (0-255)
BOUNDS_ALPHA_THRESHOLD = 128

#: how far (in user units) a nearly transparent pixel may sit from the solid core
#: and still count as an antialiased edge rather than a rendering artefact
BOUNDS_HALO = 4.0

#: delay of every exported GIF frame; ImageMagick counted this in 1/100 s, so
#: 2 ticks == 20 ms == one 50 fps frame.
GIF_FRAME_DURATION_MS = 20

_FACE_POSE_CACHE: dict[str, dict[str, Any]] | None = None
_HEAD_FACE_CACHE: dict[tuple[Any, ...], Any] = {}
_HEAD_POSE_CACHE: dict[tuple[Any, ...], sprite.Sprite] = {}
_COMPONENT_CACHE: dict[tuple[Any, ...], sprite.Sprite] = {}
_CHARACTER_CACHE: dict[str, sprite.Sprite] = {}

# Type
FloatMatrix = tuple[float, float, float, float, float, float]
EquipNames = tuple[str | None, str | None, str | None]


def getCatTree(catTree: swf.SWF_Tree, name: str):
    node = catTree.get(name)
    if isinstance(node, swf.SWF_Tree.SpriteNode):
        return node
    else:
        raise TypeError(
            f"'{name}' is not a SpriteNode, got '{type(node).__name__}'")


def _load_face_poses() -> dict[str, dict[str, Any]]:
    global _FACE_POSE_CACHE
    if _FACE_POSE_CACHE is not None:
        return _FACE_POSE_CACHE

    face_data = gon.parse_gon(CATGEN_GON).get("faces", {})
    if not isinstance(face_data, dict):
        face_data = {}

    cleaned: dict[str, dict[str, Any]] = {}
    for name, pose in face_data.items():
        if isinstance(pose, dict):
            cleaned[str(name)] = dict(pose)
        else:
            cleaned[str(name)] = {}

    _FACE_POSE_CACHE = cleaned
    return _FACE_POSE_CACHE


def _pose_match_candidates(face_name: str | None) -> list[str]:
    poses = _load_face_poses()
    if not face_name:
        return ["default"] if "default" in poses else []

    normalized = face_name.lower().replace("head_", "").replace("-", "_")

    exact_matches = [name for name in poses if name.lower() == normalized]
    if exact_matches:
        return sorted(exact_matches, key=lambda name: (len(name), name.count("_")), reverse=True)

    matched = []
    for pose_name in poses:
        key = pose_name.lower()
        if key == "default":
            continue
        if key in normalized or normalized in key:
            matched.append(pose_name)

    if not matched:
        return ["default"] if "default" in poses else []

    return sorted(matched, key=lambda name: (len(name), name.count("_")), reverse=True)


def resolve_face_pose(face_name: str | None, extra: dict[str, Any] | None = None) -> "FacePose":
    poses = _load_face_poses()
    combined: dict[str, Any] = dict(poses.get("default", {}))
    seen_face_offset = False
    seen_back = False

    for pose_name in _pose_match_candidates(face_name):
        pose = poses.get(pose_name, {})
        if not isinstance(pose, dict):
            continue

        for key, value in pose.items():
            if key == "face_offset" and seen_face_offset:
                continue
            if key == "back" and seen_back:
                continue

            combined[key] = value
            if key == "face_offset":
                seen_face_offset = True
            elif key == "back":
                seen_back = True

    if extra:
        for key, value in extra.items():
            if key == "face_offset" and seen_face_offset:
                continue
            if key == "back" and seen_back:
                continue
            combined[key] = value
            if key == "face_offset":
                seen_face_offset = True
            elif key == "back":
                seen_back = True

    return FacePose(combined)


class CustomCat:
    class Part:
        frame: int
        texture: int | None

        def __init__(self, defaultTex: int, defaultFrame: int, data=None):
            if (data == None):
                self.texture = defaultTex
                self.frame = defaultFrame - 1
                return

            if (isinstance(data, str) or isinstance(data, int)):
                self.frame = int(data) - 1
                self.texture = defaultTex
            else:
                self.frame = int(data.setdefault("frame", defaultFrame)) - 1
                self.texture = data.setdefault("texture", defaultTex)

    id: str

    default_frame = 1

    texture = 1
    palette = 1

    body: Part
    tail: Part

    leg1: Part
    leg2: Part
    arm1: Part
    arm2: Part
    claws: Part

    head: Part
    lefteye: Part
    righteye: Part
    lefteyebrow: Part
    righteyebrow: Part
    leftear: Part
    rightear: Part
    mouth: Part

    def __init__(self, name: str, gondata):
        self.id = name

        self.default_frame = int(gondata.setdefault(
            "default_frame", self.default_frame))

        self.texture = int(gondata.setdefault("texture", self.texture)) - 1
        self.palette = int(gondata.setdefault("palette", self.palette))

        self.body = CustomCat.Part(
            self.texture, self.default_frame, gondata.setdefault("body", None))
        self.tail = CustomCat.Part(
            self.texture, self.default_frame, gondata.setdefault("tail", None))

        self.leg1 = CustomCat.Part(
            self.texture, self.default_frame, gondata.setdefault("leg1", None))
        self.leg2 = CustomCat.Part(
            self.texture, self.default_frame, gondata.setdefault("leg2", None))
        self.arm1 = CustomCat.Part(
            self.texture, self.default_frame, gondata.setdefault("arm1", None))
        self.arm2 = CustomCat.Part(
            self.texture, self.default_frame, gondata.setdefault("arm2", None))
        self.claws = CustomCat.Part(
            self.texture, self.default_frame, gondata.setdefault("claws", None))

        self.head = CustomCat.Part(
            self.texture, self.default_frame, gondata.setdefault("head", None))
        self.lefteye = CustomCat.Part(
            self.texture, self.default_frame, gondata.setdefault("lefteye", None))
        self.righteye = CustomCat.Part(
            self.texture, self.default_frame, gondata.setdefault("righteye", None))
        self.lefteyebrow = CustomCat.Part(
            self.texture, self.default_frame, gondata.setdefault("lefteyebrow", None))
        self.righteyebrow = CustomCat.Part(
            self.texture, self.default_frame, gondata.setdefault("righteyebrow", None))
        self.leftear = CustomCat.Part(
            self.texture, self.default_frame, gondata.setdefault("leftear", None))
        self.rightear = CustomCat.Part(
            self.texture, self.default_frame, gondata.setdefault("rightear", None))
        self.mouth = CustomCat.Part(
            self.texture, self.default_frame, gondata.setdefault("mouth", None))


class FacePose:
    browUp: tuple[float, float]
    browRot: tuple[float, float]
    earRot: tuple[float, float]
    mouth: str
    eyes: tuple[str, str]
    offset: tuple[float, float]
    back: bool

    @staticmethod
    def _as_pair(value: Any, default: Any = 0) -> tuple[Any, Any]:
        if isinstance(value, dict):
            items = [value[i]
                     for i in sorted(value.keys(), key=lambda k: int(k))]
            if len(items) == 2:
                return (items[0], items[1])
            if len(items) == 1:
                return (items[0], items[0])
            value = default

        if isinstance(value, (list, tuple)):
            if len(value) == 2:
                return (value[0], value[1])
            if len(value) == 1:
                return (value[0], value[0])
            value = default

        return (value, value)

    def __init__(self, gondata: dict[str, Any]):
        ebu = gondata.setdefault("eyebrow_up", 15)
        brow_left, brow_right = self._as_pair(ebu)
        self.browUp = (float(brow_left), float(brow_right))

        ebr = gondata.setdefault("eyebrow_rotation", 0)
        rot_left, rot_right = self._as_pair(ebr)
        self.browRot = (float(rot_left), float(rot_right))

        earr = gondata.setdefault("ear_rotation", 0)
        ear_left, ear_right = self._as_pair(earr)
        self.earRot = (float(ear_left), float(ear_right))

        self.mouth = gondata.setdefault("mouth", "closed")
        eyes = gondata.setdefault("eyes", "open")
        eye_left, eye_right = self._as_pair(eyes)
        self.eyes = (str(eye_left), str(eye_right))

        offset = gondata.setdefault("face_offset", [10, 0])
        off_x, off_y = self._as_pair(offset)
        self.offset = (float(off_x), float(off_y))

        self.back = gondata.setdefault("back", False)


class CatEquipment:
    head_front: sprite.Sprite | None
    head_back: sprite.Sprite | None

    face_front: sprite.Sprite | None
    face_back: sprite.Sprite | None

    neck_front: sprite.Sprite | None
    neck_back: sprite.Sprite | None

    def __init__(self):
        self.head_front = None
        self.head_back = None

        self.face_front = None
        self.face_back = None

        self.neck_back = None
        self.neck_front = None


class CatFace:
    lbrow: sprite.Sprite | None
    rbrow: sprite.Sprite | None

    lear: sprite.Sprite | None
    rear: sprite.Sprite | None

    leye_open: sprite.Sprite | None
    leye_closed: sprite.Sprite | None

    reye_open: sprite.Sprite | None
    reye_closed: sprite.Sprite | None

    mouth_open: sprite.Sprite | None
    mouth_closed: sprite.Sprite | None
    mouth_smile: sprite.Sprite | None

    headItemXForm: swf.swf.Matrix
    neckItemXForm: swf.swf.Matrix
    faceItemXForm: swf.swf.Matrix

    def __init__(self):
        self.lbrow = None
        self.rbrow = None
        self.lear = None
        self.rear = None
        self.leye_open = None
        self.reye_open = None
        self.leye_closed = None
        self.reye_closed = None
        self.mouth_open = None
        self.mouth_closed = None
        self.mouth_smile = None
        self.headItemXForm = swf.swf.Matrix()
        self.neckItemXForm = swf.swf.Matrix()
        self.faceItemXForm = swf.swf.Matrix()


def _get_cached_cat_component(partDir: str, catTree: swf.SWF_Tree, node_name: str, cat: CustomCat, frame: int, texture: int | None, extra: tuple[Any, ...] = ()) -> sprite.Sprite:
    key = (partDir, id(catTree), node_name, cat.id,
           cat.palette, cat.texture, frame, texture, extra)
    cached = _COMPONENT_CACHE.get(key)
    if cached is not None:
        return copy.deepcopy(cached)

    part = catpart.getCatComponent(
        partDir, catTree, getCatTree(catTree, node_name), frame, texture)
    palette.applyPalette(palette.loadPalettes(
        "./data/textures/palette.png")[cat.palette], part.data)
    _COMPONENT_CACHE[key] = copy.deepcopy(part)
    return copy.deepcopy(part)


#: which sprite symbol provides the artwork of each equip-independent cat part
PART_COMPONENT_NODE = {
    "body": "CatBody",
    "arm1": "CatLeg",
    "arm2": "CatLeg",
    "leg1": "CatLeg",
    "leg2": "CatLeg",
    "tail": "CatTail",
}


def _build_cat_part(cat: CustomCat, partKey: str, partDir: str, palettes: list[palette.Palette], catTree: swf.SWF_Tree) -> sprite.Sprite:
    part = getattr(cat, partKey)
    return _get_cached_cat_component(partDir, catTree, PART_COMPONENT_NODE[partKey], cat, part.frame, part.texture)


def _get_cat_part(cat: CustomCat, partKey: str, partDir: str, palettes: list[palette.Palette], catTree: swf.SWF_Tree) -> sprite.Sprite:
    """Equip-independent part (limb/body/tail), reused through reusable/shapes.

    Cached as ``<cat-id>-<part>.svg``.
    """
    cacheName = reusable.shape_cache_name(cat.id, partKey)
    return reusable.get_or_build_shape(
        cacheName,
        lambda: _build_cat_part(cat, partKey, partDir, palettes, catTree),
    )


def _head_expression(frame: animations.CatFrame, tagName: str) -> str | None:
    """Face name a head tag resolves to, used both for the pose and the cache name."""
    if tagName.startswith("head_"):
        variant = tagName.removeprefix("head_")
        if variant:
            return variant
    return frame.face or None


def _build_cat_head(cat: CustomCat, expression: str | None, equip: CatEquipment, partDir: str, palettes: list[palette.Palette], catTree: swf.SWF_Tree) -> sprite.Sprite:
    _, face = makeCatHead(cat, partDir, palettes, catTree)
    return headWithPose(cat, partDir, catTree, equip, face, resolve_face_pose(expression), palettes)


def _get_cat_head(
    cat: CustomCat,
    expression: str | None,
    equip: CatEquipment,
    equipNames: EquipNames | None,
    equipDefaults: EquipNames | None,
    partDir: str,
    palettes: list[palette.Palette],
    catTree: swf.SWF_Tree,
) -> sprite.Sprite:
    """Head + equipment sprite for one pose, reused through reusable/shapes.

    Cached as ``<cat-id>-head<-表情><-装备>.svg``.
    """
    cacheName = reusable.shape_cache_name(
        cat.id, "head", expression=expression, equip=equipNames, defaults=equipDefaults)
    return reusable.get_or_build_shape(
        cacheName,
        lambda: _build_cat_head(cat, expression, equip,
                                partDir, palettes, catTree),
    )


def _build_cat_from_frame(
    cat: CustomCat,
    frame: animations.CatFrame,
    equip: CatEquipment,
    equipNames: EquipNames | None,
    equipDefaults: EquipNames | None,
    partDir: str,
    palettes: list[palette.Palette],
    catTree: swf.SWF_Tree,
) -> sprite.Sprite:
    """Whole cat laid out by one animation frame's per-part placements."""
    plan = _build_frame_plan(cat, partDir, palettes, catTree, equip, frame,
                             equipNames=equipNames, equipDefaults=equipDefaults)
    parts = _instantiate_frame_plan(plan)
    return sprite.spriteFromPlacedObjects(partDir, catTree, parts)


def _get_cat_character(
    cat: CustomCat,
    equip: CatEquipment,
    equipNames: EquipNames | None,
    equipDefaults: EquipNames | None,
    partDir: str,
    palettes: list[palette.Palette],
    catTree: swf.SWF_Tree,
    restFrame: animations.CatFrame,
) -> sprite.Sprite:
    """Whole-cat sprite used by the `character` part, reused through reusable/shapes.

    Cached as ``<cat-id>-character<-表情><-装备>.svg``.  The cached artwork
    is the cat's canonical rest pose, which every animation shares up to a
    constant translation (see :func:`_rest_pose_offset`).
    """
    cacheName = reusable.shape_cache_name(
        cat.id, "character", equip=equipNames, defaults=equipDefaults)
    cached = _CHARACTER_CACHE.get(cacheName)
    if cached is None:
        cached = reusable.load_shape(cacheName)
        if cached is None:
            cached = _build_cat_from_frame(cat, restFrame, equip, equipNames,
                                           equipDefaults, partDir, palettes, catTree)
            reusable.save_shape(cacheName, cached)
        _CHARACTER_CACHE[cacheName] = cached

    return copy.deepcopy(cached)


def _rest_pose_offset(restFrame: animations.CatFrame, frame: animations.CatFrame) -> tuple[float, float]:
    """Translation between the canonical rest pose and another animation's rest pose.

    Every cat animation starts from the same rest pose and only places it
    differently inside the frame, so a single constant translation converts one
    into the other.  Verified for all `character` animations by
    tests/test_character_overlay.py.
    """
    for key in ("body", "head", "tail", "leg1", "leg2", "arm1", "arm2"):
        reference = getattr(restFrame, key, None)
        other = getattr(frame, key, None)
        if not reference or not other:
            continue
        referenceMatrix, otherMatrix = reference[0], other[0]
        if referenceMatrix is None or otherMatrix is None:
            continue
        return (otherMatrix.xoffset - referenceMatrix.xoffset,
                otherMatrix.yoffset - referenceMatrix.yoffset)

    return (0.0, 0.0)


def _translation(offset: tuple[float, float]) -> swf.swf.Matrix:
    out = swf.swf.Matrix()
    out.xoffset = offset[0]
    out.yoffset = offset[1]
    return out


def _equipment_cache_key(equipment: CatEquipment) -> tuple[Any, ...]:
    return (
        id(equipment),
        id(equipment.head_front),
        id(equipment.head_back),
        id(equipment.face_front),
        id(equipment.face_back),
        id(equipment.neck_front),
        id(equipment.neck_back),
    )


def _cat_face_cache_key(cat: CustomCat, partDir: str, catTree: swf.SWF_Tree) -> tuple[Any, ...]:
    return (
        partDir,
        id(catTree),
        cat.id,
        cat.palette,
        cat.texture,
        cat.head.frame,
        cat.leftear.frame,
        cat.rightear.frame,
        cat.lefteye.frame,
        cat.righteye.frame,
        cat.lefteyebrow.frame,
        cat.righteyebrow.frame,
        cat.mouth.frame,
        getattr(cat, "mouth_sprite", "CatMouth"),
    )


def makeCatHead(cat: CustomCat, partDir: str, palettes: list[palette.Palette], catTree: swf.SWF_Tree) -> tuple[swf.swf.Matrix, CatFace]:
    key = _cat_face_cache_key(cat, partDir, catTree)
    cached = _HEAD_FACE_CACHE.get(key)
    if cached is not None:
        return (catpart.HeadPlacements(getCatTree(catTree, "CatHeadPlacements").frames[cat.head.frame]).head.xform, copy.deepcopy(cached))

    colors = palettes[cat.palette]

    placements = catpart.HeadPlacements(getCatTree(catTree,
                                                   "CatHeadPlacements").frames[cat.head.frame])

    face = CatFace()

    allParts = []
    if (placements.lear != None):
        face.lear = copy.deepcopy(_get_cached_cat_component(
            partDir, catTree, "CatEar", cat, cat.leftear.frame, cat.leftear.texture))
        face.lear.applyTransform(placements.lear.xform).applyTransform(
            placements.lear.cxform)
        allParts.append(face.lear)

    if (placements.rear != None):
        face.rear = copy.deepcopy(_get_cached_cat_component(
            partDir, catTree, "CatEar", cat, cat.rightear.frame, cat.rightear.texture))
        face.rear.applyTransform(placements.rear.xform).applyTransform(
            placements.rear.cxform)
        allParts.append(face.rear)

    if (placements.leye != None):
        face.leye_open = copy.deepcopy(_get_cached_cat_component(
            partDir, catTree, "CatEye", cat, cat.lefteye.frame, cat.lefteye.texture))
        face.leye_open.applyTransform(
            placements.leye.xform).applyTransform(placements.leye.cxform)

        face.leye_closed = copy.deepcopy(_get_cached_cat_component(
            partDir, catTree, "CatEyeClosed", cat, cat.lefteye.frame, cat.lefteye.texture))
        face.leye_closed.applyTransform(
            placements.leye.xform).applyTransform(placements.leye.cxform)

        face.lbrow = copy.deepcopy(_get_cached_cat_component(
            partDir, catTree, "CatEyebrow", cat, cat.lefteyebrow.frame, cat.lefteyebrow.texture))
        face.lbrow.applyTransform(placements.leye.xform).applyTransform(
            placements.leye.cxform)

        allParts += [face.leye_open, face.leye_closed, face.lbrow]

    if (placements.reye != None):
        face.reye_open = copy.deepcopy(_get_cached_cat_component(
            partDir, catTree, "CatEye_Right", cat, cat.righteye.frame, cat.righteye.texture))
        face.reye_open.applyTransform(
            placements.reye.xform).applyTransform(placements.reye.cxform)

        face.reye_closed = copy.deepcopy(_get_cached_cat_component(
            partDir, catTree, "CatEyeClosed_Right", cat, cat.righteye.frame, cat.righteye.texture))
        face.reye_closed.applyTransform(
            placements.reye.xform).applyTransform(placements.reye.cxform)

        face.rbrow = copy.deepcopy(_get_cached_cat_component(
            partDir, catTree, "CatEyebrow", cat, cat.righteyebrow.frame, cat.righteyebrow.texture))
        face.rbrow.applyTransform(placements.reye.xform).applyTransform(
            placements.reye.cxform)

        allParts += [face.reye_open, face.reye_closed, face.rbrow]

    base_name = getattr(cat, 'mouth_sprite', 'CatMouth')
    closed_name = base_name
    open_name = base_name + "Open"
    smile_name = base_name + "Smile"

    def get_mouth_component(default_name, fallback_name):
        node = getCatTree(catTree, default_name)
        if node is None:
            logging.warning(
                f"Mouth sprite '{default_name}' not found, falling back to '{fallback_name}'")
            node = getCatTree(catTree, fallback_name)
        return copy.deepcopy(_get_cached_cat_component(partDir, catTree, default_name, cat, cat.mouth.frame, cat.mouth.texture, (fallback_name,)))

    face.mouth_closed = get_mouth_component(closed_name, "CatMouth")
    face.mouth_open = get_mouth_component(open_name, "CatMouthOpen")
    face.mouth_smile = get_mouth_component(smile_name, "CatMouthSmile")

    face.mouth_closed.applyTransform(
        placements.mouth.xform).applyTransform(placements.mouth.cxform)
    face.mouth_open.applyTransform(
        placements.mouth.xform).applyTransform(placements.mouth.cxform)
    face.mouth_smile.applyTransform(
        placements.mouth.xform).applyTransform(placements.mouth.cxform)

    allParts += [face.mouth_closed, face.mouth_open, face.mouth_smile]

    if (placements.headItem != None and placements.headItem.xform != None):
        face.headItemXForm = placements.headItem.xform

    if (placements.faceItem != None and placements.faceItem.xform != None):
        face.faceItemXForm = placements.faceItem.xform

    if (placements.neckItem != None and placements.neckItem.xform != None):
        face.neckItemXForm = placements.neckItem.xform

    # No second palette pass here: `_get_cached_cat_component` already recoloured
    # every face part, and `applyPalette` is not idempotent.  For palettes that map
    # one grey to another grey (Pebbles' palette 4, MonkCat's palette 66) applying
    # it twice shifts the colour again, which made only their ears wrong while the
    # head (recoloured once, in `headWithPose`) stayed correct.

    _HEAD_FACE_CACHE[key] = copy.deepcopy(face)
    return (placements.head.xform, copy.deepcopy(face))


ITEM_DICT = None


def getCatEquipment(partDir: str, catTree: swf.SWF_Tree, head: str | None, face: str | None, neck: str | None) -> CatEquipment:
    global ITEM_DICT

    out = CatEquipment()

    if (ITEM_DICT == None):
        ITEM_DICT = items.getItemDict()

    if (head != None):
        idata = ITEM_DICT[head]
        frame = idata.frame - 1

        fronts = getCatTree(catTree, "HeadItemF").frames[frame].objs
        backs = getCatTree(catTree, "HeadItemB").frames[frame].objs

        frontKeep = []
        for obj in fronts:
            if obj.name != "aux":
                frontKeep.append(obj)

        backKeep = []
        for obj in backs:
            if obj.name != "aux":
                backKeep.append(obj)

        out.head_front = sprite.spriteFromPlacedObjects(
            partDir, catTree, frontKeep)
        out.head_back = sprite.spriteFromPlacedObjects(
            partDir, catTree, backKeep)

    if (face != None):
        idata = ITEM_DICT[face]
        frame = idata.frame - 1

        fronts = getCatTree(catTree, "FaceItemF").frames[frame].objs
        backs = getCatTree(catTree, "FaceItemB").frames[frame].objs

        out.face_front = sprite.spriteFromPlacedObjects(
            partDir, catTree, fronts)
        out.face_back = sprite.spriteFromPlacedObjects(partDir, catTree, backs)

        out.face_front = sprite.spriteFromPlacedObjects(
            partDir, catTree, fronts)
        out.face_back = sprite.spriteFromPlacedObjects(partDir, catTree, backs)

    if (neck != None):
        idata = ITEM_DICT[neck]
        frame = idata.frame - 1

        fronts = getCatTree(catTree, "NeckItemF")
        backs = getCatTree(catTree, "NeckItemB")

        out.neck_front = sprite.spriteFromPlacedObjects(
            partDir, catTree, fronts.frames[frame].objs)
        out.neck_back = sprite.spriteFromPlacedObjects(
            partDir, catTree, backs.frames[frame].objs)

    return out


def getDefaultEquipNames(catId: str) -> EquipNames:
    equipment_data: dict = gon.parse_gon(
        CAT_MINIBOSSES_GON) | gon.parse_gon(TERMINATOR_GON)

    catId = namefix.get(catId) or catId

    head_item = face_item = neck_item = None
    if catId in equipment_data.keys():
        equipments = equipment_data.get(catId, {}).get("equipment") or {}
        head_item = equipments.get("head", None)
        face_item = equipments.get("face", None)
        neck_item = equipments.get("neck", None)
    return (head_item, face_item, neck_item)


# Hand-tuned head layer order, listed from the bottom (drawn first) to the top
# (drawn last).  Each entry gets an increasing depth, so a layer listed later
# covers the ones before it.
HEAD_LAYER_ORDER_FRONT = (
    "neckItem",   # Neck Item
    "lear",       # Left Ear
    "rear",       # Right Ear
    "head",       # Head
    "leye",       # Left Eye
    "lbrow",      # Left Eyebrow
    "mouth",      # Mouth
    "reye",       # Right Eye
    "rbrow",      # Right Eyebrow
    "headItem",   # Head Item
    "faceItem",   # Face Item
)

HEAD_LAYER_ORDER_BACK = (
    "faceItem",   # Face Item
    "leye",       # Left Eye
    "lbrow",      # Left Eyebrow
    "mouth",      # Mouth
    "reye",       # Right Eye
    "rbrow",      # Right Eyebrow
    "lear",       # Left Ear
    "rear",       # Right Ear
    "head",       # Head
    "headItem",   # Head Item
    "neckItem",   # Neck Item
)


def _head_layer_depths(back: bool) -> dict[str, int]:
    """Stacking depth of every head layer, bottom to top."""
    order = HEAD_LAYER_ORDER_BACK if back else HEAD_LAYER_ORDER_FRONT
    return {name: index for index, name in enumerate(order)}


# palette and base position should be applied before this
def headWithPose(cat: CustomCat, partDir: str, catTree: swf.SWF_Tree, equipment: CatEquipment, face: CatFace, pose: FacePose, palettes: list[palette.Palette]):
    pose_key = (
        partDir,
        id(catTree),
        cat.id,
        cat.palette,
        cat.texture,
        cat.head.frame,
        pose.offset,
        pose.browUp,
        pose.eyes,
        pose.mouth,
        pose.back,
        _equipment_cache_key(equipment),
        id(face),
    )
    cached = _HEAD_POSE_CACHE.get(pose_key)
    if cached is not None:
        return copy.deepcopy(cached)

    head = copy.deepcopy(catpart.getCatHeadShape(partDir, catTree, getCatTree(catTree,
                                                                              "CatHead"), cat.head.frame, cat.texture, pose.offset))
    palette.applyPalette(palettes[cat.palette], head.data)

    face = copy.deepcopy(face)
    equipment = copy.deepcopy(equipment)

    # The layer order is fixed by hand (see HEAD_LAYER_ORDER_FRONT/BACK) rather
    # than taken from CatHeadPlacements.
    depths = _head_layer_depths(bool(pose.back))

    assembly = [
        sprite.PlacedSprite(head, 0, depths["head"], None, "Head")
    ]

    onlyoffset = swf.swf.Matrix()
    onlyoffset.xoffset = pose.offset[0]
    onlyoffset.yoffset = -pose.offset[1]

    head_item = equipment.head_back if pose.back else equipment.head_front
    face_item = equipment.face_back if pose.back else equipment.face_front
    neck_item = equipment.neck_back if pose.back else equipment.neck_front

    if (head_item != None):
        head_item.applyTransform(face.headItemXForm)
        assembly.append(sprite.PlacedSprite(
            head_item, 0, depths["headItem"], None, "Head Item"))

    if (face_item != None):
        face_item.applyTransform(face.faceItemXForm)
        face_item.applyTransform(onlyoffset)
        assembly.append(sprite.PlacedSprite(
            face_item, 0, depths["faceItem"], None, "Face Item"))

    if (neck_item != None):
        neck_item.applyTransform(face.neckItemXForm)
        assembly.append(sprite.PlacedSprite(
            neck_item, 0, depths["neckItem"], None, "Neck Item"))

    if (face.lear != None):
        xform = swf.swf.Matrix()
        face.lear.applyTransform(xform)
        assembly.append(sprite.PlacedSprite(
            face.lear, 0, depths["lear"], None, "Left Ear"))

    if (face.rear != None):
        xform = swf.swf.Matrix()
        face.rear.applyTransform(xform)
        assembly.append(sprite.PlacedSprite(
            face.rear, 0, depths["rear"], None, "Right Ear"))

    if (face.lbrow != None):
        xform = swf.swf.Matrix()
        xform.xoffset = pose.offset[0]
        xform.yoffset = -pose.offset[1] - pose.browUp[0]
        face.lbrow.applyTransform(xform)
        assembly.append(sprite.PlacedSprite(
            face.lbrow, 0, depths["lbrow"], None, "Left Brow"))

    if (face.rbrow != None):
        xform = swf.swf.Matrix()
        xform.xoffset = pose.offset[0]
        xform.yoffset = -pose.offset[1] - pose.browUp[1]
        face.rbrow.applyTransform(xform)
        assembly.append(sprite.PlacedSprite(
            face.rbrow, 0, depths["rbrow"], None, "Right Brow"))

    if (pose.eyes[0] == "closed" and face.leye_closed != None):
        face.leye_closed.applyTransform(onlyoffset)
        assembly.append(sprite.PlacedSprite(face.leye_closed, 0,
                        depths["leye"], None, "Left Eye"))
    elif (pose.eyes[0] == "open" and face.leye_open != None):
        face.leye_open.applyTransform(onlyoffset)
        assembly.append(sprite.PlacedSprite(face.leye_open, 0,
                        depths["leye"], None, "Left Eye"))
    elif (pose.eyes[0] != "closed" and pose.eyes[0] != "open"):
        raise RuntimeError("Weird eye state " + pose.eyes[0])

    if (pose.eyes[1] == "closed" and face.reye_closed != None):
        face.reye_closed.applyTransform(onlyoffset)
        assembly.append(sprite.PlacedSprite(face.reye_closed, 0,
                        depths["reye"], None, "Right Eye"))
    elif (pose.eyes[1] == "open" and face.reye_open != None):
        face.reye_open.applyTransform(onlyoffset)
        assembly.append(sprite.PlacedSprite(face.reye_open, 0,
                        depths["reye"], None, "Right Eye"))
    elif (pose.eyes[1] != "closed" and pose.eyes[1] != "open"):
        raise RuntimeError("Weird eye state " + pose.eyes[1])

    if (pose.mouth == "closed" and face.mouth_closed != None):
        tf = sprite.Sprite.matrixFromSVG(
            face.mouth_closed.data.data.getTransform())
        if (pose.offset[0] < 0):
            tf.xscale *= -1.0
            face.mouth_closed.data.data.subcomponents[0].setTransform(
                sprite.Sprite.matrixToSVG(tf))

        face.mouth_closed.applyTransform(onlyoffset)
        assembly.append(sprite.PlacedSprite(face.mouth_closed,
                        0, depths["mouth"], None, "Mouth"))
    elif (pose.mouth == "open" and face.mouth_open != None):
        tf = sprite.Sprite.matrixFromSVG(
            face.mouth_open.data.data.getTransform())
        if (pose.offset[0] < 0):
            tf.xscale *= -1.0
            face.mouth_open.data.data.subcomponents[0].setTransform(
                sprite.Sprite.matrixToSVG(tf))

        face.mouth_open.applyTransform(onlyoffset)
        assembly.append(sprite.PlacedSprite(face.mouth_open, 0,
                        depths["mouth"], None, "Mouth"))
    elif (pose.mouth == "smile" and face.mouth_smile != None):
        tf = sprite.Sprite.matrixFromSVG(
            face.mouth_smile.data.data.getTransform())
        if (pose.offset[0] < 0):
            tf.xscale *= -1.0
            face.mouth_smile.data.data.subcomponents[0].setTransform(
                sprite.Sprite.matrixToSVG(tf))

        face.mouth_smile.applyTransform(onlyoffset)
        assembly.append(sprite.PlacedSprite(face.mouth_smile, 0,
                        depths["mouth"], None, "Mouth"))
    elif (pose.mouth != "closed" and pose.mouth != "open" and pose.mouth != "smile"):
        raise RuntimeError("Weird mouth state " + pose.mouth)

    out = sprite.spriteFromPlacedObjects(partDir, catTree, assembly)
    _HEAD_POSE_CACHE[pose_key] = copy.deepcopy(out)
    return copy.deepcopy(out)


def getCustomCats() -> list[CustomCat]:
    data = gon.parse_gon(CUSTOM_CAT_GON)

    out: list[CustomCat] = []
    for id, cat in data.items():
        if (id == "__COMMENTS__"):
            continue

        out.append(CustomCat(id, cat))

    return out


def _measure_sprite_bounds(part: sprite.Sprite, window: float) -> tuple[float, float, float, float]:
    """Bounds of the artwork actually visible in one sprite, in its own coordinates.

    The sprite is measured through a temporary square `viewBox` centred on the
    frame origin, because the merged frame roots declare a size that does not
    necessarily cover their content.

    Only pixels that are at least half opaque define the extent; anything further
    than ``BOUNDS_HALO`` from that core is treated as a rendering artefact.  This
    matters because the part SVGs carry `<clipPath>` geometry that ImageMagick's
    renderer leaks as very faint (alpha 1-32) pixels far outside the artwork --
    ThiefCat's tail leaked ~65 units up and to the left, which padded the whole
    animation canvas with empty space.
    """
    probe = copy.deepcopy(part)
    root = probe.data.data

    size = window * 2.0
    root.setField("viewBox", f"{-window} {-window} {size} {size}")
    root.setField("width", f"{size}px")
    root.setField("height", f"{size}px")

    with Color('transparent') as bg:
        with Image(blob=probe.compile().encode("utf-8"), background=bg, resolution=MEASURE_DPI) as img:
            png = img.make_blob("png")

    if png is None:
        logger.warning(
            "ImageMagick produced no PNG data while measuring sprite bounds")
        return (0.0, 0.0, 0.0, 0.0)

    with PILImage.open(io.BytesIO(png)) as rgba:
        alpha = rgba.convert("RGBA").getchannel("A")
        bbox = alpha.getbbox()
        if bbox is None:
            return (0.0, 0.0, 0.0, 0.0)

        def _alpha_core(value: Any) -> int:
            return 255 if int(value) > BOUNDS_ALPHA_THRESHOLD else 0

        core = alpha.point(_alpha_core).getbbox()
        if core is not None:
            bbox = (
                max(bbox[0], core[0] - BOUNDS_HALO),
                max(bbox[1], core[1] - BOUNDS_HALO),
                min(bbox[2], core[2] + BOUNDS_HALO),
                min(bbox[3], core[3] + BOUNDS_HALO),
            )

    # At MEASURE_DPI the raster is exactly `size` pixels, so one pixel is one
    # user unit and the window offset converts straight back to frame space.
    left, top, right, bottom = bbox
    return (left - window, top - window, right - window, bottom - window)


def compute_frames_canvas(
    frames: list[sprite.Sprite],
    window: float = FRAME_BOUNDS_WINDOW,
    margin: float = 0.0,
) -> tuple[float, float, float, float]:
    """Smallest box containing every frame's drawn pixels.

    Returns ``(left, top, right, bottom)`` in frame coordinates, so translating
    by ``(-left, -top)`` maps the whole animation into ``(0, 0, w, h)``.  The
    window is doubled while any frame touches its border, which keeps the result
    correct for animations that move further than expected.
    """
    while True:
        left = top = float("inf")
        right = bottom = float("-inf")
        clipped = False

        for frame in frames:
            fl, ft, fr, fb = _measure_sprite_bounds(frame, window)
            if fl <= -window + 1 or ft <= -window + 1 or fr >= window - 1 or fb >= window - 1:
                clipped = True
            left = min(left, fl)
            top = min(top, ft)
            right = max(right, fr)
            bottom = max(bottom, fb)

        if not clipped or window >= FRAME_BOUNDS_MAX_WINDOW:
            break

        logging.debug("Frame content touches the measurement window; growing it to %s",
                      window * 2.0)
        window *= 2.0

    if left == float("inf"):
        return (0.0, 0.0, 0.0, 0.0)

    if clipped:
        logging.warning(
            "Frame bounds may be clipped even at a %s unit window", window)

    return (left - margin, top - margin, right + margin, bottom + margin)


def set_svg_canvas(frame_sprite: sprite.Sprite, width: float, height: float):
    """Pin the exported SVG root to the shared animation canvas."""
    if frame_sprite is None or frame_sprite.data is None or frame_sprite.data.data is None:
        return

    root = frame_sprite.data.data
    if "<svg" not in root.header:
        return

    root.setField("width", f"{width}px")
    root.setField("height", f"{height}px")
    # 1 user unit == 1 pixel, with the canvas origin at the top-left corner.
    root.setField("viewBox", f"0 0 {width} {height}")


def _render_gif_frame(svg_data: str, background: Any, resolution: float):
    """Rasterise one frame's SVG into a single RGBA Pillow frame.

    ImageMagick is used only to turn the SVG into pixels; the PNG blob is a
    short-lived vehicle, not a file on disk.
    """
    with Image(blob=svg_data.encode("utf-8"), background=background,
               resolution=resolution) as img:
        # Keep the raster at 1 pixel per user unit so the PNG does not carry a
        # resolution that Pillow would only have to undo.
        img.resolution = MEASURE_DPI
        png = img.make_blob("png")

    if png is None:
        raise RuntimeError("ImageMagick produced no PNG data for a GIF frame")

    with PILImage.open(io.BytesIO(png)) as rendered:
        return rendered.convert("RGBA")


def save_cat_output(outfolder, cat_id, anim_name, frames: list[sprite.Sprite], scaling=3.0, generate_gif: bool = True):
    """将 frames 列表中的 Sprite 保存为 SVG 序列、第一帧 PNG 和 GIF 动画

    The canvas is sized to the whole animation instead of a fixed square, so the
    frames are already framed and the GIF needs no post-processing crop.

    ``generate_gif=False`` only skips the raster/GIF step; the SVG frame sequence
    is always written (see ``--no-gif``).

    The GIF is assembled one frame at a time and streamed straight to disk.
    Handing the frames to ImageMagick as an image *sequence* instead costs a
    full-resolution pixel buffer per frame, a second set for ``coalesce()`` and
    then ImageMagick's own pixel cache on disk; a 310 frame animation peaked at
    14.6 GB of RAM and ~3 GB of temporary files.  Streaming keeps the peak at
    roughly two frames and writes nothing but the output file.

    Frames are released as they are exported: every caller renders a list only
    to hand it over here, so dropping each sprite's tree once its SVG is written
    keeps long batches from growing.
    """
    assets_path = os.path.join(outfolder, f"{cat_id}-{anim_name}")
    if os.path.exists(assets_path):
        shutil.rmtree(assets_path)
    os.makedirs(assets_path, exist_ok=True)

    left, top, right, bottom = compute_frames_canvas(frames)
    width = max(1.0, right - left)
    height = max(1.0, bottom - top)

    translate = swf.swf.Matrix()
    translate.xoffset = -left
    translate.yoffset = -top

    logging.info("Animation canvas for '%s-%s': %.0fx%.0f at (%.1f, %.1f)",
                 cat_id, anim_name, width, height, left, top)

    def exported_frames():
        """Write every SVG, yielding each frame's markup as it is produced."""
        for i, frame_sprite in enumerate(frames):
            outfile = os.path.join(assets_path, f"{i}.svg")
            set_svg_canvas(frame_sprite, width, height)
            frame_sprite.applyTransform(translate)
            svgData = frame_sprite.compile()
            with open(outfile, "w", encoding="utf-8") as f:
                f.write(svgData)
            yield i, svgData

            # The SVG is on disk; only the running GIF pass may still want the
            # sprite, and by the time we resume it has already been rasterised.
            frame_sprite.free()

    if not generate_gif:
        for _frame in exported_frames():
            pass
        return

    outfile = os.path.join(outfolder, f"{cat_id}-{anim_name}.gif")

    with Color('transparent') as bg:
        source = exported_frames()
        first = next(source, None)
        if first is None:
            logging.warning("No frames to export for '%s-%s'", cat_id, anim_name)
            return

        index, svgData = first
        resolution = MEASURE_DPI * scaling

        def gif_frames():
            # The first frame doubles as the still preview PNG, as before.
            first_frame = _render_gif_frame(svgData, bg, resolution)
            first_frame.save(os.path.join(assets_path, f"{index}.png"))
            yield first_frame

            del first_frame
            for _i, next_svg in source:
                yield _render_gif_frame(next_svg, bg, resolution)

        logging.info("Assembling GIF...")
        _write_gif(gif_frames(), outfile)


def _write_gif(frames, outfile: str):
    """Write ``frames`` (an iterator of RGBA images) to ``outfile`` as a GIF.

    Pillow consumes the iterator lazily, keeps at most two frames alive while it
    computes each frame's delta and merges runs of identical frames, and only
    ever touches the output file.
    """
    iterator = iter(frames)
    first = next(iterator, None)
    if first is None:
        raise ValueError("no frames to write")

    tmpfile = outfile + ".part"
    try:
        first.save(tmpfile, format="GIF", save_all=True, append_images=iterator,
                   loop=0, duration=GIF_FRAME_DURATION_MS, disposal=2,
                   optimize=True)
    except BaseException:
        if os.path.exists(tmpfile):
            os.remove(tmpfile)
        raise

    os.replace(tmpfile, outfile)



def frame_used_value(frame: animations.CatFrame, key: str):
    used = getattr(frame, "used", {}) or {}
    results: list[tuple[swf.swf.Matrix, int]] = []

    # collect exact key entries
    if key in used:
        results += list(used[key])

    # collect variant keys like 'head_back', 'head_default', etc.
    prefix = key + "_"
    for k, vals in used.items():
        if k.startswith(prefix):
            results += list(vals)

    # fallback to single attribute on the CatFrame (legacy)
    if not results:
        value = getattr(frame, key, None)
        if isinstance(value, tuple) and len(value) == 2:
            results = [value]

    # return entries sorted by depth (ascending)
    return sorted(results, key=lambda item: item[1])


def frame_used_tag_entries(frame: animations.CatFrame, key: str):
    used = getattr(frame, "used", {}) or {}
    results: list[tuple[str, swf.swf.Matrix, int]] = []
    seen: set[tuple[str, int]] = set()

    if key in used:
        for matrix, depth in used[key]:
            marker = (key, depth)
            if marker not in seen:
                seen.add(marker)
                results.append((key, matrix, depth))

    prefix = key + "_"
    for tag_name, values in used.items():
        if tag_name.startswith(prefix):
            for matrix, depth in values:
                marker = (tag_name, depth)
                if marker not in seen:
                    seen.add(marker)
                    results.append((tag_name, matrix, depth))

    if not results:
        value = getattr(frame, key, None)
        if isinstance(value, tuple) and len(value) == 2:
            matrix, depth = value
            results.append((key, matrix, depth))

    return sorted(results, key=lambda item: item[2])


def _frame_plan_entry(name: str, depth: int, matrix: swf.swf.Matrix | None, sprite_template: sprite.Sprite) -> dict[str, Any]:
    return {
        "name": name,
        "depth": depth,
        "matrix": matrix,
        "sprite_template": sprite_template,
    }


def _build_frame_plan(
    cat: CustomCat,
    partDir: str,
    palettes: list[palette.Palette],
    catTree: swf.SWF_Tree,
    equip: CatEquipment,
    frame: animations.CatFrame,
    extras: dict[str, tuple[swf.swf.Matrix, int]] | None = None,
    *,
    depth_sort: bool = True,
    equipNames: EquipNames | None = None,
    equipDefaults: EquipNames | None = None,
) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []

    for tag_name, matrix, depth in frame_used_tag_entries(frame, "head"):
        plan.append(_frame_plan_entry(
            f"Whole Head:{tag_name}",
            depth,
            matrix,
            _get_cat_head(cat, _head_expression(frame, tag_name), equip, equipNames,
                          equipDefaults, partDir, palettes, catTree),
        ))

    for part_key, label in (("body", "Body"), ("arm1", "Right Arm"), ("arm2", "Left Arm"),
                            ("leg1", "Right Leg"), ("leg2", "Left Leg"), ("tail", "Tail")):
        for matrix, depth in frame_used_value(frame, part_key):
            plan.append(_frame_plan_entry(
                label, depth, matrix,
                _get_cat_part(cat, part_key, partDir, palettes, catTree)))

    if extras:
        for name, (matrix, depth) in extras.items():
            bareName = name.removeprefix("other_")
            if bareName == "head":
                sprite_template = _get_cat_head(
                    cat, frame.face or None, equip, equipNames, equipDefaults,
                    partDir, palettes, catTree)
            elif bareName in PART_COMPONENT_NODE:
                sprite_template = _get_cat_part(
                    cat, bareName, partDir, palettes, catTree)
            else:
                continue
            plan.append(_frame_plan_entry(
                f"Extra {name}", depth, matrix, sprite_template))

    if depth_sort:
        plan.sort(key=lambda item: item["depth"])
    return plan


def _instantiate_frame_plan(plan: list[dict[str, Any]]) -> list[sprite.PlacedSprite]:
    assembly: list[sprite.PlacedSprite] = []
    for entry in plan:
        part = copy.deepcopy(entry["sprite_template"])
        if entry["matrix"] is not None:
            part.applyTransform(entry["matrix"])
        assembly.append(sprite.PlacedSprite(
            part, 0, entry["depth"], None, entry["name"]))
    return assembly


def _assemble_frame_part_sprites(
    cat: CustomCat,
    partDir: str,
    palettes: list[palette.Palette],
    catTree: swf.SWF_Tree,
    equip: CatEquipment,
    frame: animations.CatFrame,
    extras: dict[str, tuple[swf.swf.Matrix, int]] | None = None,
    *,
    depth_sort: bool = True,
    equipNames: EquipNames | None = None,
    equipDefaults: EquipNames | None = None,
) -> list[sprite.PlacedSprite]:
    """Build a frame from reusable part sprites while preserving each part's SWF depth and transform metadata."""
    plan = _build_frame_plan(cat, partDir, palettes, catTree, equip, frame, extras,
                             depth_sort=depth_sort, equipNames=equipNames,
                             equipDefaults=equipDefaults)
    return _instantiate_frame_plan(plan)


def assembleCat_with_equip(
    cat: CustomCat,
    partDir: str,
    palettes: list[palette.Palette],
    anim: list[animations.CatFrame],
    catTree: swf.SWF_Tree,
    equip: CatEquipment,
    equipNames: EquipNames | None = None,
    equipDefaults: EquipNames | None = None,
) -> list[sprite.Sprite]:
    out = []
    for frame in anim:
        assembly = _assemble_frame_part_sprites(
            cat, partDir, palettes, catTree, equip, frame,
            equipNames=equipNames, equipDefaults=equipDefaults)
        out.append(sprite.spriteFromPlacedObjects(partDir, catTree, assembly))
    return out


def _matrix_to_float_matrix(matrix: swf.swf.Matrix) -> FloatMatrix:
    return (
        float(matrix.xscale),
        float(matrix.skew1),
        float(matrix.skew2),
        float(matrix.yscale),
        float(matrix.xoffset),
        float(matrix.yoffset),
    )


def extract_anim_tag_pool_and_frames_info(anim: list[animations.CatFrame]) -> tuple[list[str], list[list[tuple[int, str, FloatMatrix | None]]]]:
    """Collect the per-frame tag metadata once, without depending on whether a second cat is being rendered.

    Entries are ``(depth, tag, transform)``; ``transform`` is ``None`` for the
    "UNSUPPORTED:<tag>" records produced for skipped tags.
    """
    tag_pool: list[str] = []
    frames_info: list[list[tuple[int, str, FloatMatrix | None]]] = []

    for frame in anim:
        used = getattr(frame, "used", {}) or {}
        frame_entries: list[tuple[int, str, FloatMatrix | None]] = []

        for tag_name, values in used.items():
            if tag_name not in tag_pool:
                tag_pool.append(tag_name)
            for matrix, depth in values:
                frame_entries.append(
                    (int(depth), tag_name, _matrix_to_float_matrix(matrix)))

        for key in ("head", "body", "arm1", "arm2", "leg1", "leg2", "tail"):
            if key in used or any(k.startswith(f"{key}_") for k in used):
                continue
            value = getattr(frame, key, None)
            if isinstance(value, tuple) and len(value) == 2:
                matrix, depth = value
                if matrix is None:
                    continue
                if depth == 0 and (
                    getattr(matrix, "xscale", 1.0) == 1.0 and
                    getattr(matrix, "yscale", 1.0) == 1.0 and
                    getattr(matrix, "skew1", 0.0) == 0.0 and
                    getattr(matrix, "skew2", 0.0) == 0.0 and
                    getattr(matrix, "xoffset", 0.0) == 0.0 and
                    getattr(matrix, "yoffset", 0.0) == 0.0
                ):
                    continue
                if key not in tag_pool:
                    tag_pool.append(key)
                frame_entries.append(
                    (int(depth), key, _matrix_to_float_matrix(matrix)))

        # keep a trace of every object we had to skip.
        for skipped in getattr(frame, "skipped", []) or []:
            depth = skipped.get("depth", 0)
            frame_entries.append((
                int(depth) if depth is not None else 0,
                str(skipped.get("tag", "UNSUPPORTED:?")),
                None,
            ))

        frame_entries.sort(key=lambda item: item[0])
        frames_info.append(frame_entries)

    return tag_pool, frames_info


def _write_anim_metadata(
    anim_name: str,
    tag_pool: list[str],
    frames_info: list[list[tuple[int, str, FloatMatrix | None]]],
    complete: bool = True,
    overlay_mode: str | None = None,
) -> dict[str, Any]:
    """Cache one animation's metadata under reusable/anims/<anim-name>.json.

    ``complete`` says whether the file describes the whole animation, including
    the second character.  Only complete files may be used to render without
    reading the source SWF, and an incomplete write never replaces a complete one.
    """
    payload: dict[str, Any] = {
        "anim_name": anim_name,
        "overlay_mode": overlay_mode,
        "complete": bool(complete),
    }

    if not complete:
        existing = reusable.load_anim_cache(anim_name)
        if existing is not None and existing.get("complete"):
            logger.debug(
                "Keeping the existing complete cache for '%s'", anim_name)
            return existing

    logger.info("Writing reusable animation metadata for '%s' with %d tag(s)%s",
                anim_name, len(tag_pool), "" if complete else " (incomplete)")

    frames_obj = {}
    for i, frame in enumerate(frames_info):
        entries = []
        for depth, tag_name, matrix in frame:
            entry: dict[str, Any] = {"depth": int(depth), "tag": tag_name}
            if matrix is None:
                entry["transform"] = None
                entry["note"] = "skipped"
            else:
                entry["transform"] = [float(v) for v in matrix]
            entries.append(entry)
        frames_obj[str(i)] = entries

    payload["tag_pool"] = list(tag_pool)
    payload["frames"] = frames_obj

    path = reusable.save_anim_cache(anim_name, payload)
    if path is not None:
        logger.debug("Cached animation metadata at %s", path)
    return payload


# kept for callers that still use the older name
_write_report_anim_metadata = _write_anim_metadata


class SecondCatResolver:
    """Resolves the second cat, asking the user only the very first time.

    Batch mode needs the same answer for every cat, and will ask at the 
    moment the animation places the second cat. Only *names* are resolved
    here, so this works without any SWF data; the caller builds the 
    equipment sprites when it actually has a tree.
    """

    def __init__(
        self,
        catList: list[CustomCat],
        cat2Id: str | None,
        equip2Mode: str,
        equip2: EquipNames | None,
    ):
        self.catList = catList
        self.cat2Id = cat2Id
        self.equip2Mode = equip2Mode
        self.equip2 = equip2

        self._resolved: tuple[CustomCat, tuple |
                              None, bool, tuple] | None = None
        self._attempted = False

    def resolve(self) -> tuple[CustomCat, EquipNames, bool, EquipNames] | None:
        if self._attempted:
            return self._resolved

        self._attempted = True

        cat2 = prompt_first_cat(self.catList, self.cat2Id,
                                allowPrompt=not self.cat2Id)
        if cat2 is None:
            logger.warning(
                "No cat matched '%s'; the second character will be skipped.", self.cat2Id)
            return None

        names, explicit = resolve_equipment_names(
            cat2, self.equip2Mode, self.equip2)
        self._resolved = (cat2, names, explicit,
                          tuple(getDefaultEquipNames(cat2.id)))
        return self._resolved


def render_animation(
    cat: CustomCat,
    partDir: str,
    palettes: list[palette.Palette],
    catpartTree: swf.SWF_Tree,
    cat_anim: list[animations.CatFrame],
    anim_name: str,
    anims: dict[str, list[animations.CatFrame]],
    catEquip: CatEquipment,
    equipNames: EquipNames | None,
    equipDefaults: EquipNames | None,
    secondCat: SecondCatResolver | None = None,
) -> list[sprite.Sprite]:
    """Render one animation, adding the second character the SWF asks for."""
    overlay_mode, payload = _second_cat_overlay_plan(cat_anim)
    logger.info("Resolved overlay mode for animation '%s': %s",
                anim_name, overlay_mode)

    frames, tag_pool, frames_info = _assemble_frames_for_first_cat(
        cat, partDir, palettes, cat_anim, catpartTree, catEquip,
        equipNames=equipNames, equipDefaults=equipDefaults)

    if overlay_mode is None:
        _write_anim_metadata(anim_name, tag_pool, frames_info,
                             complete=True, overlay_mode=None)
        return frames

    resolved = secondCat.resolve() if secondCat is not None else None
    if resolved is None:
        logger.info("Animation '%s' places a second character, but none was selected; "
                    "rendering the primary cat only.", anim_name)
        # The cached file would not describe the whole animation, so it is marked
        # incomplete and the next run re-reads the SWF.
        _write_anim_metadata(anim_name, tag_pool, frames_info,
                             complete=False, overlay_mode=overlay_mode)
        return frames

    cat2, equip2Names, equip2Explicit, equip2Defaults = resolved
    equip2CacheNames = None if not equip2Explicit else equip2Names
    catEquip2 = (getCatEquipment(partDir, catpartTree, *equip2Names)
                 if partDir is not None and catpartTree is not None
                 else CatEquipment())

    if overlay_mode == "parts":
        extras_by_frame = payload if isinstance(payload, list) else []
        frames, tag_pool, frames_info = _assemble_frames_for_first_cat(
            cat, partDir, palettes, cat_anim, catpartTree, catEquip,
            extras_by_frame, cat2, catEquip2, equipNames, equipDefaults,
            equip2CacheNames, equip2Defaults)
        _write_anim_metadata(anim_name, tag_pool, frames_info,
                             complete=True, overlay_mode=overlay_mode)
        logger.info(
            "Added second cat '%s' as frame-timed part overlay", cat2.id)
        return frames

    # `character`: the symbol the tag references is only a placeholder, so the
    # second cat is drawn as one whole-body layer positioned by that transform.
    idle_frame = _idle_first_frame(anims)
    if not idle_frame:
        logger.warning(
            "Animation '%s' needs the idle rest pose, which is unavailable.", anim_name)
        _write_anim_metadata(anim_name, tag_pool, frames_info,
                             complete=False, overlay_mode=overlay_mode)
        return frames

    # Cache the rest pose too, so a later run can rebuild this layer offline.
    idleFrames = anims.get("idleF")
    if idleFrames:
        _write_anim_metadata("idleF", *extract_anim_tag_pool_and_frames_info(idleFrames),
                             complete=True, overlay_mode=None)

    restFrame = idle_frame[0]
    characterSprite = _get_cat_character(
        cat2, catEquip2, equip2Names, equip2Defaults, partDir, palettes, catpartTree, restFrame)
    characterOffset = _rest_pose_offset(restFrame, cat_anim[0])

    characterByFrame: list[tuple[swf.swf.Matrix, int] | None] = []
    for aframe in cat_anim:
        entry = (getattr(aframe, "extra", {}) or {}).get("character")
        if entry is None:
            characterByFrame.append(None)
            continue
        matrix, depth = _extra_matrix_and_depth(entry)
        characterByFrame.append(None if matrix is None else (matrix, depth))

    frames, tag_pool, frames_info = _assemble_frames_for_first_cat(
        cat, partDir, palettes, cat_anim, catpartTree, catEquip,
        None, None, None, equipNames, equipDefaults, None, None,
        characterByFrame, characterSprite, characterOffset)
    _write_anim_metadata(anim_name, tag_pool, frames_info,
                         complete=True, overlay_mode=overlay_mode)
    logger.info("Added second cat '%s' as a whole-body character layer", cat2.id)
    return frames


def _second_character_transform(anim: list[animations.CatFrame], frame_index: int | None = None) -> swf.swf.Matrix | None:
    if frame_index is not None:
        frames = [anim[frame_index]] if 0 <= frame_index < len(anim) else []
    else:
        frames = anim

    for frame in frames:
        extra = getattr(frame, "extra", {}) or {}
        if "character" in extra:
            matrix, _ = _extra_matrix_and_depth(extra.get("character"))
            return matrix
    return None


def _as_matrix(value: Any) -> swf.swf.Matrix | None:
    if isinstance(value, swf.swf.Matrix):
        return value

    if isinstance(value, (list, tuple)) and len(value) == 6:
        matrix = swf.swf.Matrix()
        matrix.xscale, matrix.skew1, matrix.skew2, matrix.yscale, matrix.xoffset, matrix.yoffset = value
        return matrix

    return None


def _extra_matrix_and_depth(value: Any) -> tuple[swf.swf.Matrix | None, int]:
    if isinstance(value, tuple) and len(value) == 2:
        matrix_value, depth_value = value
        return _as_matrix(matrix_value), int(depth_value)

    return _as_matrix(value), 0


def _second_character_parts(anim: list[animations.CatFrame]) -> list[dict[str, tuple[swf.swf.Matrix, int]]]:
    out: list[dict[str, tuple[swf.swf.Matrix, int]]] = [{} for _ in anim]
    for i, frame in enumerate(anim):
        extra = getattr(frame, "extra", {}) or {}
        for key, value in extra.items():
            if not key.startswith("other_"):
                continue
            part_key = key.removeprefix("other_")
            if part_key in {"head", "body", "tail", "arm1", "arm2", "leg1", "leg2"}:
                matrix, depth = _extra_matrix_and_depth(value)
                if matrix is not None:
                    out[i][key] = (matrix, depth)
    return out


SECOND_CAT_PART_KEYS = {"head", "body", "tail", "arm1", "arm2", "leg1", "leg2"}


def _float_matrix_to_matrix(matrix: FloatMatrix) -> swf.swf.Matrix:
    out = swf.swf.Matrix()
    out.xscale, out.skew1, out.skew2, out.yscale, out.xoffset, out.yoffset = matrix
    return out


def _second_cat_overlay_plan(anim: list[animations.CatFrame]) -> tuple[str | None, swf.swf.Matrix | list[dict[str, tuple[swf.swf.Matrix, int]]] | None]:
    """Decide the second-cat overlay mode from animation metadata before rendering.

    This keeps mode detection based on tag extraction and per-frame metadata instead of
    forcing an early single-cat render as the de facto source of truth.
    """
    tag_pool, frames_info = extract_anim_tag_pool_and_frames_info(anim)

    # a part that is added on frame N must stay on frame N. The
    # per-frame list therefore keeps one slot per animation frame, including the
    # empty leading frames before the second cat is placed.
    second_parts_by_frame = _second_character_parts(anim)

    if any(second_parts_by_frame):
        first_frame = next(i for i, parts in enumerate(
            second_parts_by_frame) if parts)
        logger.info(
            "Second-cat overlay mode resolved from tag metadata: parts (first placed on frame %d, %d non-empty frame(s))",
            first_frame, sum(1 for parts in second_parts_by_frame if parts))
        return "parts", second_parts_by_frame

    if "character" in tag_pool:
        for frame in frames_info:
            for depth, tag_name, matrix in frame:
                if tag_name != "character" or matrix is None:
                    continue
                logger.info(
                    "Second-cat overlay mode resolved from tag metadata: character")
                return "character", _float_matrix_to_matrix(matrix)

    second_transform = _second_character_transform(anim)
    if second_transform is not None:
        logger.info(
            "Second-cat overlay mode resolved from legacy transform metadata: character")
        return "character", second_transform

    logger.debug(
        "No second-cat overlay metadata detected in animation tag pool.")
    return None, None


def _idle_first_frame(anims: dict[str, list[animations.CatFrame]]) -> list[animations.CatFrame] | None:
    for name, frames in anims.items():
        if name == "idleF":
            return frames[:1]
    return None


def _append_second_cat_extras(
    assembly: list[sprite.PlacedSprite],
    frame_entries: list[tuple[int, str, FloatMatrix | None]],
    cat2: CustomCat,
    partDir: str,
    palettes: list[palette.Palette],
    catTree: swf.SWF_Tree,
    equip2: CatEquipment,
    extras: dict[str, tuple[swf.swf.Matrix, int]],
    tag_pool: list[str],
    equip2Names: EquipNames | None = None,
    equip2Defaults: EquipNames | None = None,
) -> None:
    """Append the second cat's parts for one frame (the `other_*` overlay mode)."""
    if not extras:
        return

    def add_pool(name: str):
        if name not in tag_pool:
            tag_pool.append(name)

    for raw_name, (matrix, depth) in extras.items():
        tag_name = raw_name
        part_name = raw_name.removeprefix(
            "other_") if raw_name.startswith("other_") else raw_name

        if part_name == "head":
            part_sprite = _get_cat_head(
                cat2, None, equip2, equip2Names, equip2Defaults, partDir, palettes, catTree)
        elif part_name in PART_COMPONENT_NODE:
            part_sprite = _get_cat_part(
                cat2, part_name, partDir, palettes, catTree)
        else:
            continue

        part_sprite = copy.deepcopy(part_sprite)
        part_sprite.applyTransform(matrix)
        assembly.append(sprite.PlacedSprite(
            part_sprite, 0, depth, None, tag_name))
        add_pool(tag_name)
        frame_entries.append((depth, tag_name, (matrix.xscale, matrix.skew1,
                             matrix.skew2, matrix.yscale, matrix.xoffset, matrix.yoffset)))


PART_LABELS = {
    "body": "Body",
    "arm1": "Right Arm",
    "arm2": "Left Arm",
    "leg1": "Right Leg",
    "leg2": "Left Leg",
    "tail": "Tail",
}


def _assemble_frames_for_first_cat(
    cat: CustomCat,
    partDir: str,
    palettes: list[palette.Palette],
    anim: list[animations.CatFrame],
    catTree: swf.SWF_Tree,
    equip: CatEquipment,
    extras_by_frame: list[dict[str, tuple[swf.swf.Matrix, int]]] | None = None,
    second_cat: CustomCat | None = None,
    second_equip: CatEquipment | None = None,
    equipNames: EquipNames | None = None,
    equipDefaults: EquipNames | None = None,
    secondEquipNames: EquipNames | None = None,
    secondEquipDefaults: tuple[str | None,
                               str | None, str | None] | None = None,
    characterByFrame: list[tuple[swf.swf.Matrix, int] | None] | None = None,
    characterSprite: sprite.Sprite | None = None,
    characterOffset: tuple[float, float] = (0.0, 0.0),
):
    out = []
    tag_pool = []
    frames_info: list[list[tuple[int, str, FloatMatrix | None]]] = []

    for i, frame in enumerate(anim):
        assembly = []
        frame_entries: list[tuple[int, str, FloatMatrix | None]] = []

        def add_pool(name: str):
            if name not in tag_pool:
                tag_pool.append(name)

        # same depth as the previous frame -> only the transform
        # changes, so the part artwork is reused from reusable/shapes.
        for tag_name, matrix, depth in frame_used_tag_entries(frame, "head"):
            head = _get_cat_head(cat, _head_expression(frame, tag_name), equip,
                                 equipNames, equipDefaults, partDir, palettes, catTree)
            head.applyTransform(matrix)
            assembly.append(sprite.PlacedSprite(
                head, 0, depth, None, f"Whole Head:{tag_name}"))
            add_pool(tag_name)
            frame_entries.append((depth, tag_name, (matrix.xscale, matrix.skew1,
                                 matrix.skew2, matrix.yscale, matrix.xoffset, matrix.yoffset)))

        for part_key in ("body", "arm1", "arm2", "leg1", "leg2", "tail"):
            for tag_name, matrix, depth in frame_used_tag_entries(frame, part_key):
                part = _get_cat_part(cat, part_key, partDir, palettes, catTree)
                part.applyTransform(matrix)
                assembly.append(sprite.PlacedSprite(
                    part, 0, depth, None, f"{PART_LABELS[part_key]}:{tag_name}"))
                add_pool(tag_name)
                frame_entries.append((depth, tag_name, (matrix.xscale, matrix.skew1,
                                     matrix.skew2, matrix.yscale, matrix.xoffset, matrix.yoffset)))

        if second_cat is not None and second_equip is not None and extras_by_frame is not None:
            extras = extras_by_frame[i] if i < len(extras_by_frame) else {}
            _append_second_cat_extras(assembly, frame_entries, second_cat,
                                      partDir, palettes, catTree, second_equip, extras, tag_pool,
                                      secondEquipNames, secondEquipDefaults)

        # A `character` PlaceObject2 places a whole character as a single layer
        # (the symbol it references is only a placeholder).
        if characterSprite is not None and characterByFrame is not None:
            entry = characterByFrame[i] if i < len(characterByFrame) else None
            if entry is not None:
                matrix, depth = entry
                whole = copy.deepcopy(characterSprite)
                if characterOffset != (0.0, 0.0):
                    whole.applyTransform(_translation(characterOffset))
                whole.applyTransform(matrix)
                assembly.append(sprite.PlacedSprite(
                    whole, 0, depth, None, "character"))
                add_pool("character")
                frame_entries.append((depth, "character", (matrix.xscale, matrix.skew1,
                                     matrix.skew2, matrix.yscale, matrix.xoffset, matrix.yoffset)))

        # objects we cannot read are skipped, but stay visible in
        # the cached metadata.
        for skipped in getattr(frame, "skipped", []) or []:
            depth = skipped.get("depth", 0)
            frame_entries.append((
                int(depth) if depth is not None else 0,
                str(skipped.get("tag", "UNSUPPORTED:?")),
                None,
            ))

        frame_entries.sort(key=lambda item: item[0])
        assembly.sort(key=lambda ps: ps.depth if hasattr(ps, 'depth') else 0)
        out.append(sprite.spriteFromPlacedObjects(partDir, catTree, assembly))
        frames_info.append(frame_entries)

    return out, tag_pool, frames_info


def prompt_anim_name(anims: list[str], anim_name: str | None = None, allowPrompt: bool = True) -> str:
    while True:
        if anim_name:
            matches = [a for a in anims if anim_name.lower() in a.lower()]
            if matches:
                return matches[0]
            if not allowPrompt:
                raise SystemExit(
                    f"Animation '{anim_name}' was not found in the available list.")
            logger.warning(
                "Animation '%s' was not found in the available list; prompting again.", anim_name)

        if not allowPrompt:
            raise SystemExit("No animation name was given.")

        anim_name = input("Input Anim name (Empty to exit): ").strip()
        if not anim_name:
            raise SystemExit(0)


def prompt_first_cat(catList: list[CustomCat], catId: str | None = None, allowPrompt: bool = True) -> CustomCat | None:
    """Find a cat by id, falling back to an interactive prompt when allowed."""
    if catId:
        filtered = [cat for cat in catList if catId.lower() in cat.id.lower()]
        if filtered:
            return filtered[0]

        if not allowPrompt:
            logger.error(
                "Requested cat id '%s' is not in the custom cat list.", catId)
            return None

        logger.warning(
            "Requested cat id '%s' is not in the custom cat list; prompting again.", catId)
        return prompt_first_cat(catList)

    if not allowPrompt:
        return None

    catId = input("Input Cat id: ")
    return prompt_first_cat(catList, catId)


def resolve_equipment_names(
    cat: CustomCat,
    mode: str = "default",
    override: EquipNames | None = None,
) -> tuple[EquipNames, bool]:
    """Resolve which items a cat wears, without building any sprite.

    Returns ``(head, face, neck)`` and whether the selection was explicit.  This
    needs no SWF data at all, which is what lets a fully cached animation render
    without touching the source files.
    """
    defaults = getDefaultEquipNames(cat.id)
    mode = (mode or "default").lower()

    if override is not None and any(item is not None for item in override):
        names = tuple(list(override[:3]) + [None] * (3 - len(override[:3])))
        return names, True

    if mode == "none":
        return (None, None, None), True

    if cat.id == "MedicCat":
        logger.warning(
            "MedicCat equipment is disabled because GIF export does not support semi-transparent pixels.")
        if mode == "interactive":
            input("Empty input will continue without selecting her equipment, input anything to proceed selecting her equipment.")
        return (None, None, None), True

    if mode == "default":
        return defaults, False

    if mode == "interactive":
        head_item, face_item, neck_item = defaults
        if head_item or face_item or neck_item:
            if head_item:
                logger.info("'%s' has default head equipment: %s",
                            cat.id, head_item)
            if face_item:
                logger.info("'%s' has default face equipment: %s",
                            cat.id, face_item)
            if neck_item:
                logger.info("'%s' has default neck equipment: %s",
                            cat.id, neck_item)

            if not input("Empty input will proceed using default equipments set, input anything to choose another equipments: "):
                return (head_item, face_item, neck_item), False

        head_item = input("Head equipment (empty for none): ").strip() or None
        face_item = input("Face equipment (empty for none): ").strip() or None
        neck_item = input("Neck equipment (empty for none): ").strip() or None
        return (head_item, face_item, neck_item), True

    return (None, None, None), True


def resolve_equipment(
    partDir: str,
    catpartTree: swf.SWF_Tree,
    cat: CustomCat,
    mode: str = "default",
    override: EquipNames | None = None,
) -> tuple[CatEquipment, EquipNames, bool]:
    """Resolve a cat's equipment sprites and report which items ended up worn."""
    names, explicit = resolve_equipment_names(cat, mode, override)
    return getCatEquipment(partDir, catpartTree, *names), names, explicit


def prompt_equipment(partDir: str, catpartTree: swf.SWF_Tree, cat: CustomCat, mode: str = "default") -> CatEquipment:
    """Backwards-compatible wrapper around :func:`resolve_equipment`."""
    return resolve_equipment(partDir, catpartTree, cat, mode)[0]


def _required_shape_names(
    frames: list[animations.CatFrame],
    cat_id: str,
    equipNames: EquipNames | None,
    equipDefaults: EquipNames | None,
    headExpressions: set[str | None] | None = None,
) -> set[str]:
    """Every reusable/shapes file a cat needs to be drawn across these frames.

    ``headExpressions=None`` collects the head variants the animation actually
    uses (the primary cat); pass ``{None}`` for a second cat rendered through the
    ``other_*`` overlay, whose head is always the default expression.
    """
    names = {reusable.shape_cache_name(cat_id, part)
             for part in reusable.UNEQUIPPED_PARTS}

    if headExpressions is None:
        headExpressions = set()
        for frame in frames:
            for tag in (getattr(frame, "used", {}) or {}):
                if tag == "head":
                    headExpressions.add(frame.face or None)
                elif tag.startswith("head_"):
                    headExpressions.add(tag.removeprefix("head_") or None)

    for expression in headExpressions:
        names.add(reusable.shape_cache_name(
            cat_id, "head", expression=expression,
            equip=equipNames, defaults=equipDefaults))

    return names


def _missing_cache_files(names: set[str]) -> list[str]:
    # A cache built by an older version of the pipeline is discarded here, before
    # the completeness check can trust it.
    reusable.ensure_shape_cache_current()
    return sorted(name for name in names
                  if not os.path.isfile(reusable.shape_cache_path(name)))


def load_cached_animation(
    requested_anim: str,
    cat: CustomCat,
    cat2: CustomCat | None,
    equipNames: EquipNames | None,
    equipDefaults: EquipNames | None,
    equip2Names: EquipNames | None,
    equip2Defaults: EquipNames | None,
) -> tuple[str, list[animations.CatFrame], dict[str, list[animations.CatFrame]]] | None:
    """Load an animation straight from reusable/ when it is completely cached.

    "Completely cached" means the animation metadata *and* every part SVG the render needs
    are present; only then can the source SWFs be left untouched.  Returns
    ``(anim_name, frames, anims)`` or ``None`` when the cache is incomplete.
    """
    payload = reusable.load_anim_cache(requested_anim)
    if payload is None:
        return None

    if not payload.get("complete"):
        logger.debug("Cached animation '%s' is marked incomplete; reading the source SWF.",
                     requested_anim)
        return None

    anim_name = str(payload.get("anim_name") or requested_anim)
    frames = animations.framesFromAnimCache(payload)

    try:
        overlay_mode, _payload = _second_cat_overlay_plan(frames)
    except Exception as error:
        logger.warning("Cached animation '%s' is unusable (%s); falling back to the SWF.",
                       requested_anim, error)
        return None

    required = _required_shape_names(frames, cat.id, equipNames, equipDefaults)
    anims: dict[str, list[animations.CatFrame]] = {}

    if overlay_mode is not None:
        if cat2 is None:
            return None
        if overlay_mode == "parts":
            required |= _required_shape_names(frames, cat2.id, equip2Names, equip2Defaults,
                                              headExpressions={None})
        else:
            required.add(reusable.shape_cache_name(
                cat2.id, "character", equip=equip2Names, defaults=equip2Defaults))
            idle = reusable.load_anim_cache("idleF")
            if idle is None:
                return None
            anims["idleF"] = animations.framesFromAnimCache(idle)

    missing = _missing_cache_files(required)
    if missing:
        logger.info("Reusable cache is incomplete for '%s' (%d missing part(s), e.g. %s); "
                    "reading the source SWF.", anim_name, len(missing), missing[:3])
        return None

    logger.info(
        "Reusable cache fully covers animation '%s'; skipping SWF parsing.", anim_name)
    anims[anim_name] = frames
    return anim_name, frames, anims


def exportCustomCats_interactive(
    ffdecPath: str,
    outdir: str,
    cat_id: str | None,
    requested_anim: str | None = None,
    equip_mode: str = "default",
    equip: EquipNames | None = None,
    cat2_id: str | None = None,
    equip2_mode: str = "default",
    equip2: EquipNames | None = None,
    generate_gif: bool = True,
):
    palettes = palette.loadPalettes("./data/textures/palette.png")

    cat_list = getCustomCats()
    cat = prompt_first_cat(cat_list, cat_id, allowPrompt=not cat_id)
    if cat is None:
        raise SystemExit(
            f"Cat '{cat_id}' was not found in the custom cat list.")
    logger.info("Selected primary cat '%s' for interactive export", cat.id)

    equip1Names, equip1Explicit = resolve_equipment_names(
        cat, equip_mode, equip)
    equip1CacheNames = None if not equip1Explicit else equip1Names
    equip1Defaults = getDefaultEquipNames(cat.id)

    # --- fully cached? then never touch the source SWFs ---------------------
    cached = None
    if requested_anim:
        cat2ForCache = prompt_first_cat(
            cat_list, cat2_id, allowPrompt=False) if cat2_id else None
        equip2CacheNames = None
        equip2Defaults = None
        if cat2ForCache is not None:
            equip2Names, equip2Explicit = resolve_equipment_names(
                cat2ForCache, equip2_mode, equip2)
            equip2CacheNames = None if not equip2Explicit else equip2Names
            equip2Defaults = getDefaultEquipNames(cat2ForCache.id)

        # An animation without a second character needs no cat2 id at all, so the
        # check is retried once the cache told us whether one is involved.
        cached = load_cached_animation(
            requested_anim, cat, cat2ForCache,
            equip1CacheNames, equip1Defaults, equip2CacheNames, equip2Defaults)

    if cached is not None:
        anim_name, cat_anim, anims = cached
        secondCat = SecondCatResolver(cat_list, cat2_id, equip2_mode, equip2)
        frames = render_animation(
            cat, None, palettes, None, cat_anim, anim_name, anims,
            CatEquipment(), equip1CacheNames, equip1Defaults, secondCat)
    else:
        partDir = ffdec.exportShapesIfNeeded(ffdecPath, catpart.CATPARTS_SWF)
        catpartTree = swf.getSwfTree(catpart.CATPARTS_SWF)
        anims = animations.getCatAnims()
        anim_list = list(anims.keys())

        anim_name = requested_anim.strip() if requested_anim else ""
        anim_name = prompt_anim_name(
            anim_list, anim_name, allowPrompt=not anim_name)
        cat_anim = anims[anim_name]
        logger.info("Loading animation '%s' with %d frames",
                    anim_name, len(cat_anim))

        catEquip = getCatEquipment(partDir, catpartTree, *equip1Names)

        # the second cat is asked for at the moment the animation
        # places it, and the answer is reused for the rest of the run.
        secondCat = SecondCatResolver(cat_list, cat2_id, equip2_mode, equip2)

        frames = render_animation(
            cat, partDir, palettes, catpartTree, cat_anim, anim_name, anims,
            catEquip, equip1CacheNames, equip1Defaults, secondCat)

    os.makedirs(outdir, exist_ok=True)
    logger.info("Saving exported frames for '%s' animation '%s' to '%s'",
                cat.id, anim_name, outdir)
    save_cat_output(outdir, cat.id, anim_name,
                    frames, generate_gif=generate_gif)


def exportCustomCats_batch(
    ffdecPath,
    anim_name: str,
    outdir,
    cat2_id: str | None = None,
    equip2_mode: str = "default",
    equip2: EquipNames | None = None,
    generate_gif: bool = True,
):
    """批量导出所有猫（使用各自的 class_anis 动画）"""
    partDir = ffdec.exportShapesIfNeeded(ffdecPath, catpart.CATPARTS_SWF)
    palettes = palette.loadPalettes("./data/textures/palette.png")
    catpartTree = swf.getSwfTree(catpart.CATPARTS_SWF)
    anims = animations.getCatAnims()
    cat_list = getCustomCats()

    batch_cats = [c for c in cat_list if c.id in BATCH_CAT_NAMES]

    outdir = os.path.join(outdir, "batch")
    if os.path.isdir(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir, exist_ok=True)

    # Asked at most once for the whole batch, then reused for every cat.
    secondCat = SecondCatResolver(
        cat_list, cat2_id, equip2_mode, equip2)

    count = 0
    for cat in batch_cats:
        if anim_name is None or not any(anim_name.lower() == a.lower() for a in anims):
            new_name = f"{cat.id.strip("Cat").strip("cat")}IdleF"
            if any(new_name.lower() == a.lower() for a in anims):
                logging.warning(
                    f"Cat {cat.id}: animation '{anim_name}' not found, using '{new_name}'")
                anim_name = new_name
            else:
                logging.warning(
                    f"Cat {cat.id}: animation '{anim_name}' not found, using 'idleF'")
                anim_name = "idleF"
        cat_anim = anims[anim_name]

        catEquip, equipNames, equipExplicit = resolve_equipment(
            partDir, catpartTree, cat, "default")

        try:
            frames = render_animation(
                cat, partDir, palettes, catpartTree, cat_anim, anim_name, anims,
                catEquip, None if not equipExplicit else equipNames,
                getDefaultEquipNames(cat.id), secondCat)
            save_cat_output(outdir, cat.id, anim_name, frames,
                            generate_gif=generate_gif)
            count += 1
            logging.info(f"Exported {cat.id}")
        except Exception as e:
            logging.error(f"Failed to export {cat.id}: {e}")
            continue
    return count
