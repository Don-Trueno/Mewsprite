from . import swf_tree as tree

import logging

CATANIS_SWF1 = "./data/swfs/catanis.swf"
CATANIS_SWF2 = "./data/swfs/catanis2.swf"

class CatFrame:
    head: tuple[tree.swf.Matrix, int]
    body: tuple[tree.swf.Matrix, int]
    arm1: tuple[tree.swf.Matrix, int]
    arm2: tuple[tree.swf.Matrix, int]
    leg1: tuple[tree.swf.Matrix, int]
    leg2: tuple[tree.swf.Matrix, int]
    tail: tuple[tree.swf.Matrix, int]

    face: str

    extra: dict[str, tuple[tree.swf.Matrix, int]]
    used: dict[str, list[tuple[tree.swf.Matrix, int]]]
    skipped: list[dict]

    def __init__(self):
        self.head = (tree.swf.Matrix(), 0)
        self.body = (tree.swf.Matrix(), 0)

        self.arm1 = (tree.swf.Matrix(), 0)

        self.arm2 = (tree.swf.Matrix(), 0)

        self.leg1 = (tree.swf.Matrix(), 0)
        self.leg2 = (tree.swf.Matrix(), 0)
        self.tail = (tree.swf.Matrix(), 0)

        self.extra = {}
        self.used = {}
        self.skipped = []

        self.face = ""


def _record_used_tag(used: dict[str, list[tuple[tree.swf.Matrix, int]]], name: str, xform: tree.swf.Matrix | None, depth: int) -> None:
    if not name:
        return
    used.setdefault(name, []).append(((xform or tree.swf.Matrix()), depth))


def finalizeFrame(out: CatFrame) -> CatFrame:
    """Derive the legacy per-part fields and `extra` from a frame's `used` map."""
    used_tags = out.used

    head_candidates = [
        (name, value[0], value[1])
        for name, value_list in used_tags.items()
        for value in value_list
        if name.startswith("head")
    ]
    if head_candidates:
        best_name, best_xform, best_depth = max(head_candidates, key=lambda item: item[2])
        out.head = (best_xform, best_depth)
        if "_" in best_name:
            out.face = best_name.removeprefix("head_")

    for tag_name in ("body", "arm1", "arm2", "leg1", "leg2", "tail"):
        if tag_name in used_tags and used_tags[tag_name]:
            values = sorted(used_tags[tag_name], key=lambda item: item[1])
            out.__dict__[tag_name] = values[-1]

    out.extra = {}
    for name, value_list in used_tags.items():
        if name in {"body", "arm1", "arm2", "leg1", "leg2", "tail"}:
            continue
        if name.startswith("head"):
            continue
        if value_list:
            out.extra[name] = sorted(value_list, key=lambda item: item[1])[-1]

    return out


def catFrameFromObjs(objs: list[tree.PlacedObject], skipped: list[dict] | None = None) -> CatFrame:
    out = CatFrame()
    used_tags: dict[str, list[tuple[tree.swf.Matrix, int]]] = {}

    for obj in objs:
        if not obj.name:
            continue
        _record_used_tag(used_tags, obj.name, obj.xform, obj.depth)

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
            frame.used.setdefault(tag, []).append((matrix, int(depth)))

        out.append(finalizeFrame(frame))

    return out

def aniFromSprite(defSprite: tree.SWF_Tree.SpriteNode) -> list[CatFrame]:
    out = []
    for frame in defSprite.frames:
        out.append(catFrameFromObjs(frame.objs, frame.skipped))

    return out

def anisFromSprite(swfTree: tree.SWF_Tree, defSprite: tree.SWF_Tree.SpriteNode) -> dict[str, list[CatFrame]]:
    out = {}
    for frame in defSprite.frames:
        if (frame.name == ""):
            continue

        if (len(frame.objs) > 1):
            logging.warning("Animation has many animations: " + frame.name)
            continue
            raise RuntimeError("Animation has many animations: " + frame.name)

        if (len(frame.objs) == 0):
            out[frame.name] = []
            continue

        node = swfTree.get(frame.objs[0].id)
        out[frame.name] = aniFromSprite(node)
        
    return out

def getCatAnims() -> dict[str, list[CatFrame]]:
    anis1 = tree.getSwfTree(CATANIS_SWF1)
    out = anisFromSprite(anis1, anis1.get("CatTest"))

    anis2 = tree.getSwfTree(CATANIS_SWF2)
    out |= anisFromSprite(anis2, anis2.get("_Append_CatTest"))

    return out