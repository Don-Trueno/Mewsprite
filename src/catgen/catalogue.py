"""The plain-text name lists that sit next to the artwork cache.

`reusable/` holds one file per kind of name the CLI accepts -- cat ids,
animations, and the five item slots -- as one name per line, so they can be read
and searched without digging through the SWFs or the ``.gon`` tables.

A list is written only when its file does not exist yet: an existing file is never
touched, so a hand-edited or trimmed list survives.  That also keeps the cost
where it belongs -- listing the animations has to parse both animation SWFs, which
must not happen on a run that already has the list.
"""

import logging
import os
from functools import partial
from typing import Callable

from src import items as items_mod
from . import animations

logger = logging.getLogger(__name__)

#: where the lists live.  Deliberately *not* `reusable.REUSABLE_DIR`: that one is
#: the artwork cache (`./cache`) and is git-ignored, while these lists are meant to
#: be readable in the repository.
NAME_LISTS_DIR = "./reusable"

ITEM_SLOTS = ("head", "face", "neck", "weapon", "trinket")

#: a line starting with this is a comment, not a name
COMMENT_PREFIX = "//"


def catIds() -> list[str]:
    """Every cat id ``--cat-id`` accepts."""
    from .. import custom_cats

    return sorted(cat.id for cat in custom_cats.getCustomCats())


def animNames() -> list[str]:
    """Every animation name ``--anim`` accepts."""
    return sorted(animations.getCatAnims())


def animLines() -> list[str]:
    """``anims.txt``: the animation names grouped by the SWF they come from.

    Unlike the other lists this one is not flat -- each group starts with a
    ``// <file>.swf`` comment so it is obvious where an animation is defined.  It
    reads the frame titles only, so no animation frames are built; parsing the
    SWFs themselves is still what makes this the slow list to produce.
    """
    lines: list[str] = []

    for swfPath, names in animations.getCatAnimSources():
        lines.append(f"{COMMENT_PREFIX} {os.path.basename(swfPath)}")
        lines.extend(names)

    return lines


def itemNames(slot: str) -> list[str]:
    """Every item id that can be worn in ``slot``.

    Variants (``variant_of`` entries) are left out: they carry no kind or frame of
    their own, so they cannot be worn or drawn as they are.
    """
    table = items_mod.getItemDict()
    return sorted(name for name, item in table.items()
                  if item.variant is None and item.kind == slot)


def _name_lists() -> list[tuple[str, Callable[[], list[str]]]]:
    """``(file name, producer)`` for every list, in the order they are written."""
    lists: list[tuple[str, Callable[[], list[str]]]] = [
        ("cat-id.txt", catIds),
        ("anims.txt", animLines),
    ]
    lists += [(f"{slot}-items.txt", partial(itemNames, slot))
              for slot in ITEM_SLOTS]
    return lists


def name_list_path(fileName: str) -> str:
    return os.path.join(NAME_LISTS_DIR, fileName)


def _write_names(path: str, names: list[str]) -> bool:
    """Write one name per line, unless the file is already there."""
    if os.path.exists(path):
        return False

    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            for name in names:
                handle.write(f"{name}\n")
    except OSError as error:
        logger.warning("Could not write the name list '%s': %s", path, error)
        return False

    logger.info("Wrote the name list '%s' with %d name(s)", path, len(names))
    return True


def ensure_name_lists() -> list[str]:
    """Write every name list that is missing; returns the paths written.

    A producer is only called for a missing file, so an up-to-date `reusable/`
    costs nothing but a handful of ``exists`` checks.
    """
    written: list[str] = []

    for fileName, produce in _name_lists():
        path = name_list_path(fileName)
        if os.path.exists(path):
            continue

        if _write_names(path, produce()):
            written.append(path)

    return written
