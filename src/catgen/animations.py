from . import swf_tree as tree

import logging
from typing import Any

_2D_CATANIS_SWF = "./data/swfs/2d_catanis.swf"
CATANIS_SWF1 = "./data/swfs/catanis.swf"
CATANIS_SWF2 = "./data/swfs/catanis2.swf"
HOUSE_INTERSTITIALS = "./data/swfs/house_interstitials.swf"

#: Every SWF that holds cat animations, as ``(path, root sprite)`` in read order:
#: later files override the animations they redefine.
CATANIS_SOURCES: tuple[tuple[str, str], ...] = (
    (CATANIS_SWF1, "CatTest"),
    (CATANIS_SWF2, "_Append_CatTest"),
    (_2D_CATANIS_SWF, "FlatCat"),
)

#: One placement of a part: its matrix, its display-list depth and the SWF
#: `colorTransform` that goes with it (``None`` when the tag carries none).
#: The color transform drives part tinting and, importantly, the alpha used by
#: cross-fades such as `headblend_*`.
#:
#: Written without string forward references on purpose: the alias is used from
#: other modules' annotations, and a quoted ``"tree.swf.CXFORM"`` would only
#: resolve inside this one (`typing.get_type_hints` evaluates it in the *using*
#: module's globals, where `tree` does not exist).
Placement = tuple[tree.swf.Matrix, int, tree.swf.CXFORM | None]


def _defaultPlacement() -> Placement:
    """The "this frame places nothing" placeholder (identity at depth 0)."""
    return (tree.swf.Matrix(), 0, None)


def asPlacement(value: Any) -> Placement:
    """Normalise a placement, accepting the legacy ``(matrix, depth)`` shape too."""
    if len(value) >= 3:
        return (value[0], value[1], value[2])
    return (value[0], value[1], None)


#: Head layers come in more than one tag family.  ``head_<pose>`` is an
#: expression of the head itself; ``headblend_<pose>`` is the outgoing expression
#: the SWF parks at a fixed spot (and a low depth) so the head can cross-fade away
#: from it, so it belongs in the tag pool but is not part of the visible frame.
HEAD_TAG_FAMILIES = ("head_", "headblend_")
HEAD_BLEND_PREFIX = "headblend_"


def isHeadTag(name: str) -> bool:
    """True for ``head``, ``head_<pose>`` and ``headblend_<pose>``."""
    return name == "head" or name.startswith(HEAD_TAG_FAMILIES)


def isHeadBlendTag(name: str) -> bool:
    """True for ``headblend_<pose>``, the parked cross-fade source."""
    return name.startswith(HEAD_BLEND_PREFIX)


def headTagExpression(name: str) -> str | None:
    """The face pose a head layer tag stands for.

    ``head`` itself means "the frame's own pose", which this returns as ``None``.
    """
    for family in HEAD_TAG_FAMILIES:
        if name.startswith(family):
            return name[len(family):] or None
    return None


class CatFrame:
    head: "Placement"
    body: "Placement"
    arm1: "Placement"
    arm2: "Placement"
    leg1: "Placement"
    leg2: "Placement"
    tail: "Placement"

    face: str

    extra: dict[str, "Placement"]
    used: dict[str, list["Placement"]]
    skipped: list[dict]

    def __init__(self):
        self.head = _defaultPlacement()
        self.body = _defaultPlacement()

        self.arm1 = _defaultPlacement()

        self.arm2 = _defaultPlacement()

        self.leg1 = _defaultPlacement()
        self.leg2 = _defaultPlacement()
        self.tail = _defaultPlacement()

        self.extra = {}
        self.used = {}
        self.skipped = []

        self.face = ""


def _record_used_tag(used: dict[str, list[Placement]], name: str, xform: tree.swf.Matrix | None, depth: int, cxform: tree.swf.CXFORM | None = None) -> None:
    if not name:
        return
    used.setdefault(name, []).append(
        ((xform or tree.swf.Matrix()), depth, cxform))


def finalizeFrame(out: CatFrame) -> CatFrame:
    """Derive the legacy per-part fields and `extra` from a frame's `used` map."""
    used_tags = out.used

    head_candidates = [
        (name, asPlacement(value))
        for name, value_list in used_tags.items()
        for value in value_list
        if isHeadTag(name)
    ]
    if head_candidates:
        best_name, best = max(head_candidates, key=lambda item: item[1][1])
        out.head = best
        expression = headTagExpression(best_name)
        if expression:
            out.face = expression

    for tag_name in ("body", "arm1", "arm2", "leg1", "leg2", "tail"):
        if tag_name in used_tags and used_tags[tag_name]:
            values = sorted(used_tags[tag_name], key=lambda item: item[1])
            out.__dict__[tag_name] = asPlacement(values[-1])

    out.extra = {}
    for name, value_list in used_tags.items():
        if name in {"body", "arm1", "arm2", "leg1", "leg2", "tail"}:
            continue
        if isHeadTag(name):
            continue
        if value_list:
            out.extra[name] = asPlacement(
                sorted(value_list, key=lambda item: item[1])[-1])

    return out


def catFrameFromObjs(objs: list[tree.PlacedObject], skipped: list[dict] | None = None) -> CatFrame:
    out = CatFrame()
    used_tags: dict[str, list[Placement]] = {}

    for obj in objs:
        if not obj.name:
            continue
        _record_used_tag(used_tags, obj.name, obj.xform, obj.depth, obj.cxform)

    out.used = used_tags
    out.skipped = list(skipped or [])

    return finalizeFrame(out)


