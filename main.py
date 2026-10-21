import argparse
import logging
import os

import src.custom_cats as custom_cats
import src.catgen.catalogue as catalogue
import src.util.ffdec_tools as ffdec
from src.import_paths import *
from src.custom_cats import NONE_TOKENS

DEBUG = True

#: the equipment a cat wears.  It is always exactly these three: a weapon and a
#: trinket are not part of a cat, so they are asked for separately.
EQUIP_SLOTS = ("head", "face", "neck")

EQUIP_USAGE = "head;face;neck"

def _is_none_token(value: str | None) -> bool:
    """Whether ``--weapon none`` style input asks for nothing."""
    return value is not None and value.strip().lower() in NONE_TOKENS


def parse_equipment_override(raw: str | None):
    """Parse a ``head;face;neck`` selection into a slot tuple.

    Empty fields mean "nothing in this slot".  Anything beyond the third field is
    dropped: a weapon or a trinket has no place in a cat's equipment.
    """
    if raw is None or raw == "":
        return None

    parts = [part.strip() for part in str(raw).split(";")]
    if not any(parts):
        return None

    head, face, neck = (parts + ["", "", ""])[:len(EQUIP_SLOTS)]
    return (head or None, face or None, neck or None)


def parse_handheld(weapon: str | None, trinket: str | None):
    """Parse ``--weapon`` / ``--trinket`` into a ``weapon;trinket`` request.

    ``None`` means the flag was not given at all: the cat's character file then
    decides, and an entry the file leaves out stays empty.  ``none`` asks for the
    slot to be empty explicitly.
    """
    if weapon is None and trinket is None:
        return None

    return [
        None if _is_none_token(weapon) else (weapon or "").strip() or None,
        None if _is_none_token(trinket) else (trinket or "").strip() or None,
    ]


def parse_cat_selection(raw: list[str] | None):
    if raw is None:
        return (None, "default", None)

    items = [str(part).strip() for part in raw]
    items = [item for item in items if item]
    if not items:
        return (None, "default", None)

    cat_id = items[0]
    if len(items) == 1:
        return (cat_id, "default", None)

    mode = items[1].lower()
    if mode == "default":
        return (cat_id, "default", None)
    if mode == "none":
        return (cat_id, "none", None)
    if mode == "custom":
        if len(items) >= 3:
            return (cat_id, "custom", parse_equipment_override(items[2]))
        return (cat_id, "interactive", None)

    return (cat_id, "custom", parse_equipment_override(";".join(items[1:])))


