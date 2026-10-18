# this file does *magic* :)

from .catgen import catparts as catpart
from .catgen import swf_tree as swf
from .catgen import sprite
from .catgen import animations
from .catgen import palette
from .catgen import reusable
from src.import_paths import *

from .util import parse_gon as gon
from .util import ffdec_tools as ffdec
from .util import svg_tools
from .util import svg_tools as svg

from . import items

import copy
import io
import os
import shutil
import logging
from typing import Any, Iterable, Iterator, Mapping, Sequence, overload

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

#: Where the game anchors the second cat relative to the artwork `character`
#: stands in for.  `character` references a runtime-only placeholder, so its
#: matrix has to be applied to our whole-cat sprite with this correction; drawn
#: straight on top of the rest pose the second cat lands about 0.6 cat bodies too
#: low and 0.1 too far left.
#:
#: The placeholder is positioned in the canonical rest-pose space, which is why
#: the animation's own rest displacement is *not* added on top: `terminatorPunchF`
#: carries exactly -48 in its rest offset, and letting both through would shift its
#: second cat twice as far as its `other_*` parts (the explicit ground truth) say.
CHARACTER_LAYER_OFFSET = (13.0, -48.0)

#: how far (in user units) a nearly transparent pixel may sit from the solid core
#: and still count as an antialiased edge rather than a rendering artefact
BOUNDS_HALO = 4.0

#: delay of every exported GIF frame; ImageMagick counted this in 1/100 s, so
#: 2 ticks == 20 ms == one 50 fps frame.
GIF_FRAME_DURATION_MS = 20

_FACE_POSE_CACHE: dict[str, dict[str, Any]] | None = None
_HEAD_FACE_CACHE: dict[tuple[Any, ...], "CatFace"] = {}
_HEAD_POSE_CACHE: dict[tuple[Any, ...], sprite.Sprite] = {}
_COMPONENT_CACHE: dict[tuple[Any, ...], sprite.Sprite] = {}
_CHARACTER_CACHE: dict[str, sprite.Sprite] = {}
_ITEM_SPRITE_CACHE: dict[tuple[Any, ...], sprite.Sprite] = {}

# Type
FloatMatrix = tuple[float, float, float, float, float, float]

#: A cat's equipment is exactly the three worn armor slots.  Nothing else is
#: ever part of a cat: a weapon and a trinket are standalone parts that the
#: animation places, and only the animation metadata says whether a cat has any.
EQUIP_SLOTS: tuple[str, str, str] = ("head", "face", "neck")

#: the two handheld slots.  A cat holds no such thing by itself; the slots only
#: name the parts an animation's ``weapon`` / ``trinket`` objects refer to.
HANDHELD_SLOTS: tuple[str, str] = ("weapon", "trinket")

#: worn armor, in slot order
EquipNames = tuple[str | None, str | None, str | None]

#: a weapon and a trinket, in slot order
HandheldNames = tuple[str | None, str | None]

#: item a cat's animation shows when its character file names no trinket
DEFAULT_TRINKET = "Chicken"

#: spellings that mean "nothing in this slot"
NONE_TOKENS = {"none", "null", "-"}


def getCatTree(catTree: swf.SWF_Tree, name: str) -> swf.SWF_Tree.SpriteNode:
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

    faces = gon.parse_gon(CATGEN_GON).get("faces", {})
    if not isinstance(faces, dict):
        faces = {}

    cleaned: dict[str, dict[str, Any]] = {}
    for name, pose in faces.items():
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

    #: sprite symbol the mouth artwork comes from; every cat so far uses the
    #: default one, and a character file may override it
    mouth_sprite = "CatMouth"

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


def _as_slots(values: Sequence[str | None], slots: Sequence[str]) -> list[str | None]:
    """Normalise a selection to one entry per slot in ``slots``."""
    items: list[str | None] = list(values)[:len(slots)]
    while len(items) < len(slots):
        items.append(None)
    return items


def _normalise_tokens(names: Sequence[str | None]) -> list[str | None]:
    """Turn blanks and the ``none`` spellings of a selection into ``None``."""
    items: list[str | None] = []
    for item in names:
        token = "" if item is None else str(item).strip()
        items.append(None if not token or token.lower()
                     in NONE_TOKENS else token)
    return items


def normalise_equipment(names: Sequence[str | None] | None) -> EquipNames | None:
    """Normalise an equipment selection to exactly the three armor slots.

    ``None`` stays ``None``, meaning "the cat's own default".  Blank entries and
    the ``none`` spelling mean the cat wears nothing there.
    """
    if names is None:
        return None

    head, face, neck = _as_slots(_normalise_tokens(names), EQUIP_SLOTS)
    return (head, face, neck)


class CatEquipment:
    """The three worn armor slots of one cat, as sprites.

    Only the armor lives here: it is drawn *on* the cat, so it belongs to the
    cat and is part of each cached cat part's name.  A weapon or a trinket is not
    part of a cat at all -- see :class:`ItemPool`.
    """

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
    if part.data is None:
        raise RuntimeError(f"cat component '{node_name}' has no SVG data")
    palette.applyPalette(
        palette.loadPalettes("./data/textures/palette.png")[cat.palette], part.data)
    _COMPONENT_CACHE[key] = copy.deepcopy(part)
    return copy.deepcopy(part)


def _mouth_svg_data(component: sprite.Sprite) -> svg_tools.SvgData:
    """The SVG document of a mouth sprite, which every mouth layer must have."""
    data = component.data
    if data is None:
        raise RuntimeError("mouth component has no SVG data")
    return data


def mirror_sprite_x(component: sprite.Sprite) -> None:
    """Mirror a part's artwork horizontally, keeping its placement transform.

    The placement from `CatHeadPlacements` is the outermost `<g>` of the sprite.
    Overwriting that wrapper's transform with the mirror throws the placement
    away: for the mouth that lost its `y +7.5` offset, so a left-looking face drew
    the mouth 7.5 units too high.  The mirror therefore goes *inside* the
    placement wrapper, leaving the placement to apply on top of it.
    """
    data = component.data
    if data is None or data.data is None:
        return

    root = data.data
    if not root.subcomponents:
        return

    placement = root.subcomponents[0]
    if placement.getTagname() != "g":
        return

    placement.subcomponents = [svg_tools.SvgData.Composite(
        '<g transform="matrix(-1.0, 0.0, 0.0, 1.0, 0.0, 0.0)">\n',
        placement.subcomponents,
    )]


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
    expression = animations.headTagExpression(tagName)
    if expression:
        return expression
    return frame.face or None


