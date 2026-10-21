# Mewsprite

[English](README.md) | [简体中文](README.zh.md)
## Overview
This project is a fork from [Mewgenerate](https://github.com/Sploder12/mewgenerate), providing more convient way to make catgen animations and export them as `.gif` image.

## Structure
```
Mewsprite
  ├─ .github ----------------- // GitHub configures, Agent Instructions, etc.
  ├─ cache ------------------- // Cached shapes
  ├─ data -------------------- // Put unpacked resources.gpak files here.
  │   ├─ auto
  │   ├─ data
  │   ├─ levels
  │   ├─ shaders
  │   ├─ swfs
  │   ├─ ...
  │   └─ textures
  ├─ out
  │   ├─ batch --------------- // Store batch exported anims, will cleanup if export again.
  │   │   └─ ...
  │   └─ ...
  ├─ reusable ---------------- // Name lists for the CLI
  └─ src --------------------- // Source codes
      ├─ catgen -------------- // Catgen class and functions definition
      └─ util ---------------- // Tools use to parse .gon, .swf files
```

## How to use
### Dependencies
* [Mewgenics](https://store.steampowered.com/app/686060/Mewgenics/)
* [Mewgenics_gpak_util](https://github.com/Tiftid/mewgenics_gpak_util)
* [JPEXS Free Flash Decompiler](https://github.com/jindrapetrik/jpexs-decompiler)

### Step-to-step instruction
1. Find `resources.gpak` in Steam installation directory.
    * Usually located in `steamapps/common/Mewgenics/resources.gpak`.
2. Use gpak util tool to unpack this file, then move extracted files to `./data/` in root directory.
3. Open [import_paths.py](./src/import_paths.py), then change the actual installation path of ffdec.
4. Then feel free making GIFs! ([#CLI](#CLI))

Currently, this project has skipped the dumping of files other than `catpart.swf`, `catanis.swf`, `catanis2.swf`, etc. However, the first run still takes a very long time (more than 10 minutes) to complete the dumping process.

### Caching
Each time the program is run, some animation metadata and component shapes are cached for future use:
* `./cache/anims/<anim>.json`: Animation metadata, including the component (definition tags) pool (`tag_pool`) required for this animation, the required tags for each object (control tags) in each frame (`tag`), depth (`depth`), and shape transformation matrix (`transform`, corresponding to `matrix`).
* `./cache/shapes/`: SVG images of all the components used this time. If needed to be used elsewhere, the images can be trimmed by yourself using InkScape.
* The component of the cat is like `<cat name>-<component>[-<expression>[-<head>-<face>-<neck]].svg`.
* Components of weapons and accessories, like `<item name>.svg` (e.g., `ButcherHook.svg`, `Chicken.svg`): They do not belong to any specific cat. Multiple cats sharing the same weapon will use the same cached version; changing the weapon will not invalidate the cat's component cache.

In interactive mode, if the animation metadata and all component shape files (including weapons/accessories) are found in `./cache` during this export, the original `.swf` files will not be read. In batch mode, only the animation metadata is searched for, and the component shapes still rely on the original `.swf` files each time. Use `--force-redump` to ignore the asset file cache in `./cache`.

### CLI
```
python main.py [-h] [-v] [-o OUT_DIR] [--ffdec FFDEC] [--force-redump] [-b]
               [--anim ANIM_NAME] [--cat [CAT_ID|MODE|EQUIP ...]]
               [--cat2 [CAT_ID|MODE|EQUIP ...]] [--cat-id CAT_ID]
               [--cat2-id CAT2_ID] [--equip EQUIP] [--equip2 EQUIP2]
               [--weapon ITEM_NAME|none] [--trinket ITEM_NAME|none]
               [--no-equip] [--no-equip2] [--no-gif]

options:
  -h, --help                            Display help messages and exit
  -v, --verbose
  -o, --out-dir OUT_DIR                 Specify the root directory of the export path
                                        (Default: ./out)
  --ffdec FFDEC                         Specify the path of the ffdec-cli executable
  --force-redump                        Ignore the asset file cache
  -b, --batch                           If this flag exists, run in batch mode;
                                        otherwise, run in interactive mode
  -a, --anim, --anim-name [ANIM_NAME]   Specify the animation name 
  --cat <cat-id> default
                 custom [head;face;neck]
                 none                   Specify cat name(id), equip mode, equip items
                                        <cat-id>  Cat name (internal name e.g. ButcherCat)
                                        default:  Use default equip items set
                                        custom [head;face;neck]: Use the specified three 
                                              equip items. must be specified at once,
                                              separated by semicolons, each item can be
                                              left blank.
                                        none: Do not render any equip item
  --cat <cat-id> [default|custom|none] [head;face;neck]
                                        Pre-input second cat's name & equip items. If exist 
                                              it will not be asked again during the run.
  --cat-id CAT_ID                       Equivalent to --cat <cat-id>
  --equip [head;face;neck]              Primary cat's equip item, same format and order.
  --weapon [ITEM_NAME|none]             Primary cat's weapon; if omitted, use class default
                                              item or none.
  --trinket [ITEM_NAME|none]            Primary cat's trinket/consumable (Default: Chicken)
  --no-equip                            Don't render equip items (don't affect weapon/trinket)
  --cat2-id CAT2_ID                     Pre-input second cat's name. If exist, it will not be
                                              asked again during the run.
  --equip2 [head;face;neck]             Pre-input second cat's equip.
  --no-equip2                           Don't render second cat's equip items.
  --no-gif                              (DEBUG only)  Skip the step of assembling GIF images
                                              (still export SVG images frame by frame)
```

### Name lists

`./reusable/` holds one plain-text list per kind of name the CLI accepts, one name per line:

| File | What it lists | Flag |
| --- | --- | --- |
| `cat-id.txt` | cat ids | `--cat-id` / `--cat2-id` |
| `anims.txt` | animation names | `--anim` |
| `head-items.txt` | head armor | `--equip <head>;...` |
| `face-items.txt` | face armor | `--equip ...;<face>;...` |
| `neck-items.txt` | neck armor | `--equip ...;;<neck>` |
| `weapon-items.txt` | weapons | `--weapon` |
| `trinket-items.txt` | trinkets | `--trinket` |

A list is written automatically the first time its file is missing; an existing file is never touched, so a trimmed or hand-edited list survives. Listing the animations has to parse both animation SWFs (about half a minute), which is why it only happens when `anims.txt` is absent. Delete a file to regenerate it — that is also how you pick up newly added names.

### Examples

Open the terminal in the root directory of the project and run

<figure>Export ButcherCat's idleF, using his default equip items:

`python main.py --anim idleF --cat ButcherCat`

Export ButcherCat's idleF, while specify the head item as CoinBag and other two as none:

`python main.py --anim idleF --cat ButcherCat custom CoinBag;;`

Export ButcherCat and ThiefCat's bearHugF, using both cats' default equip items:

`python main.py --anim bearHugF --cat ButcherCat --cat2 ThiefCat`

Export ButcherCat's ButcherIdleF, while specify weapon item as CaveCatClub (still use default equip items):

`python main.py --anim ButcherIdleF --cat ButcherCat --weapon CaveCatClub`

Same as above, with neither equip items nor weapon item:

`python main.py --anim ButcherIdleF --cat ButcherCat none --weapon none`</figure>


## Developer Info

`src/parse_csv.py` contains the function `parse_csv(filepath)`, this is useful for translations found in `./data/data/text`.

`src/parse_gon.py` contains the function `parse_gon(filepath)`, this is useful for parsing `.gon` files into Python objects. Unlike a normal parser, comments are kept as a list of strings in the `"__COMMENTS__"` field of the object. Note that arrays are parsed as dictionaries so that `"__COMMENTS__"` can be present, they still use numeric indexes however.

`src/parse_swf.py` contains the function `parse_swf(filepath)`, this is useful for getting sprites and animations **WORK IN PROGRESS!!!**

Higher-level functionality is also provided in files named based off what they parse for Mewgenics. Ex. `src/keywords.py` handles strings for buffs and debuffs (keywords).

### Type Checking

The repository uses [mypy](https://mypy.readthedocs.io/) for static type checking. The configuration is in `mypy.ini` (with `mypy_path = .` + `explicit_package_bases`, since `src` is a package using relative imports).

```bash
.venv/Scripts/python.exe -m mypy                      # Check src/, main.py, svg_to_png.py
.venv/Scripts/python.exe -m mypy -p src.custom_cats   # Only check a single module
```