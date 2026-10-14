"""Reusable on-disk caches for animation metadata and part SVG images.

Layout:

    reusable/anims/<anim-name>.json
    reusable/shapes/<cat-id>-<part>[-<expression>][-<equipment>].svg

Part file naming rules:

* parts that are never touched by equipment (limbs, body, tail)::

      <cat-id>-<part>.svg                  e.g. ButcherCat-tail.svg

* parts that are composed together with the worn equipment (head, character).
  The optional expression comes first, then the three armor slots in the same
  ``head;face;neck`` order the CLI uses::

      <cat-id>-head.svg                    default equipment, default face
      <cat-id>-head-smile.svg              face "smile", default equipment
      <cat-id>-head-None.svg               explicitly wearing nothing
      <cat-id>-head-<head>-<face>-<neck>.svg
      <cat-id>-character.svg               whole cat, used for the `character` part
      <cat-id>-character-smile-<...>.svg

* standalone items, cached under their own name because they belong to no cat::

      <item-name>.svg                      a weapon or a trinket

The weapon and the trinket are *not* part of a cat part's name: the animation
places them, and they are their own layers, so a cat's head looks the same
whichever weapon it happens to hold.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
from typing import Any, Callable, Sequence

from ..util import svg_tools as svg_tools
from . import sprite as sprite_mod

logger = logging.getLogger(__name__)

REUSABLE_DIR = "./cache"
ANIMS_DIR = os.path.join(REUSABLE_DIR, "anims")
SHAPES_DIR = os.path.join(REUSABLE_DIR, "shapes")

#: parts whose artwork never depends on the worn equipment
UNEQUIPPED_PARTS: tuple[str, ...] = ("body", "tail", "arm1", "arm2", "leg1", "leg2")

#: parts whose artwork is composed together with the worn equipment
EQUIP_AFFECTED_PARTS: tuple[str, ...] = ("head", "character")

#: file-name token meaning "explicitly wearing no equipment at all"
NO_EQUIPMENT = "None"

#: bump when the way a part sprite is composed changes, so old cached artwork is
#: discarded instead of silently rendering with the previous composition
SHAPE_CACHE_VERSION = "7"

#: marker file holding SHAPE_CACHE_VERSION next to the part SVGs
VERSION_FILE = ".version"

#: bump when the *shape* of the animation metadata changes, so a cached animation
#: written by an older pipeline is ignored instead of rendering incompletely
ANIM_CACHE_VERSION = 2

_UNSAFE_NAME_CHARS = re.compile(r"[^A-Za-z0-9_.\-]")

#: parsed part sprites, so a frame never has to re-parse an SVG from disk
_SHAPE_MEMORY: dict[str, "sprite_mod.Sprite"] = {}

#: whether the on-disk part cache has already been checked against the version,
#: remembered per directory so a redirected cache is validated again
_SHAPE_CACHE_CURRENT: str | None = None

Equipment = Sequence[str | None]


def _safe(token: str) -> str:
    return _UNSAFE_NAME_CHARS.sub("_", token)


#: how many equipment slots a fully specified selection has: head, face, neck,
#: weapon, trinket -- the order the CLI takes them in.
EQUIPMENT_SLOTS = 5

#: how many of those slots a cat part depends on.  The weapon and the trinket
#: are standalone items with their own cache file, so only the armor slots are
#: part of a cat part's name.
ARMOR_SLOTS = 3


def equipment_suffix(equip: Equipment | None, defaults: Equipment | None) -> str:
    """Return the ``<-装备>`` part of a cached cat part file name.

    ``equip=None`` means "use the cat's default equipment" and yields no suffix.
    An explicit selection that happens to equal the default also yields no
    suffix, because both describe exactly the same artwork.  An explicit empty
    selection yields ``-None``.

    Only the armor slots are written down: a weapon or a trinket is drawn from
    its own cached item file, so it never changes a cat part's name.
    """
    if equip is None:
        return ""

    selection = _as_slots(equip, ARMOR_SLOTS)
    if defaults is not None and selection == _as_slots(defaults, ARMOR_SLOTS):
        return ""

    if not any(selection):
        return f"-{NO_EQUIPMENT}"

    # head;face;neck, the same order the CLI uses.
    return "-" + "-".join(
        NO_EQUIPMENT if item is None or item == "" else _safe(str(item))
        for item in selection
    )


def _as_slots(values: Equipment, slots: int) -> tuple[str | None, ...]:
    """Normalise an equipment selection to exactly ``slots`` entries."""
    items: list[str | None] = list(values)[:slots]
    while len(items) < slots:
        items.append(None)
    return tuple(None if item in (None, "") else str(item) for item in items)


def shape_cache_name(
    cat_id: str,
    part: str,
    expression: str | None = None,
    equip: Equipment | None = None,
    defaults: Equipment | None = None,
) -> str:
    """Build the ``reusable/shapes`` file name for one part of one cat."""
    name = f"{_safe(cat_id)}-{_safe(part)}"

    if part in UNEQUIPPED_PARTS:
        return name + ".svg"

    if part not in EQUIP_AFFECTED_PARTS:
        raise ValueError(f"'{part}' is not a cacheable cat part")

    if expression:
        name += f"-{_safe(expression)}"

    return name + equipment_suffix(equip, defaults) + ".svg"


def item_cache_name(item_name: str) -> str:
    """Build the ``reusable/shapes`` file name of one standalone item.

    A weapon or a trinket is not part of any cat, so -- unlike a cat part -- its
    name carries no cat id and no equipment suffix.
    """
    return _safe(item_name) + ".svg"


def shape_cache_path(name: str) -> str:
    return os.path.join(SHAPES_DIR, name)


def _version_path() -> str:
    return os.path.join(SHAPES_DIR, VERSION_FILE)


def reset_shape_cache_if_stale() -> bool:
    """Drop the cached part artwork when it was composed by older code.

    The part file names are fixed by time, so a change to how a part is
    composed (e.g. the head layer order) cannot be expressed in the name.  A
    version marker next to the files covers that instead.
    """
    global _SHAPE_CACHE_CURRENT
    if _SHAPE_CACHE_CURRENT == SHAPES_DIR:
        return False

    _SHAPE_CACHE_CURRENT = SHAPES_DIR

    path = _version_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                if handle.read().strip() == SHAPE_CACHE_VERSION:
                    return False
        except OSError:
            pass
    elif not os.path.isdir(SHAPES_DIR) or not any(
            entry.endswith(".svg") for entry in os.listdir(SHAPES_DIR)):
        # nothing cached yet: nothing to invalidate
        return False

    logger.info("Part artwork cache in %s was built by another version; rebuilding it.",
                SHAPES_DIR)
    _SHAPE_MEMORY.clear()
    try:
        for entry in os.listdir(SHAPES_DIR):
            if entry.endswith(".svg"):
                os.remove(os.path.join(SHAPES_DIR, entry))
    except OSError as error:
        logger.warning("Could not clear the stale part cache: %s", error)

    _write_shape_cache_version()
    return True


def ensure_shape_cache_current() -> bool:
    """Public entry point for the staleness check; returns True if it reset."""
    return reset_shape_cache_if_stale()


def mark_shape_cache_current() -> None:
    """Record SHAPE_CACHE_VERSION next to the cached parts."""
    global _SHAPE_CACHE_CURRENT
    _SHAPE_CACHE_CURRENT = SHAPES_DIR
    _write_shape_cache_version()


def _write_shape_cache_version() -> None:
    try:
        os.makedirs(SHAPES_DIR, exist_ok=True)
        with open(_version_path(), "w", encoding="utf-8") as handle:
            handle.write(SHAPE_CACHE_VERSION)
    except OSError as error:
        logger.debug("Could not record the part cache version: %s", error)


def load_shape(name: str) -> "sprite_mod.Sprite | None":
    """Load a cached part SVG, or ``None`` when it is missing/unreadable."""
    reset_shape_cache_if_stale()

    path = shape_cache_path(name)
    if not os.path.isfile(path):
        return None

    try:
        return sprite_mod.Sprite(svg_tools.parse_svg(path))
    except Exception as error:  # corrupt cache entry: rebuild instead of failing
        logger.warning("Ignoring unreadable reusable shape '%s': %s", path, error)
        return None


def save_shape(name: str, part: "sprite_mod.Sprite") -> bool:
    """Persist a part SVG so later runs can reuse it.  Never raises."""
    path = shape_cache_path(name)
    try:
        reset_shape_cache_if_stale()
        os.makedirs(SHAPES_DIR, exist_ok=True)
        _write_shape_cache_version()
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(part.compile())
        return True
    except Exception as error:
        logger.warning("Could not cache reusable shape '%s': %s", path, error)
        return False


def get_or_build_shape(name: str, builder: Callable[[], "sprite_mod.Sprite"]) -> "sprite_mod.Sprite":
    """Read-through cache for one part sprite: memory, then disk, then ``builder``.

    The returned sprite is always a fresh deep copy, so callers may apply
    per-frame transforms to it without corrupting the cache.
    """
    cached = _SHAPE_MEMORY.get(name)
    if cached is None:
        cached = load_shape(name)
        if cached is None:
            logger.debug("reusable shape cache miss: %s", name)
            cached = builder()
            save_shape(name, cached)
        else:
            logger.debug("reusable shape cache hit (disk): %s", name)
        _SHAPE_MEMORY[name] = cached

    return copy.deepcopy(cached)


def anim_cache_path(anim_name: str) -> str:
    return os.path.join(ANIMS_DIR, f"{_safe(anim_name)}.json")


def load_anim_cache(anim_name: str) -> dict[str, Any] | None:
    """Load the cached metadata of one animation, or ``None`` when missing."""
    path = anim_cache_path(anim_name)
    if not os.path.isfile(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as error:
        logger.warning("Ignoring unreadable reusable animation '%s': %s", path, error)
        return None

    if not isinstance(payload, dict) or "frames" not in payload:
        logger.warning("Ignoring malformed reusable animation '%s'", path)
        return None

    # Metadata written before the colorTransform was carried through would render
    # without the tint and the cross-fades, so it is treated as missing.
    if payload.get("metadata_version") != ANIM_CACHE_VERSION:
        logger.debug("Ignoring reusable animation '%s' written as metadata version %r",
                     path, payload.get("metadata_version"))
        return None

    return payload


def save_anim_cache(anim_name: str, payload: dict[str, Any]) -> str | None:
    """Persist animation metadata for later runs.  Never raises."""
    path = anim_cache_path(anim_name)
    try:
        os.makedirs(ANIMS_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        return path
    except Exception as error:
        logger.warning("Could not cache reusable animation '%s': %s", path, error)
        return None