def tag_family_prefixes(key: str) -> tuple[str, ...]:
    """Every tag prefix that belongs to ``key``'s family.

    Normally that is just ``key_``; the head is special because its layers also
    arrive as ``headblend_<pose>``.
    """
    if key == "head":
        return animations.HEAD_TAG_FAMILIES
    return (key + "_",)


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

    The weapon and the trinket are *not* part of this sprite.  Their placement
    changes with every animation frame, which the part file name cannot express,
    so they are added as their own frame layers instead (see
    :func:`_animation_item_plan_entries`).
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

    Cached as ``<cat-id>-character<-表情><-装备>.svg``.  The cached artwork is the
    cat's canonical rest pose (``idleF`` frame 0), which is also the space the
    `character` placeholder's matrix is expressed in -- see
    :data:`CHARACTER_LAYER_OFFSET` and :func:`_assemble_frames_for_first_cat`.

    A part file name can only describe the armor, so this sprite never contains
    a handheld item.
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

    Kept as the documented invariant of the rest pose; the `character` layer no
    longer needs it, because the placeholder's matrix is already expressed in the
    canonical rest-pose space.
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
        cat.mouth_sprite,
    )


def makeCatHead(cat: CustomCat, partDir: str, palettes: list[palette.Palette], catTree: swf.SWF_Tree) -> tuple[swf.swf.Matrix | None, CatFace]:
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

    base_name = cat.mouth_sprite
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

    if (placements.mouth != None):
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

    _HEAD_FACE_CACHE[key] = copy.deepcopy(face)
    return (placements.head.xform, copy.deepcopy(face))


ITEM_DICT = None


def getItem(name: str) -> items.Item:
    """Look an item up by its ``.gon`` id, loading the item table on first use."""
    global ITEM_DICT

    if (ITEM_DICT == None):
        ITEM_DICT = items.getItemDict()

    try:
        return ITEM_DICT[name]
    except KeyError:
        raise KeyError(
            f"Unknown item '{name}'. Use an id from data/data/items, "
            f"a <slot> name from {CAT_MINIBOSSES_GON}, or 'none'.") from None


class ItemPool:
    """The standalone weapon/trinket parts an animation draws.

    An item is not part of a cat: it is cached on its own as
    ``reusable/shapes/<item name>.svg`` and looked up by name, so two cats
    holding the same weapon share one cached part, and a cat's own parts never
    change when only its weapon does.

    Which items a cat *may* show comes from three places, in order: an explicit
    request (``--weapon`` / ``--trinket``), then the cat's character file, then
    :data:`DEFAULT_TRINKET` for a trinket.  Which of them is actually drawn, and
    where, is decided by the animation alone: a slot whose animation has no
    object is not drawn, and every object the animation places for a slot is
    drawn, however many depths it uses.
    """

    def __init__(self, items_by_slot: Mapping[str, str] | None = None):
        #: slot name -> item name, e.g. ``{"weapon": "ButcherHook"}``
        self._items: dict[str, str] = {
            slot: str(name) for slot, name in (items_by_slot or {}).items() if name
        }

    @classmethod
    def for_cat(cls, catId: str,
                handheld: Sequence[str | None] | None = None) -> "ItemPool":
        """The pool of one cat, without looking at any animation yet.

        ``handheld`` is an explicit ``weapon;trinket`` request.  ``None`` means
        "not requested at all": the cat's character file then decides, including
        the :data:`DEFAULT_TRINKET` fallback.  A request always overrides the
        file, and a ``None`` entry inside it leaves that slot empty.
        """
        if handheld is None:
            return cls({slot: name for slot, name in zip(HANDHELD_SLOTS,
                                                         getDefaultHandheldNames(catId))
                        if name})

        requested = _as_slots(handheld, HANDHELD_SLOTS)
        items: dict[str, str] = {}
        for index, slot in enumerate(HANDHELD_SLOTS):
            token = requested[index]
            if token is None or str(token).strip().lower() in NONE_TOKENS:
                continue
            items[slot] = str(token).strip()

        return cls(items)

    def confirmed_by(self, anim: Sequence[animations.CatFrame]) -> "ItemPool":
        """This pool restricted to the slots ``anim`` actually places.

        A weapon or a trinket the animation never draws is not part of the
        render at all -- the animation decides, not the equipment list.
        """
        drawn: set[str] = set()
        for frame in anim:
            drawn |= set(getFrameItemTags(frame))

        return self._confirmed_by(drawn)

    def confirmed_by_frames(
        self,
        frames_info: Sequence[Sequence["FrameEntry"]],
    ) -> "ItemPool":
        """Like :func:`confirmed_by`, for already-extracted frame metadata."""
        drawn = {str(tag)
                 for frame in frames_info for _depth, tag, _matrix, _cxform in frame}
        return self._confirmed_by(drawn)

    def _confirmed_by(self, drawn: set[str]) -> "ItemPool":
        return ItemPool({slot: name for slot, name in self._items.items()
                         if slot in drawn})

    def by_slot(self) -> dict[str, "ItemPool"]:
        """``slot -> single-item pool``, for callers that walk slot by slot."""
        return {slot: ItemPool({slot: itemName})
                for slot, itemName in self._items.items()}

    def item_name(self, slot: str) -> str | None:
        return self._items.get(slot)

    def is_empty(self) -> bool:
        return not self._items

    def cache_names(self) -> set[str]:
        """The ``reusable/shapes`` files this pool is drawn from."""
        return {reusable.item_cache_name(itemName)
                for itemName in self._items.values()}

    def sprite(self, slot: str) -> sprite.Sprite:
        """Artwork of the item in ``slot``, through the shared item cache.

        The caller gets its own copy and may transform it freely.
        """
        itemName = self._items[slot]
        key = (slot, itemName)
        cached = _ITEM_SPRITE_CACHE.get(key)
        if cached is None:
            cached = items.getItemSprite(slot, itemName)
            _ITEM_SPRITE_CACHE[key] = cached

        return cached

    def __repr__(self) -> str:
        return f"ItemPool({self._items!r})"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, ItemPool) and other._items == self._items

    def __hash__(self) -> int:
        return hash(tuple(sorted(self._items.items())))


def getCatEquipment(partDir: str, catTree: swf.SWF_Tree, head: str | None, face: str | None,
                    neck: str | None) -> CatEquipment:
    """The worn armor of one cat, as sprites.

    A weapon and a trinket are deliberately not accepted here: they are not part
    of a cat, and the animation -- not this record -- decides whether they are
    drawn.
    """
    out = CatEquipment()

    if (head != None):
        idata = getItem(head)
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
        idata = getItem(face)
        frame = idata.frame - 1

        fronts = getCatTree(catTree, "FaceItemF").frames[frame].objs
        backs = getCatTree(catTree, "FaceItemB").frames[frame].objs

        out.face_front = sprite.spriteFromPlacedObjects(
            partDir, catTree, fronts)
        out.face_back = sprite.spriteFromPlacedObjects(partDir, catTree, backs)

    if (neck != None):
        idata = getItem(neck)
        frame = idata.frame - 1

        neckFronts = getCatTree(catTree, "NeckItemF")
        neckBacks = getCatTree(catTree, "NeckItemB")

        out.neck_front = sprite.spriteFromPlacedObjects(
            partDir, catTree, neckFronts.frames[frame].objs)
        out.neck_back = sprite.spriteFromPlacedObjects(
            partDir, catTree, neckBacks.frames[frame].objs)

    return out


