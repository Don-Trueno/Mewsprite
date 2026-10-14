from .util import parse_csv as csv
from .util import parse_gon as gon
from .util import ffdec_tools as ffdec
from .util import svg_tools as svg
from .catgen import swf_tree as swf_tree
from .catgen import reusable
from .catgen import sprite

import os
import shutil

from typing import Any

from . import translations

ITEMS_SWF = "./data/swfs/catparts.swf"

#: where the cat part sprites live; also holds the per-item sprites of the
#: weapon and the trinket
CATPARTS_SWF = "./data/swfs/catparts.swf"

ITEMS_FOLDER = "./data/data/items"
ITEMS_GONS = [
    "armor_sets.gon",
    "beanies_quest_items.gon",
    "consumables.gon",
    "cursed_items.gon",
    "face_items.gon",
    "head_items.gon",
    "legacy_quest_items.gon",
    "legendary_items.gon",
    "neck_items.gon",
    "parasites.gon",
    "special_class_items.gon",
    "trinkets.gon",
    "weapons.gon"
]

KIND_MAP = {
    "face": "FaceItemIcon",
    "head": "HeadItemIcon",
    "neck": "NeckItemIcon",
    "trinket": "TrinketIcon",
    "weapon": "WeaponIcon",
}

#: which `catparts.swf` sprite holds the artwork of each equip slot, as a
#: ``(front, back)`` pair.  Every item of that kind indexes the sprite with its
#: own ``frame`` field, exactly like the head/face/neck icons exported above.
ITEM_SLOT_SYMBOLS = {
    "head": ("HeadItemF", "HeadItemB"),
    "face": ("FaceItemF", "FaceItemB"),
    "neck": ("NeckItemF", "NeckItemB"),
    "weapon": ("Weapon", None),
    "trinket": ("Trinket", None),
}

#: item kind each equip slot expects, for the slots whose artwork is read from
#: its own sprite.  A mismatch means the name was written into the wrong slot.
SLOT_ITEM_KINDS = {
    "head": "head",
    "face": "face",
    "neck": "neck",
    "weapon": "weapon",
    "trinket": "trinket",
}

#: slots whose artwork is only ever placed by the animation, not by the head
#: placement sprite: the animation defines both the transform and the depth.
ANIMATED_ITEM_SLOTS = ("weapon", "trinket")

class Item:
    variant: str | None
    name: str
    translationID: str
    desc: str
    rarity: str
    kind: str
    frame: int

    data: dict[str, Any]

    def __init__(self, name: str, gondata: dict[str, Any]):
        self.name = name

        self.variant = None
        if "variant_of" in gondata:
            self.variant = gondata["variant_of"]

            self.data = gondata.copy()
            self.data.pop("variant_of")
        
        else:
            self.translationID = gondata["name"]
            self.desc = gondata["desc"]
            self.kind = gondata["kind"]
            self.frame = int(gondata["frame"])

            self.data = gondata.copy()
            self.data.pop("name")
            self.data.pop("desc")
            self.data.pop("kind")
            self.data.pop("frame")

        
        
        

def getItems() -> list[Item]:
    items: list[Item] = []
    for gonname in ITEMS_GONS:
        gondata = gon.parse_gon(ITEMS_FOLDER + '/' + gonname)
        for name, data in gondata.items():
            if (name == "__COMMENTS__" or data == None):
                continue

            items.append(Item(name, data))

    return items

def getItemDict() -> dict[str, Item]:
    items: dict[str, Item] = {}
    for gonname in ITEMS_GONS + ["enemy_items.gon"]:
        gondata = gon.parse_gon(ITEMS_FOLDER + '/' + gonname)
        for name, data in gondata.items():
            if (name == "__COMMENTS__" or data == None):
                continue

            items[name] = Item(name, data)

    return items


def itemFrameIndex(item: Item) -> int:
    """Zero-based frame the item's artwork sits at inside its slot sprite."""
    return int(item.frame) - 1