def framesFromAnimCache(payload: dict) -> list[CatFrame]:
    """Rebuild the frame list of one animation from reusable/anims/<name>.json.

    This is what lets a fully cached animation render without parsing the source
    SWF at all.
    """
    frames_obj = payload.get("frames") or {}
    out: list[CatFrame] = []

    for index in sorted(frames_obj, key=lambda key: int(key)):
        frame = CatFrame()

        for entry in frames_obj[index]:
            tag = str(entry.get("tag", ""))
            transform = entry.get("transform")
            depth = entry.get("depth", 0)

            if transform is None:
                frame.skipped.append({
                    "tag": tag,
                    "note": entry.get("note", "skipped"),
                    "depth": int(depth) if depth is not None else 0,
                })
                continue

            matrix = tree.swf.Matrix()
            (matrix.xscale, matrix.skew1, matrix.skew2,
             matrix.yscale, matrix.xoffset, matrix.yoffset) = (float(v) for v in transform)
            frame.used.setdefault(tag, []).append(
                (matrix, int(depth), colorTransformFromCache(entry.get("colorTransform"))))

        out.append(finalizeFrame(frame))

    return out


def colorTransformToCache(cxform: "tree.swf.CXFORM | None") -> dict | None:
    """Serialise a SWF color transform for the reusable metadata."""
    if cxform is None:
        return None
    return {
        "mult": [cxform.redMult, cxform.greenMult, cxform.blueMult, cxform.alphaMult],
        "add": [cxform.redAdd, cxform.greenAdd, cxform.blueAdd, cxform.alphaAdd],
    }


def colorTransformFromCache(data: dict | None) -> "tree.swf.CXFORM | None":
    """Rebuild a SWF color transform from the reusable metadata."""
    if not data:
        return None

    cxform = tree.swf.CXFORM()
    mult = data.get("mult") or [1.0, 1.0, 1.0, 1.0]
    add = data.get("add") or [0, 0, 0, 0]
    (cxform.redMult, cxform.greenMult, cxform.blueMult,
     cxform.alphaMult) = (float(v) for v in mult)
    # `CXFORM` keeps the add terms as the signed integers the SWF stores
    (cxform.redAdd, cxform.greenAdd, cxform.blueAdd,
     cxform.alphaAdd) = (int(v) for v in add)
    return cxform


def isIdentityColorTransform(cxform: "tree.swf.CXFORM | None") -> bool:
    """True when a color transform would not change anything."""
    if cxform is None:
        return True
    return (cxform.redMult == 1.0 and cxform.greenMult == 1.0
            and cxform.blueMult == 1.0 and cxform.alphaMult == 1.0
            and cxform.redAdd == 0 and cxform.greenAdd == 0
            and cxform.blueAdd == 0 and cxform.alphaAdd == 0)


def aniFromSprite(defSprite: tree.SWF_Tree.SpriteNode) -> list[CatFrame]:
    out = []
    for frame in defSprite.frames:
        out.append(catFrameFromObjs(frame.objs, frame.skipped))

    return out


def _iterAnimFrames(swfTree: tree.SWF_Tree, defSprite: tree.SWF_Tree.SpriteNode, prefix: str = ""):
    """Yield ``(name, sprite node or None)`` for every animation of a root sprite.

    The one place that decides which frames of a root sprite count as animations,
    so the frame builder and the plain name listing can never drift apart.
    """
    for frame in defSprite.frames:
        if (frame.name == ""):
            continue

        if (len(frame.objs) > 1):
            logging.warning("Animation has many animations: " + frame.name)
            continue

        if (len(frame.objs) == 0):
            yield prefix + frame.name, None
            continue

        node = swfTree.get(frame.objs[0].id)
        if isinstance(node, tree.SWF_Tree.SpriteNode):
            yield prefix + frame.name, node


def anisFromSprite(swfTree: tree.SWF_Tree, defSprite: tree.SWF_Tree.SpriteNode, prefix: str = "") -> dict[str, list[CatFrame]]:
    out: dict[str, list[CatFrame]] = {}
    for name, node in _iterAnimFrames(swfTree, defSprite, prefix):
        out[name] = [] if node is None else aniFromSprite(node)

    return out


def getCatAnimSources() -> list[tuple[str, list[str]]]:
    """Animation names per source SWF, as ``(swf path, names)`` in read order.

    Listing names does not build any frame, so this is much cheaper than
    `getCatAnims` while covering exactly the same animations.  A name that a later
    SWF redefines is attributed to that later file -- the one whose frames win when
    `getCatAnims` merges them.
    """
    groups: list[tuple[str, list[str]]] = []
    owner: dict[str, int] = {}

    for swfPath, rootName in CATANIS_SOURCES:
        swfTree = tree.getSwfTree(swfPath)
        root = swfTree.get(rootName)
        if not isinstance(root, tree.SWF_Tree.SpriteNode):
            logging.warning(
                "SWF '%s' has no '%s' sprite; skipping it", swfPath, rootName)
            continue

        names = [name for name, _node in _iterAnimFrames(swfTree, root)]
        groups.append((swfPath, names))
        for name in names:
            owner[name] = len(groups) - 1

    return [(swfPath, sorted({name for name in names if owner[name] == index}))
            for index, (swfPath, names) in enumerate(groups)]


def getCatAnims() -> dict[str, list[CatFrame]]:
    out: dict[str, list[CatFrame]] = {}

    for swfPath, rootName in CATANIS_SOURCES:
        swfTree = tree.getSwfTree(swfPath)
        root = swfTree.get(rootName)
        if not isinstance(root, tree.SWF_Tree.SpriteNode):
            logging.warning(
                "SWF '%s' has no '%s' sprite; skipping it", swfPath, rootName)
            continue
        out |= anisFromSprite(swfTree, root)
    return out