def _characterEquipment(catId: str) -> dict[str, Any]:
    """The ``equipment`` block of a cat's character file, or an empty mapping."""
    equipment_data = gon.parse_gon(
        CAT_MINIBOSSES_GON) | gon.parse_gon(TERMINATOR_GON)

    catId = namefix.get(catId) or catId
    equipments = equipment_data.get(catId, {}).get("equipment") or {}
    return equipments if isinstance(equipments, dict) else {}


def getDefaultEquipNames(catId: str) -> EquipNames:
    """The worn armor a cat's character file asks for, one entry per slot.

    This is the raw ``equipment`` block: no fallback is applied here, so an
    explicit selection can still tell "the file says nothing" from "the game
    would show a chicken".
    """
    equipments = _characterEquipment(catId)

    head: str | None = equipments.get("head", None)
    face: str | None = equipments.get("face", None)
    neck: str | None = equipments.get("neck", None)

    return (head, face, neck)


def getDefaultHandheldNames(catId: str) -> HandheldNames:
    """The weapon and the trinket a cat's character file asks for.

    Still separate from the equipment, with the trinket fallback the game
    applies: a cat whose file names no trinket is shown with a chicken.
    """
    equipments = _characterEquipment(catId)

    weapon: str | None = equipments.get("weapon", None)
    trinket: str = equipments.get("trinket", DEFAULT_TRINKET)

    return (weapon, trinket)


def getFrameItemTags(frame: animations.CatFrame) -> dict[str, list[animations.Placement]]:
    """Placements of the animation's handheld objects in one frame.

    The animation SWF names these objects ``weapon`` and ``trinket``; both the
    transform and the depth they carry are the ones the game draws them with, so
    they are used as-is.  A frame may place several objects for one slot, at
    different depths, and every one of them is returned.
    """
    used = getattr(frame, "used", {}) or {}
    out: dict[str, list[animations.Placement]] = {}

    for slot in HANDHELD_SLOTS:
        values = used.get(slot)
        if not values:
            continue
        out[slot] = sorted((animations.asPlacement(v) for v in values),
                           key=lambda placement: placement[1])

    return out


# Hand-tuned head layer order, listed from the bottom (drawn first) to the top
# (drawn last).  Each entry gets an increasing depth, so a layer listed later
# covers the ones before it.
HEAD_LAYER_ORDER_FRONT = (
    "neckItem",   # Neck Item
    "lear",       # Left Ear
    "rear",       # Right Ear
    "head",       # Head
    "mouth",      # Mouth
    "leye",       # Left Eye
    "lbrow",      # Left Eyebrow
    "reye",       # Right Eye
    "rbrow",      # Right Eyebrow
    "headItem",   # Head Item
    "faceItem",   # Face Item
)