def main():
    parser = argparse.ArgumentParser(
        prog="Mewgenerate",
        description="Export custom cats with almost all available movements, currently catgen enemies only.",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-o", "--out-dir",
                        default=outDirDefault, help="Output directory")
    parser.add_argument("--ffdec", default=ffdecDefault,
                        help="Path to ffdec-cli executable")
    parser.add_argument("--force-redump", action="store_true",
                        help="Ignores asset cache.")
    parser.add_argument("-b", "--batch", action="store_true",
                        help="Export all cats in the current set")
    parser.add_argument("-a","--anim", "--anim-name", dest="anim_name", default=None,
                        help="Animation name to export (defaults to idleF when omitted)")
    parser.add_argument("--cat", nargs="*", metavar="CAT_ID|MODE|EQUIP", default=None,
                        help="Select a cat and equipment mode: --cat <cat-id> [default|custom|none] [head;face;neck]. \nThe equipment is always those three slots; a weapon or a trinket is asked for with --weapon / --trinket.\nExamples: --cat ButcherCat default,\n\t --cat MedicCat none,\n\t --cat DruidCat custom Head;Face;Neck")
    parser.add_argument("--cat2", nargs="*", metavar="CAT_ID|MODE|EQUIP", default=None,
                        help="Select the second cat and equipment mode: --cat2 <cat-id> [default|custom|none] [head;face;neck]. The second cat never carries a weapon or a trinket.")
    parser.add_argument("--cat-id", dest="cat_id_arg", default=None,
                        help="Id of the primary cat (non-interactive shortcut for --cat <id>)")
    parser.add_argument("--cat2-id", dest="cat2_id_arg", default=None,
                        help="Id of the second cat; supplying it avoids the interactive prompt when the animation contains a second character")
    parser.add_argument("--equip", dest="equip_arg", default=None,
                        help=f"Equipment of the primary cat as {EQUIP_USAGE} (empty item means none). Implies --cat <cat-id> custom")
    parser.add_argument("--equip2", dest="equip2_arg", default=None,
                        help="Equipment of the second cat as head;face;neck (empty item means none)")
    parser.add_argument("--weapon", dest="weapon_arg", default=None,
                        help="Weapon the primary cat's animation draws; 'none' renders without one. Independent of the equipment: the character file's weapon is used when this is omitted, and the animation decides in which frames it appears")
    parser.add_argument("--trinket", dest="trinket_arg", default=None,
                        help="Trinket the primary cat's animation draws; 'none' renders without one. Independent of the equipment: the character file's trinket is used when this is omitted, falling back to 'Chicken'")
    parser.add_argument("--no-equip", action="store_true",
                        help="Render the primary cat without any equipment")
    parser.add_argument("--no-equip2", action="store_true",
                        help="Render the second cat without any equipment")
    parser.add_argument("--no-gif", action="store_true",
                        help="Skip GIF assembly step.")

    args = parser.parse_args()

    logging.basicConfig(
        format="%(levelname)s: %(message)s",
        level=logging.DEBUG if args.verbose or DEBUG else logging.INFO,
    )

    if args.force_redump:
        ffdec.FORCE_REDUMP = True

    # The name lists in reusable/ are a convenience for anyone who needs to know
    # which ids the CLI takes; a failure there must never stop an export.
    try:
        catalogue.ensure_name_lists()
    except Exception as error:
        logging.warning("Could not refresh the name lists in %s: %s",
                        catalogue.NAME_LISTS_DIR, error)

    # The equipment and the handheld items are asked for separately: a weapon or
    # a trinket never becomes part of a cat's equipment list.
    equip_arg = args.equip_arg
    equip2_arg = args.equip2_arg
    handheld = parse_handheld(args.weapon_arg, args.trinket_arg)

    # --cat/--cat2 stay the primary spelling; --cat-id/--equip/--no-equip are
    # equivalent shortcuts for scripts that cannot answer prompts.
    cat_selection = list(args.cat) if args.cat else None
    if cat_selection is None and args.cat_id_arg:
        cat_selection = [args.cat_id_arg, "none" if args.no_equip else ("custom" if equip_arg else "default")]
        if equip_arg:
            cat_selection.append(equip_arg)

    cat2_selection = list(args.cat2) if args.cat2 else None
    if cat2_selection is None and args.cat2_id_arg:
        cat2_selection = [args.cat2_id_arg, "none" if args.no_equip2 else ("custom" if equip2_arg else "default")]
        if equip2_arg:
            cat2_selection.append(equip2_arg)

    if cat_selection:
        cat_id, equip_mode, equip_override = parse_cat_selection(cat_selection)
        args.cat_id = cat_id
        args.cat_mode = equip_mode
        args.cat_equip = equip_override if equip_mode in {"custom", "interactive"} and equip_override is not None else None
    else:
        args.cat_id = None
        args.cat_mode = "default"
        args.cat_equip = None

    if cat2_selection:
        cat2_id, equip2_mode, equip2_override = parse_cat_selection(cat2_selection)
        args.cat2_id = cat2_id
        args.cat2_mode = equip2_mode
        args.cat2_equip = equip2_override if equip2_mode in {"custom", "interactive"} and equip2_override is not None else None
    else:
        # The second cat is only rendered when the animation contains one, so its
        # equipment may still be chosen up front.
        args.cat2_id = None
        args.cat2_mode = "none" if args.no_equip2 else ("custom" if equip2_arg else "default")
        args.cat2_equip = parse_equipment_override(equip2_arg) if equip2_arg else None

    if not args.batch and not args.cat_id:
        parser.error("Either --cat <cat-id> [default|custom|none] ["
                     + EQUIP_USAGE + "], --cat-id <cat-id> or -b/--batch is required.")


    if args.batch:
        custom_cats.exportCustomCats_batch(
            args.ffdec,
            args.anim_name,
            args.out_dir,
            cat2_id=args.cat2_id,
            equip2_mode=args.cat2_mode,
            equip2=args.cat2_equip,
            generate_gif=not args.no_gif,
        )
        return

    custom_cats.exportCustomCats_interactive(
        args.ffdec,
        args.out_dir,
        args.cat_id,
        args.anim_name,
        args.cat_mode,
        args.cat_equip,
        args.cat2_id,
        args.cat2_mode,
        args.cat2_equip,
        not args.no_gif,
        handheld,
    )


if __name__ == "__main__":
    main()
