## 0.2.2
(This modification is assisted by DeepSeek-V4.1-flash)

### Fixes
- Fixed the issue where cat's left eye was incorrectly flipped.
- Fix the issue where the position of the second cat is too low in the animation where the second cat is involved as a whole (e.g. `bearHugF`).

### Additions
- Now you can export animations from `2d_catanis.swf`. However, some animations may have issues.
- Now `./reusable/` holds one plain-text list per kind of name the CLI accepts, one name per line.

### Misc.
- Let `Edmund` and `Tyler` join in the default batch-export cats list.

## 0.2.1
(This modification is assisted by DeepSeek-V4.1-flash)

### Fixes
- Fixed the issue where the cat's mouth was positioned abnormally high when looking to the left.
- Now, when exporting in batches, if the input animation name is incorrect, the respective idle actions for each profession will be correctly applied.
- For the Monk (`MonkCat`), only his melee mode idle actions are used.

### Additions
- Added support for the cat's weapons (Weapon) and accessories (Trinket, Consumable).
- CLI now includes fields `--weapon <id|none>` and `--trinket <id|none>`.
- `SHAPE_CACHE_VERSION` has been upgraded to `6`: old caches will be automatically rebuilt.
- Added parsing of the `colorTransform` field from the original SWF, allowing the cat to be colored in the animation.

## 0.2.0
(This modification is assisted by DeepSeek-V4.1-flash)

### Changes
- Optimized the GIF generation logic of the original project to stream frame-by-frame writing, significantly reducing memory and disk usage.
- Now, the final GIF image will correctly crop the surrounding blank pixels.
- Removed the dependency on InkScape.

**Performance Comparison**

(Using 310 frames, 1239×1242, Q16-HDRI, 8 bytes per pixel image for testing)

|| Original wand sequence + coalesce | Improved version |
|----|:----:|:----:|
| Peak Memory | 14.6 GB | 600 MB |
| Peak Temporary Directory Size | ~3.0 GB | ~0 |
| GIF Assembly Time | 354 s | 132 s |
| GIF Size | 8.12 MB | 6.57 MB |