HEAD_LAYER_ORDER_BACK = (
    "faceItem",   # Face Item
    "leye",       # Left Eye
    "lbrow",      # Left Eyebrow
    "reye",       # Right Eye
    "rbrow",      # Right Eyebrow
    "mouth",      # Mouth
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
def headWithPose(cat: CustomCat, partDir: str, catTree: swf.SWF_Tree, equipment: CatEquipment, face: CatFace, pose: FacePose, palettes: list[palette.Palette]) -> sprite.Sprite:
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
    if head.data is None:
        raise RuntimeError("CatHead sprite has no SVG data")
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
        if (pose.offset[0] < 0):
            mirror_sprite_x(face.mouth_closed)

        face.mouth_closed.applyTransform(onlyoffset)
        assembly.append(sprite.PlacedSprite(face.mouth_closed,
                        0, depths["mouth"], None, "Mouth"))
    elif (pose.mouth == "open" and face.mouth_open != None):
        if (pose.offset[0] < 0):
            mirror_sprite_x(face.mouth_open)

        face.mouth_open.applyTransform(onlyoffset)
        assembly.append(sprite.PlacedSprite(face.mouth_open, 0,
                        depths["mouth"], None, "Mouth"))
    elif (pose.mouth == "smile" and face.mouth_smile != None):
        if (pose.offset[0] < 0):
            mirror_sprite_x(face.mouth_smile)

        face.mouth_smile.applyTransform(onlyoffset)
        assembly.append(sprite.PlacedSprite(face.mouth_smile, 0,
                        depths["mouth"], None, "Mouth"))
    elif (pose.mouth != "closed" and pose.mouth != "open" and pose.mouth != "smile"):
        raise RuntimeError("Weird mouth state " + pose.mouth)

    out = sprite.spriteFromPlacedObjects(partDir, catTree, assembly)
    _HEAD_POSE_CACHE[pose_key] = copy.deepcopy(out)
    return copy.deepcopy(out)


def _animation_item_plan_entries(
    partDir: str,
    catTree: swf.SWF_Tree,
    frame: animations.CatFrame,
    pool: ItemPool,
) -> list[dict[str, Any]]:
    """Plan entries for every handheld object the frame places.

    The animation's own ``weapon`` / ``trinket`` objects define where each one is
    drawn and at which depth, so they are ordinary frame layers: a frame that
    does not place them shows nothing, and a frame that places several draws all
    of them.  ``pool`` only says which item artwork a slot refers to.
    """
    entries: list[dict[str, Any]] = []

    for slot in HANDHELD_SLOTS:
        if not pool.item_name(slot):
            continue

        template = pool.sprite(slot)
        for placement in getFrameItemTags(frame).get(slot, []):
            entries.append(_frame_plan_entry(
                f"{slot.capitalize()} Item", placement[1], placement[0], template,
                placement[2]))

    return entries


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
    if probe.data is None:
        raise RuntimeError("cannot measure a sprite without SVG data")
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
        bbox: tuple[float, float, float, float] | None = alpha.getbbox()
        if bbox is None:
            return (0.0, 0.0, 0.0, 0.0)

        def _alpha_core(value: Any) -> int:
            return 255 if int(value) > BOUNDS_ALPHA_THRESHOLD else 0

        core = alpha.point(_alpha_core).getbbox()
        if core is not None:
            # keep the antialiased edge, but clamp it to a halo around the solid
            # core so a stray faint pixel cannot stretch the frame
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


def set_svg_canvas(frame_sprite: sprite.Sprite, width: float, height: float) -> None:
    """Pin the exported SVG root to the shared animation canvas."""
    if frame_sprite.data is None:
        return

    root = frame_sprite.data.data
    if "<svg" not in root.header:
        return

    root.setField("width", f"{width}px")
    root.setField("height", f"{height}px")
    # 1 user unit == 1 pixel, with the canvas origin at the top-left corner.
    root.setField("viewBox", f"0 0 {width} {height}")


def _render_gif_frame(svg_data: str, background: Any, resolution: float) -> PILImage.Image:
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


def save_cat_output(outfolder: str, cat_id: str, anim_name: str, frames: list[sprite.Sprite],
                    scaling: float = 3.0, generate_gif: bool = True) -> None:
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

    def exported_frames() -> Iterator[tuple[int, str]]:
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
            logging.warning("No frames to export for '%s-%s'",
                            cat_id, anim_name)
            return

        index, svgData = first
        resolution = MEASURE_DPI * scaling

        def gif_frames() -> Iterator[PILImage.Image]:
            # The first frame doubles as the still preview PNG, as before.
            first_frame = _render_gif_frame(svgData, bg, resolution)
            first_frame.save(os.path.join(assets_path, f"{index}.png"))
            yield first_frame

            del first_frame
            for _i, next_svg in source:
                yield _render_gif_frame(next_svg, bg, resolution)

        logging.info("Assembling GIF...")
        _write_gif(gif_frames(), outfile)


def _write_gif(frames: Iterable[PILImage.Image], outfile: str) -> None:
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


#: One layer of a frame: its depth, tag, transform (``None`` for a skipped tag)
#: and the serialised SWF color transform it carries, if any.
FrameEntry = tuple[int, str, "FloatMatrix | None", "dict | None"]


def is_default_placement(value: Any) -> bool:
    """True for a `CatFrame` placeholder value rather than a real placement.

    `CatFrame` initialises every part to an identity matrix at depth 0, and depth
    0 is not a valid SWF display-list depth, so such a value always means "this
    frame does not place the part".  Treating it as a placement resurrects parts
    that a `RemoveObject2` had hidden.
    """
    if not (isinstance(value, tuple) and len(value) in (2, 3)):
        return True

    matrix, depth = value[0], value[1]
    if matrix is None:
        return True

    return (depth == 0
            and getattr(matrix, "xscale", 1.0) == 1.0
            and getattr(matrix, "yscale", 1.0) == 1.0
            and getattr(matrix, "skew1", 0.0) == 0.0
            and getattr(matrix, "skew2", 0.0) == 0.0
            and getattr(matrix, "xoffset", 0.0) == 0.0
            and getattr(matrix, "yoffset", 0.0) == 0.0)


def frame_used_placements(frame: animations.CatFrame, key: str) -> list[animations.Placement]:
    """Every placement of ``key`` (and of its variant families) in one frame."""
    used = getattr(frame, "used", {}) or {}
    results: list[animations.Placement] = []

    # collect exact key entries
    if key in used:
        results += [animations.asPlacement(v) for v in used[key]]

    # collect variant keys like 'head_back', 'head_default', 'headblend_*', etc.
    prefixes = tag_family_prefixes(key)
    for k, vals in used.items():
        if k.startswith(prefixes):
            results += [animations.asPlacement(v) for v in vals]

    # fallback to single attribute on the CatFrame (legacy)
    if not results:
        value = getattr(frame, key, None)
        if not is_default_placement(value):
            results = [animations.asPlacement(value)]

    # return entries sorted by depth (ascending)
    return sorted(results, key=lambda item: item[1])


def frame_used_value(frame: animations.CatFrame, key: str) -> list[tuple[swf.swf.Matrix, int]]:
    """Like :func:`frame_used_placements`, dropping the color transform."""
    return [(placement[0], placement[1]) for placement in frame_used_placements(frame, key)]


def frame_used_tag_placements(frame: animations.CatFrame, key: str) -> list[tuple[str, animations.Placement]]:
    """Like :func:`frame_used_placements`, keeping the tag each placement came from."""
    used = getattr(frame, "used", {}) or {}
    results: list[tuple[str, animations.Placement]] = []
    seen: set[tuple[str, int]] = set()

    if key in used:
        for placement in used[key]:
            placement = animations.asPlacement(placement)
            marker = (key, placement[1])
            if marker not in seen:
                seen.add(marker)
                results.append((key, placement))

    prefixes = tag_family_prefixes(key)
    for tag_name, values in used.items():
        if tag_name.startswith(prefixes):
            for placement in values:
                placement = animations.asPlacement(placement)
                marker = (tag_name, placement[1])
                if marker not in seen:
                    seen.add(marker)
                    results.append((tag_name, placement))

    if not results:
        value = getattr(frame, key, None)
        if not is_default_placement(value):
            results.append((key, animations.asPlacement(value)))

    return sorted(results, key=lambda item: item[1][1])


def frame_used_tag_entries(frame: animations.CatFrame, key: str) -> list[tuple[str, swf.swf.Matrix, int]]:
    """Like :func:`frame_used_tag_placements`, dropping the color transform."""
    return [(tag, placement[0], placement[1])
            for tag, placement in frame_used_tag_placements(frame, key)]


def frame_head_layers(frame: animations.CatFrame) -> list[tuple[str, animations.Placement]]:
    """The head layers a frame actually shows, as ``(tag, placement)`` pairs.

    A ``headblend_<pose>`` tag is not a cross-fade.  The SWF drives the fade with
    the blend's alpha, but this pipeline renders single frames, where a
    half-faded face is simply a wrong face -- so the blend's color transform is
    dropped and the pose it names is drawn as the head, at the head layer's own
    placement.

    A *specific* ``head_<pose>`` tag outranks the blend: while the SWF is
    cross-fading it keeps the generic ``head`` tag as the source, so the blend is
    the pose to show, and the moment the artist moves the head tag to
    ``head_<pose>`` that pose is the destination and wins outright.

    A blend with no head layer to replace draws nothing.
    """
    placements = frame_used_tag_placements(frame, "head")
    heads = [(tag, placement) for tag, placement in placements
             if not animations.isHeadBlendTag(tag)]
    blends = [tag for tag, _placement in placements if animations.isHeadBlendTag(tag)]

    if not heads or not blends:
        return heads

    if any(animations.headTagExpression(tag) for tag, _placement in heads):
        return heads

    return [(blends[-1], heads[-1][1])]


def _frame_plan_entry(name: str, depth: float, matrix: swf.swf.Matrix | None, sprite_template: sprite.Sprite, cxform: swf.swf.CXFORM | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "depth": depth,
        "matrix": matrix,
        "cxform": cxform,
        "sprite_template": sprite_template,
    }


def _build_frame_plan(
    cat: CustomCat,
    partDir: str,
    palettes: list[palette.Palette],
    catTree: swf.SWF_Tree,
    equip: CatEquipment,
    frame: animations.CatFrame,
    extras: dict[str, animations.Placement] | None = None,
    *,
    depth_sort: bool = True,
    equipNames: EquipNames | None = None,
    equipDefaults: EquipNames | None = None,
    pool: ItemPool | None = None,
) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []

    for tag_name, placement in frame_head_layers(frame):
        plan.append(_frame_plan_entry(
            f"Whole Head:{tag_name}",
            placement[1],
            placement[0],
            _get_cat_head(cat, _head_expression(frame, tag_name), equip, equipNames,
                          equipDefaults, partDir, palettes, catTree),
            placement[2],
        ))

    for part_key, label in (("body", "Body"), ("arm1", "Right Arm"), ("arm2", "Left Arm"),
                            ("leg1", "Right Leg"), ("leg2", "Left Leg"), ("tail", "Tail")):
        for placement in frame_used_placements(frame, part_key):
            plan.append(_frame_plan_entry(
                label, placement[1], placement[0],
                _get_cat_part(cat, part_key, partDir, palettes, catTree),
                placement[2]))

    # The weapon and the trinket are placed by the animation, at its own depth.
    if pool is not None:
        plan += _animation_item_plan_entries(partDir, catTree, frame, pool)

    if extras:
        for name, placement in extras.items():
            matrix, depth, cxform = animations.asPlacement(placement)
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
                f"Extra {name}", depth, matrix, sprite_template, cxform))

    if depth_sort:
        plan.sort(key=lambda item: item["depth"])
    return plan


