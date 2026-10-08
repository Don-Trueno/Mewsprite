### CLI
```
python main.py [-h] [-v] [-o OUT_DIR] [--ffdec FFDEC] [--force-redump] [-b]
               [--anim ANIM_NAME] [--cat [CAT_ID|MODE|EQUIP ...]]
               [--cat2 [CAT_ID|MODE|EQUIP ...]] [--cat-id CAT_ID]
               [--cat2-id CAT2_ID] [--equip EQUIP] [--equip2 EQUIP2]
               [--no-equip] [--no-equip2] [--no-gif]

options:
  -h, --help            show this help message and exit
  -v, --verbose
  -o, --out-dir OUT_DIR
                        Output directory (default: ./out)
  --ffdec FFDEC         Path to ffdec-cli executable, used for dumping assets from SWF files.
  --force-redump        Ignores asset cache.
  -b, --batch           Export all cats in the current set
  --anim, --anim-name ANIM_NAME
                        Animation name to export
  --cat [CAT_ID|MODE|EQUIP ...]
                        Select a cat and equipment mode: --cat <cat-id> [default|custom|none] [head;face;neck]
  --cat2 [CAT_ID|MODE|EQUIP ...]
                        Select the second cat and equipment mode
  --cat-id CAT_ID       Non-interactive shortcut for --cat <id>
  --cat2-id CAT2_ID     Second cat id; supplying it avoids the interactive prompt
  --equip EQUIP         Primary cat equipment as head;face;neck
  --equip2 EQUIP2       Second cat equipment as head;face;neck
  --no-equip            Render the primary cat without any equipment
  --no-equip2           Render the second cat without any equipment
  --no-gif              Skip GIF assembly (the SVG frame sequence is still written)
```