def buildItemSprite(partDir: str, catTree: swf_tree.SWF_Tree, slot: str, item: Item) -> sprite.Sprite:
    """Artwork of one item as placed inside its equip slot sprite.

    ``slot`` is one of :data:`ITEM_SLOT_SYMBOLS`.  The sprite frame already
    carries the item's own offset within the slot, so the caller only has to
    apply the placement transform that comes from the animation.
    """
    expected = SLOT_ITEM_KINDS.get(slot)
    if (expected != None and item.kind != expected):
        raise ValueError(
            f"'{item.name}' is a {item.kind} item and cannot be worn as a {slot}")

    front, _back = ITEM_SLOT_SYMBOLS[slot]
    node = catTree.get(front)
    if (node == None):
        raise RuntimeError(f"'{front}' is missing from the cat parts SWF")
    if (not isinstance(node, swf_tree.SWF_Tree.SpriteNode)):
        raise RuntimeError(f"'{front}' is not a sprite in the cat parts SWF")

    frame = node.frames[itemFrameIndex(item)]
    objs = [obj for obj in frame.objs if obj.name != "aux"]
    return sprite.spriteFromPlacedObjects(partDir, catTree, objs)


def itemSpriteCacheName(itemName: str) -> str:
    """File an item's artwork is cached under: just ``<name>.svg``.

    A weapon or a trinket belongs to no cat in particular, so unlike a cat part
    its cache name carries no cat id.
    """
    return reusable.item_cache_name(itemName)


def getItemSprite(slot: str, itemName: str) -> sprite.Sprite:
    """Artwork of the weapon or trinket ``itemName``, read through ``reusable``.

    The first run extracts the item from the source SWFs and writes
    ``reusable/shapes/<name>.svg``; every later run reads that file straight
    back, so no SWF has to be parsed to draw an item again.
    """
    return reusable.get_or_build_shape(
        itemSpriteCacheName(itemName),
        lambda: _extractItemSprite(slot, itemName),
    )


def _extractItemSprite(slot: str, itemName: str) -> sprite.Sprite:
    """Build one item's artwork from the source SWFs, by name."""
    from .import_paths import ffdecDefault

    partDir = ffdec.exportShapesIfNeeded(ffdecDefault, CATPARTS_SWF)
    catTree = swf_tree.getSwfTree(CATPARTS_SWF)
    return buildItemSprite(partDir, catTree, slot, getItemDict()[itemName])


def exportItems(svgCropper: svg.SvgCropper, ffdecPath: str, items: list[Item], outfolder = "./out") -> int:
    dumpdir = ffdec.exportShapesIfNeeded(ffdecPath, ITEMS_SWF)
    print("dumpdir:", dumpdir)
    print("Contents of dumpdir:", os.listdir(dumpdir))

    count = 0

    foldermap = {}
    print("foldermap:", foldermap)
    dirs = os.listdir(dumpdir)
    for kind, id in KIND_MAP.items():
        for dir in dirs:
            if dir.endswith(id):
                foldermap[kind] = os.path.join(dumpdir, dir)
                break

    outfolder += "/items"
    if (os.path.isdir(outfolder)):
        shutil.rmtree(outfolder)

    for item in items:
        if (item.variant != None):
            continue

        src = foldermap.get(item.kind,'') + f"/{item.frame}.svg"

        folder = outfolder + "/" + item.kind

        en = translations.get(item.translationID)

        out = folder + "/ITEM " + en + ".svg"
        if os.path.exists(out):
            folder += "/dupes/" 
            os.makedirs(folder, exist_ok=True)
            shutil.move(out, folder + "/ITEM " + en + ".svg")

            out = folder + "/ITEM " + en + ".svg"
            
        os.makedirs(folder, exist_ok=True)
        with open(src, "r") as xml:
            content = xml.readlines()

        outlines = []
        for line in content:
            if ("id=\"sloticon\"" in line):
                continue

            outlines.append(line)

        with open(src, "w") as xmlout:
            xmlout.write(''.join(outlines))   

        svgCropper.crop_handle_duplicate(src, out)  
        count += 1

    return count

    