def _instantiate_frame_plan(plan: list[dict[str, Any]]) -> list[sprite.PlacedSprite]:
    assembly: list[sprite.PlacedSprite] = []
    for entry in plan:
        part = copy.deepcopy(entry["sprite_template"])
        # the SWF color transform tints the part and carries its alpha
        part.applyTransform(entry.get("cxform"))
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
    extras: dict[str, animations.Placement] | None = None,
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


def extract_anim_tag_pool_and_frames_info(anim: list[animations.CatFrame]) -> tuple[list[str], list[list["FrameEntry"]]]:
    """Collect the per-frame tag metadata once, without depending on whether a second cat is being rendered.

    Entries are ``(depth, tag, transform, colorTransform)``; ``transform`` is
    ``None`` for the "UNSUPPORTED:<tag>" records produced for skipped tags, and
    ``colorTransform`` is the serialised SWF color transform when the tag has one.
    """
    tag_pool: list[str] = []
    frames_info: list[list[FrameEntry]] = []

    for frame in anim:
        used = getattr(frame, "used", {}) or {}
        frame_entries: list[FrameEntry] = []

        for tag_name, values in used.items():
            if tag_name not in tag_pool:
                tag_pool.append(tag_name)
            for value in values:
                matrix, depth, cxform = animations.asPlacement(value)
                frame_entries.append((
                    int(depth), tag_name, _matrix_to_float_matrix(matrix),
                    animations.colorTransformToCache(cxform)))

        for key in ("head", "body", "arm1", "arm2", "leg1", "leg2", "tail"):
            if key in used or any(k.startswith(tag_family_prefixes(key)) for k in used):
                continue
            value = getattr(frame, key, None)
            if is_default_placement(value):
                continue
            matrix, depth, cxform = animations.asPlacement(value)
            if key not in tag_pool:
                tag_pool.append(key)
            frame_entries.append((
                int(depth), key, _matrix_to_float_matrix(matrix),
                animations.colorTransformToCache(cxform)))

        # keep a trace of every object we had to skip.
        for skipped in getattr(frame, "skipped", []) or []:
            depth = skipped.get("depth", 0)
            frame_entries.append((
                int(depth) if depth is not None else 0,
                str(skipped.get("tag", "UNSUPPORTED:?")),
                None,
                None,
            ))

        frame_entries.sort(key=lambda item: item[0])
        frames_info.append(frame_entries)

    return tag_pool, frames_info


def _write_anim_metadata(
    anim_name: str,
    tag_pool: list[str],
    frames_info: list[list["FrameEntry"]],
    complete: bool = True,
    overlay_mode: str | None = None,
    items: ItemPool | None = None,
) -> dict[str, Any]:
    """Cache one animation's metadata under reusable/anims/<anim-name>.json.

    ``complete`` says whether the file describes the whole animation, including
    the second character.  Only complete files may be used to render without
    reading the source SWF, and an incomplete write never replaces a complete one.

    ``items`` records which standalone weapon/trinket parts the animation places.
    Those are confirmed *by* the metadata: a slot that never appears in
    ``tag_pool`` is written without an entry, so a cached render draws exactly
    what the animation draws.
    """
    payload: dict[str, Any] = {
        "anim_name": anim_name,
        "overlay_mode": overlay_mode,
        "complete": bool(complete),
        "metadata_version": reusable.ANIM_CACHE_VERSION,
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
        for depth, tag_name, matrix, cxform in frame:
            entry: dict[str, Any] = {"depth": int(depth), "tag": tag_name}
            if matrix is None:
                entry["transform"] = None
                entry["note"] = "skipped"
            else:
                entry["transform"] = [float(v) for v in matrix]
            if cxform is not None:
                entry["colorTransform"] = cxform
            entries.append(entry)
        frames_obj[str(i)] = entries

    payload["tag_pool"] = list(tag_pool)
    payload["frames"] = frames_obj
    if items is not None:
        drawn = items.confirmed_by_frames(frames_info)
        if not drawn.is_empty():
            payload["items"] = {slot: drawn.item_name(slot)
                                for slot in sorted(drawn.by_slot())}

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
        catId: str | None,
        equipMode: str,
        equip: Sequence[str | None] | None,
    ):
        self.catList = catList
        self.id = catId
        self.equipMode = equipMode
        self.equip = equip

        self._resolved: tuple[CustomCat, EquipNames,
                              bool, EquipNames] | None = None
        self._attempted = False

    def resolve(self) -> tuple[CustomCat, EquipNames, bool, EquipNames] | None:
        if self._attempted:
            return self._resolved

        self._attempted = True

        cat2 = prompt_first_cat(self.catList, self.id,
                                allowPrompt=not self.id)
        if cat2 is None:
            logger.warning(
                "No cat matched '%s'; the second character will be skipped.", self.id)
            return None

        names, explicit = resolve_equipment_names(
            cat2, self.equipMode, self.equip)
        self._resolved = (cat2, names, explicit, getDefaultEquipNames(cat2.id))
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
    pool: ItemPool | None = None,
) -> list[sprite.Sprite]:
    """Render one animation, adding the second character the SWF asks for.

    ``pool`` holds the weapon/trinket parts this render may draw; the animation
    decides which of them, and where, actually appear.
    """
    items = pool or ItemPool()

    overlay_mode, payload = _second_cat_overlay_plan(cat_anim)
    logger.info("Resolved overlay mode for animation '%s': %s",
                anim_name, overlay_mode)

    frames, tag_pool, frames_info = _assemble_frames_for_first_cat(
        cat, partDir, palettes, cat_anim, catpartTree, catEquip,
        equipNames=equipNames, equipDefaults=equipDefaults, pool=items)

    if overlay_mode is None:
        _write_anim_metadata(anim_name, tag_pool, frames_info,
                             complete=True, overlay_mode=None, items=items)
        return frames

    resolved = secondCat.resolve() if secondCat is not None else None
    if resolved is None:
        logger.info("Animation '%s' places a second character, but none was selected; "
                    "rendering the primary cat only.", anim_name)
        # The cached file would not describe the whole animation, so it is marked
        # incomplete and the next run re-reads the SWF.
        _write_anim_metadata(anim_name, tag_pool, frames_info,
                             complete=False, overlay_mode=overlay_mode, items=items)
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
            equip2CacheNames, equip2Defaults, pool=items)
        _write_anim_metadata(anim_name, tag_pool, frames_info,
                             complete=True, overlay_mode=overlay_mode, items=items)
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
                             complete=False, overlay_mode=overlay_mode, items=items)
        return frames

    # Cache the rest pose too, so a later run can rebuild this layer offline.
    idleFrames = anims.get("idleF")
    if idleFrames:
        _write_anim_metadata("idleF", *extract_anim_tag_pool_and_frames_info(idleFrames),
                             complete=True, overlay_mode=None)

    restFrame = idle_frame[0]
    characterSprite = _get_cat_character(
        cat2, catEquip2, equip2Names, equip2Defaults, partDir, palettes,
        catpartTree, restFrame)

    characterByFrame: list[animations.Placement | None] = []
    for aframe in cat_anim:
        entry = (getattr(aframe, "extra", {}) or {}).get("character")
        if entry is None:
            characterByFrame.append(None)
            continue
        matrix, depth = _extra_matrix_and_depth(entry)
        if matrix is None:
            characterByFrame.append(None)
            continue
        cxform = entry[2] if isinstance(entry, (list, tuple)) and len(entry) > 2 else None
        characterByFrame.append((matrix, 0 if depth is None else depth, cxform))

    frames, tag_pool, frames_info = _assemble_frames_for_first_cat(
        cat, partDir, palettes, cat_anim, catpartTree, catEquip,
        None, None, None, equipNames, equipDefaults, None, None,
        characterByFrame, characterSprite, pool=items)
    _write_anim_metadata(anim_name, tag_pool, frames_info,
                         complete=True, overlay_mode=overlay_mode, items=items)
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


#: one entry of :attr:`animations.CatFrame.extra` holds a flat 6-value matrix,
#: either written straight as floats or inside a ``matrix`` block
FlatMatrixValue = tuple[float, float, float, float, float, float]


def _as_matrix(value: Any) -> swf.swf.Matrix | None:
    """Read a matrix out of its flat ``[a, b, c, d, tx, ty]`` form."""
    if isinstance(value, swf.swf.Matrix):
        return value

    if isinstance(value, (list, tuple)) and len(value) == 6:
        matrix = swf.swf.Matrix()
        matrix.xscale, matrix.skew1, matrix.skew2, matrix.yscale, matrix.xoffset, matrix.yoffset = value
        return matrix

    return None


def _extra_matrix_and_depth(value: Any) -> tuple[swf.swf.Matrix | None, int | None]:
    """Split an ``extra`` entry into its matrix and its depth.

    ``CatFrame.extra`` maps a tag to ``(matrix, depth[, colorTransform])``; the
    matrix itself is either a plain 6-value list or a ``matrix`` block that the GON
    parser turned into a dict.  The depth is ``None`` when the entry does not
    carry one.
    """
    if isinstance(value, (list, tuple)) and len(value) in (2, 3):
        matrix_value, depth_value = value[0], value[1]
        depth = int(depth_value) if isinstance(depth_value, int) else None
        return _as_matrix(matrix_value), depth

    return _as_matrix(value), None


def _extra_depth(value: Any) -> int:
    """The depth of an ``extra`` entry, defaulting to ``0``."""
    _matrix, depth = _extra_matrix_and_depth(value)
    return 0 if depth is None else depth


def _second_character_parts(anim: list[animations.CatFrame]) -> list[dict[str, animations.Placement]]:
    """The second cat's parts per frame, as ``tag -> placement``."""
    out: list[dict[str, animations.Placement]] = [{} for _ in anim]
    for i, frame in enumerate(anim):
        extra = getattr(frame, "extra", {}) or {}
        for key, value in extra.items():
            if not key.startswith("other_"):
                continue
            if key.removeprefix("other_") not in SECOND_CAT_PART_KEYS:
                continue

            matrix, depth = _extra_matrix_and_depth(value)
            if matrix is None:
                continue

            cxform = value[2] if isinstance(value, (list, tuple)) and len(value) > 2 else None
            out[i][key] = (matrix, 0 if depth is None else depth, cxform)
    return out


SECOND_CAT_PART_KEYS = {"head", "body", "tail", "arm1", "arm2", "leg1", "leg2"}


def _float_matrix_to_matrix(matrix: FloatMatrix) -> swf.swf.Matrix:
    out = swf.swf.Matrix()
    out.xscale, out.skew1, out.skew2, out.yscale, out.xoffset, out.yoffset = matrix
    return out


def _second_cat_overlay_plan(anim: list[animations.CatFrame]) -> tuple[str | None, swf.swf.Matrix | list[dict[str, animations.Placement]] | None]:
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
            for depth, tag_name, matrix, _cxform in frame:
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
    frame_entries: list[FrameEntry],
    cat2: CustomCat,
    partDir: str,
    palettes: list[palette.Palette],
    catTree: swf.SWF_Tree,
    equip2: CatEquipment,
    extras: dict[str, animations.Placement],
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

    for raw_name, placement in extras.items():
        matrix, depth, cxform = animations.asPlacement(placement)
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
        part_sprite.applyTransform(cxform)
        part_sprite.applyTransform(matrix)
        assembly.append(sprite.PlacedSprite(
            part_sprite, 0, depth, None, tag_name))
        add_pool(tag_name)
        frame_entries.append(
            (depth, tag_name, _matrix_to_float_matrix(matrix),
             animations.colorTransformToCache(cxform)))


def _append_animation_items(
    assembly: list[sprite.PlacedSprite],
    frame_entries: list[FrameEntry],
    tag_pool: list[str],
    frame: animations.CatFrame,
    pool: ItemPool,
) -> None:
    """Append every handheld layer the frame places, at its own depth."""
    for slot in HANDHELD_SLOTS:
        if not pool.item_name(slot):
            continue

        template = pool.sprite(slot)
        for placement in getFrameItemTags(frame).get(slot, []):
            matrix, depth, cxform = animations.asPlacement(placement)
            part = copy.deepcopy(template)
            part.applyTransform(cxform)
            part.applyTransform(matrix)

            assembly.append(sprite.PlacedSprite(
                part, 0, int(depth), None, f"{slot.capitalize()} Item"))

            if slot not in tag_pool:
                tag_pool.append(slot)
            frame_entries.append(
                (int(depth), slot, _matrix_to_float_matrix(matrix),
                 animations.colorTransformToCache(cxform)))


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
    extras_by_frame: list[dict[str, animations.Placement]] | None = None,
    second_cat: CustomCat | None = None,
    second_equip: CatEquipment | None = None,
    equipNames: EquipNames | None = None,
    equipDefaults: EquipNames | None = None,
    secondEquipNames: EquipNames | None = None,
    secondEquipDefaults: EquipNames | None = None,
    characterByFrame: list[animations.Placement | None] | None = None,
    characterSprite: sprite.Sprite | None = None,
    pool: ItemPool | None = None,
) -> tuple[list[sprite.Sprite], list[str], list[list[FrameEntry]]]:
    out = []
    tag_pool = []
    frames_info: list[list[FrameEntry]] = []

    for i, frame in enumerate(anim):
        assembly = []
        frame_entries: list[FrameEntry] = []

        def add_pool(name: str):
            if name not in tag_pool:
                tag_pool.append(name)

        def add_entry(depth: int, tag: str, matrix: swf.swf.Matrix | None,
                      cxform: swf.swf.CXFORM | None) -> None:
            frame_entries.append((
                depth,
                tag,
                None if matrix is None else (matrix.xscale, matrix.skew1,
                                             matrix.skew2, matrix.yscale,
                                             matrix.xoffset, matrix.yoffset),
                animations.colorTransformToCache(cxform),
            ))

        # same depth as the previous frame -> only the transform
        # changes, so the part artwork is reused from reusable/shapes.
        #
        # Every head-family placement is logged as the SWF has it, so the cached
        # metadata stays a faithful record and the decision of which layer is
        # actually shown can be re-derived from the tag names alone.
        for tag_name, placement in frame_used_tag_placements(frame, "head"):
            add_pool(tag_name)
            add_entry(placement[1], tag_name, placement[0], placement[2])

        # A `headblend_<pose>` replaces the other head layers with its own pose.
        for tag_name, placement in frame_head_layers(frame):
            matrix, depth, cxform = placement
            head = _get_cat_head(cat, _head_expression(frame, tag_name), equip,
                                 equipNames, equipDefaults, partDir, palettes, catTree)
            head = copy.deepcopy(head)
            head.applyTransform(cxform)
            head.applyTransform(matrix)
            assembly.append(sprite.PlacedSprite(
                head, 0, depth, None, f"Whole Head:{tag_name}"))

        for part_key in ("body", "arm1", "arm2", "leg1", "leg2", "tail"):
            for tag_name, placement in frame_used_tag_placements(frame, part_key):
                matrix, depth, cxform = placement
                part = copy.deepcopy(_get_cat_part(cat, part_key, partDir, palettes, catTree))
                part.applyTransform(cxform)
                part.applyTransform(matrix)
                assembly.append(sprite.PlacedSprite(
                    part, 0, depth, None, f"{PART_LABELS[part_key]}:{tag_name}"))
                add_pool(tag_name)
                add_entry(depth, tag_name, matrix, cxform)

        if second_cat is not None and second_equip is not None and extras_by_frame is not None:
            extras = extras_by_frame[i] if i < len(extras_by_frame) else {}
            _append_second_cat_extras(assembly, frame_entries, second_cat,
                                      partDir, palettes, catTree, second_equip, extras, tag_pool,
                                      secondEquipNames, secondEquipDefaults)

        # The weapon and the trinket are placed by this frame's own objects, so
        # they are their own layers here, exactly like the body parts above.
        if pool is not None:
            _append_animation_items(
                assembly, frame_entries, tag_pool, frame, pool)

        # A `character` PlaceObject2 places a whole character as a single layer
        # (the symbol it references is only a placeholder).
        if characterSprite is not None and characterByFrame is not None:
            entry = characterByFrame[i] if i < len(characterByFrame) else None
            if entry is not None:
                matrix, depth, cxform = entry
                whole = copy.deepcopy(characterSprite)
                # The placeholder lives in the canonical rest-pose space, so the
                # animation's own rest displacement must not be added on top of it
                # (see CHARACTER_LAYER_OFFSET).
                whole.applyTransform(_translation(CHARACTER_LAYER_OFFSET))
                whole.applyTransform(cxform)
                whole.applyTransform(matrix)
                assembly.append(sprite.PlacedSprite(
                    whole, 0, depth, None, "character"))
                add_pool("character")
                add_entry(depth, "character", matrix, cxform)

        # objects we cannot read are skipped, but stay visible in
        # the cached metadata.
        for skipped in getattr(frame, "skipped", []) or []:
            depth = skipped.get("depth", 0)
            frame_entries.append((
                int(depth) if depth is not None else 0,
                str(skipped.get("tag", "UNSUPPORTED:?")),
                None,
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
            matches = [a for a in anims if anim_name.lower() == a.lower()]
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


#: what an item slot's name is called in the interactive prompt
SLOT_PROMPTS = {
    "head": "Head Item",
    "face": "Face Item",
    "neck": "Neck Item",
}


def normalize_equipment(
    cat: CustomCat,
    mode: str = "default",
    override: Sequence[str | None] | None = None,
) -> tuple[EquipNames, bool]:
    """Resolve which armor a cat wears, without building any sprite.

    The result is always exactly the three armor slots, and the flag says
    whether the selection was explicit.  No SWF data is needed, which is what
    lets a fully cached animation render without touching the source files.

    A weapon or a trinket has nothing to do with this: see :func:`normalize_handheld`.
    """
    mode = (mode or "default").lower()
    defaults = getDefaultEquipNames(cat.id)

    # An explicit selection replaces the default; a gap in it means "nothing in
    # that slot", and a blank slot is how the CLI writes "none".  Asking for an
    # item explicitly is not a default, so no default rule applies to it.
    explicit = normalise_equipment(override)
    if explicit is not None and any(item not in (None, "") for item in override or ()):
        return explicit, True

    if mode == "none":
        return (None, None, None), True

    if mode == "interactive":
        if any(defaults):
            for slot, item in zip(EQUIP_SLOTS, defaults):
                if item:
                    logger.info("'%s' has default %s equipment: %s",
                                cat.id, slot, item)

            if not input("Empty input will proceed using default equipments set, input anything to choose another equipments: "):
                return defaults, False

        chosen = [input(f"{SLOT_PROMPTS[slot]} (empty for none): ").strip() or None
                  for slot in EQUIP_SLOTS]
        return normalise_equipment(chosen) or (None, None, None), True

    # `default`.  MedicCat's armor is disabled::
    # GIF export cannot represent her semi-transparent gear.
    if cat.id == "MedicCat":
        logger.warning(
            "MedicCat equipment is disabled because GIF export does not support "
            "semi-transparent pixels; her weapon and trinket are kept.")
        return (None, None, None), False

    return defaults, False


def normalize_handheld(
    cat: CustomCat,
    handheld: Sequence[str | None] | None = None,
) -> ItemPool:
    """The weapon/trinket pool a cat's render may draw from.

    An explicit request wins, then the cat's character file, then
    :data:`DEFAULT_TRINKET`.  Nothing here reads an animation: the pool only
    lists what could be shown, and the animation metadata decides what is.
    """
    return ItemPool.for_cat(cat.id, handheld)


def resolve_equipment_names(
    cat: CustomCat,
    mode: str = "default",
    override: Sequence[str | None] | None = None,
) -> tuple[EquipNames, bool]:
    """Like :func:`normalize_equipment`; the flag says whether it was explicit.

    ``primary_cat`` is accepted for callers that share one code path for both
    characters.  The armor slots are the same for both, so it changes nothing.
    """
    return normalize_equipment(cat, mode, override)


def resolve_equipment(
    partDir: str,
    catpartTree: swf.SWF_Tree,
    cat: CustomCat,
    mode: str = "default",
    override: Sequence[str | None] | None = None,
) -> tuple[CatEquipment, EquipNames, bool]:
    """Resolve a cat's armor sprites and report which items ended up worn."""
    names, explicit = normalize_equipment(cat, mode, override)
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
    items: ItemPool | None = None,
) -> set[str]:
    """Every reusable/shapes file a cat needs to be drawn across these frames.

    ``headExpressions=None`` collects the head variants the animation actually
    uses (the primary cat); pass ``{None}`` for a second cat rendered through the
    ``other_*`` overlay, whose head is always the default expression.

    ``items`` adds the standalone weapon/trinket parts, which are cached under
    the item name instead of under the cat.
    """
    names = {reusable.shape_cache_name(cat_id, part)
             for part in reusable.UNEQUIPPED_PARTS}

    if headExpressions is None:
        headExpressions = set()
        for frame in frames:
            # Only the layers a frame actually shows need their artwork cached;
            # a `headblend_` decides which pose that is.
            for tag, _placement in frame_head_layers(frame):
                expression = animations.headTagExpression(tag)
                headExpressions.add(expression if expression else (frame.face or None))

        if not headExpressions:
            headExpressions.add(None)

    for expression in headExpressions:
        names.add(reusable.shape_cache_name(
            cat_id, "head", expression=expression,
            equip=equipNames, defaults=equipDefaults))

    if items is not None:
        names |= items.cache_names()

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
    items: ItemPool | None = None,
    items2: ItemPool | None = None,
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

    required = _required_shape_names(frames, cat.id, equipNames, equipDefaults,
                                     items=items)
    anims: dict[str, list[animations.CatFrame]] = {}

    if overlay_mode is not None:
        if cat2 is None:
            return None
        if overlay_mode == "parts":
            required |= _required_shape_names(frames, cat2.id, equip2Names, equip2Defaults,
                                              headExpressions={None}, items=items2)
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
    equip: Sequence[str | None] | None = None,
    cat2_id: str | None = None,
    equip2_mode: str = "default",
    equip2: Sequence[str | None] | None = None,
    generate_gif: bool = True,
    handheld: Sequence[str | None] | None = None,
) -> None:
    palettes = palette.loadPalettes("./data/textures/palette.png")

    cat_list = getCustomCats()
    cat = prompt_first_cat(cat_list, cat_id, allowPrompt=not cat_id)
    if cat is None:
        raise SystemExit(
            f"Cat '{cat_id}' was not found in the custom cat list.")
    logger.info("Selected primary cat '%s' for interactive export", cat.id)

    # The armor is part of the cat; the weapon and the trinket are a pool of
    # their own, and which of them is drawn comes from the animation.
    equip1Names, equip1Explicit = resolve_equipment_names(
        cat, equip_mode, equip)
    equip1CacheNames = None if not equip1Explicit else equip1Names
    equip1Defaults = getDefaultEquipNames(cat.id)
    equip1Items = normalize_handheld(cat, handheld)

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
            equip1CacheNames, equip1Defaults, equip2CacheNames, equip2Defaults,
            items=equip1Items)

    # The weapon and the trinket are read from the cat part SWF even on a fully
    # cached animation, so the shape dump and the SWF tree are always prepared.
    # Both are cache hits after the first run; the animation SWFs stay untouched.
    partDir = ffdec.exportShapesIfNeeded(ffdecPath, catpart.CATPARTS_SWF)
    catpartTree = swf.getSwfTree(catpart.CATPARTS_SWF)

    catEquip = getCatEquipment(partDir, catpartTree, *equip1Names)
    secondCat = SecondCatResolver(cat_list, cat2_id, equip2_mode, equip2)

    if cached is not None:
        anim_name, cat_anim, anims = cached
    else:
        anims = animations.getCatAnims()
        anim_list = list(anims.keys())

        anim_name = requested_anim.strip() if requested_anim else ""
        anim_name = prompt_anim_name(
            anim_list, anim_name, allowPrompt=not anim_name)
        cat_anim = anims[anim_name]
        logger.info("Loading animation '%s' with %d frames",
                    anim_name, len(cat_anim))

    frames = render_animation(
        cat, partDir, palettes, catpartTree, cat_anim, anim_name, anims,
        catEquip, equip1CacheNames, equip1Defaults, secondCat,
        pool=equip1Items)

    os.makedirs(outdir, exist_ok=True)
    logger.info("Start saving exported frames for '%s' animation '%s' to '%s'",
                cat.id, anim_name, outdir)
    save_cat_output(outdir, cat.id, anim_name,
                    frames, generate_gif=generate_gif)


def exportCustomCats_batch(
    ffdecPath: str,
    anim_name: str | None,
    outdir: str,
    cat2_id: str | None = None,
    equip2_mode: str = "default",
    equip2: Sequence[str | None] | None = None,
    generate_gif: bool = True,
) -> int:
    """批量导出所有猫（如果找不到则直接使用各自的 class_anis 动画）"""
    partDir = ffdec.exportShapesIfNeeded(ffdecPath, catpart.CATPARTS_SWF)
    palettes = palette.loadPalettes("./data/textures/palette.png")
    catpartTree = swf.getSwfTree(catpart.CATPARTS_SWF)
    anims = animations.getCatAnims()
    list_anim = list(anims.keys())
    cat_list = getCustomCats()

    batch_cats = [c for c in cat_list if c.id in BATCH_CAT_NAMES]

    outdir = os.path.join(outdir, "batch")
    if os.path.isdir(outdir):
        shutil.rmtree(outdir)
    os.makedirs(outdir, exist_ok=True)

    # Asked at most once for the whole batch, then reused for every cat.
    secondCat = SecondCatResolver(
        cat_list, cat2_id, equip2_mode, equip2)

    def getClassIdleF(cat: CustomCat) -> str:
        out = f"{cat.id.capitalize().strip("cat")}IdleF"
        if any(out.lower() == a.lower() for a in list_anim):
            return out
        else:
            return "idleF"

    count = 0
    for cat in batch_cats:
        _anim_name = anim_name
        if not _anim_name or not any(_anim_name.lower() == a.lower() for a in list_anim):
            _anim_name = getClassIdleF(cat)
            logging.warning(
                f"Cat {cat.id}: animation '{anim_name}' not found, using '{_anim_name}'")
        cat_anim = anims[_anim_name]

        catEquip, equipNames, equipExplicit = resolve_equipment(
            partDir, catpartTree, cat, "default")

        try:
            frames = render_animation(
                cat, partDir, palettes, catpartTree, cat_anim, _anim_name, anims,
                catEquip, None if not equipExplicit else equipNames,
                getDefaultEquipNames(cat.id), secondCat,
                pool=normalize_handheld(cat))
            save_cat_output(outdir, cat.id, _anim_name, frames,
                            generate_gif=generate_gif)
            count += 1
            logging.info(f"Exported {cat.id}")
        except Exception as e:
            logging.error(f"Failed to export {cat.id}: {e}")
            continue
    return count


if __name__ == "__main__":
    exportCustomCats_batch(ffdecDefault, "tanturmF", outDirDefault)
