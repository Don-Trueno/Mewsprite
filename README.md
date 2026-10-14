# Mewsprite

## 项目介绍
本项目由Mewgenerate<!--仓库链接？-->分叉，旨在更方便地自定义不同动作与猫族生物（Catgen）的动作，生成gif动画并导出。

## 仓库结构
```
Mewsprite
  ├─ .github ----------------- // GitHub 配置文件、Agent指令等
  ├─ cache ------------------- // 缓存的形状文件等
  ├─ data -------------------- // 解压后的resources.gpak
  │   ├─ auto
  │   ├─ data
  │   ├─ levels
  │   ├─ shaders
  │   ├─ swfs
  │   ├─ ...
  │   └─ textures
  ├─ Mewgenics-Level-Editor -- // _目前还有需要使用这个工具吗？_
  ├─ out
  │   ├─ batch --------------- // 批量导出，再次运行批量导出前会清理此文件夹
  │   │   └─ ...
  │   └─ ...
  ├─ reusable
  └─ src --------------------- // 源码
      ├─ catgen -------------- // 定义猫族生物的一些工具类和工具函数等
      └─ util ---------------- // 解析SWF、GON格式文件的一些工具
```

## 使用方法
### 依赖项
* [Mewgenics 本体](https://store.steampowered.com/app/686060/Mewgenics/)
* [Mewgenics_gpak_util](https://github.com/Tiftid/mewgenics_gpak_util)
* [JPEXS Free Flash Decompiler](https://github.com/jindrapetrik/jpexs-decompiler)

### 步骤
1. 从 Steam 安装目录找到`resources.gpak`
    * 一般在`steamapps/common/Mewgenics/resources.gpak`）。
2. 使用 gpak util 解压缩此 gpak 包，将提取出的所有文件放在本项目的`./data/`目录下。
3. 找到[import_paths.py](./src/import_paths.py)，修改 FFDec cli 的路径为实际路径。
4. 然后即可通过命令行运行（见 [#CLI](#CLI)）。
<!--TODO: GUI或WebUI？-->

目前本项目已跳过对除`catpart.swf`、`catanis.swf`、`catanis2.swf`等的转储。但首次运行需仍很长时间（>10分钟）以完成转储工作。

### 缓存
每次运行程序时，会缓存一些动画元数据、部件形状供未来使用：
* `./reusable/anims/<anim>.json`：动画元数据，包含此动画所需的部件（定义标签）池（`tag_pool`）、每帧中各对象（控制标签）的所需标签（`tag`）、深度（`depth`）、形状变换矩阵（`transform`，对应`matrix`）。
* `./reusable/shapes/`：本次使用的所有部件形状的SVG图片。有需求使用在别的地方的话，可以自行使用InkScape修剪图像边界。
  * 猫的部件形如 `<猫名>-<部件>[-<表情>[-<头>-<面>-<颈>]].svg`。
  * 武器与饰品类型的部件，形如 `<物品名>.svg`（例：`ButcherHook.svg`、`Chicken.svg`）：它们不属于任何一只猫，多只猫拿同一件武器共用同一份缓存；换武器也不会让猫自身的部件缓存失效。

交互式模式下，如果本次导出时在`./reuseable`里命中了动画元数据与所有部件形状文件（含武器/饰品），则不再读取原始`.swf`文件。批量模式只寻找动画元数据，部件形状仍然每次依赖原始`.swf`文件。使用`--force-redump`以忽略`./cache`下资产文件缓存。

### CLI
```
python main.py [-h] [-v] [-o OUT_DIR] [--ffdec FFDEC] [--force-redump] [-b]
               [--anim ANIM_NAME] [--cat [CAT_ID|MODE|EQUIP ...]]
               [--cat2 [CAT_ID|MODE|EQUIP ...]] [--cat-id CAT_ID]
               [--cat2-id CAT2_ID] [--equip EQUIP] [--equip2 EQUIP2]
               [--weapon ITEM_NAME|none] [--trinket ITEM_NAME|none]
               [--no-equip] [--no-equip2] [--no-gif]

options:
  -h, --help                            显示帮助信息（英文）并退出
  -v, --verbose
  -o, --out-dir OUT_DIR                 指定导出路径的根目录（默认值 ./out）
  --ffdec FFDEC                         指定 ffdec-cli 可执行文件的路径
  --force-redump                        忽略资产文件缓存
  -b, --batch                           有此标记时为批量模式，否则为交互式模式
  -a, --anim, --anim-name [ANIM_NAME]   指定导出动画的名字
  --cat <cat-id> default
                 custom [head;face;neck]
                 none                   指定导出猫的名字、装备模式、装备
                                        <cat-id>: 猫的名字（内部名，例：ButcherCat）
                                        default: 使用默认装备
                                        custom [head;face;neck]: 使用指定的三个装备，
                                            必须一次指定，使用英文分号分隔，每项可留空
                                        none: 不渲染猫的装备
  --cat <cat-id> [default|custom|none] [head;face;neck]
                                        预输入第二猫的名字、装备，指定后运行时不再询问
  --cat-id CAT_ID                       等效 --cat <cat-id>
  --equip [head;face;neck]              第一猫的装备，格式和顺序同前
  --weapon [ITEM_NAME|none]             第一猫的武器；省略时使用默认武器（没有则不带）
  --trinket [ITEM_NAME|none]            第一猫的饰品（默认值 Chicken）
  --no-equip                            不渲染第一猫的装备（不影响武器/饰品）
  --cat2-id CAT2_ID                     预输入第二猫的名字；指定后运行时不再询问
  --equip2 [head;face;neck]             预输入第二猫的装备，格式和顺序同前
  --no-equip2                           不渲染第二猫的装备
  --no-gif                              （调试用）跳过组装GIF图片步骤（仍逐帧导出SVG图片）
```
快速参考： [ 猫名 ] | [ 动画 ](./reusable/anims.txt) | 装备 - [ 头部 ] [ 面部 ] [ 颈部 ] | 手持 - [ 武器 ] [ 饰品 ]

上述文件会在缺失或首次运行时由程序自动生成。

**示例：**（在项目的根目录开启终端并运行）

<figure>导出 ButcherCat 的 idleF 动画，装备使用默认装备：

`python main.py --anim idleF --cat ButcherCat`

导出 ButcherCat 的 idleF 动画，指定头部装备为 CoinBag：

`python main.py --anim idleF --cat ButcherCat custom CoinBag;;`

导出 ButcherCat 对 ThiefCat 的 bearHugF 动画，两只猫均使用默认装备：

`python main.py --anim bearHugF --cat ButcherCat --cat2 ThiefCat`

导出 ButcherCat 的 ButcherIdleF 动画，武器换成 CaveCatClub（装备保持默认）：

`python main.py --anim ButcherIdleF --cat ButcherCat --weapon CaveCatClub`

不戴武器，也不穿装备：

`python main.py --anim ButcherIdleF --cat ButcherCat none --weapon none`</figure>


## Developer Info

`src/parse_csv.py` contains the function `parse_csv(filepath)`, this is useful for translations found in `./data/data/text`.

`src/parse_gon.py` contains the function `parse_gon(filepath)`, this is useful for parsing `.gon` files into Python objects. Unlike a normal parser, comments are kept as a list of strings in the `"__COMMENTS__"` field of the object. Note that arrays are parsed as dictionaries so that `"__COMMENTS__"` can be present, they still use numeric indexes however.

`src/parse_swf.py` contains the function `parse_swf(filepath)`, this is useful for getting sprites and animations **WORK IN PROGRESS!!!**

Higher-level functionality is also provided in files named based off what they parse for Mewgenics. Ex. `src/keywords.py` handles strings for buffs and debuffs (keywords).

### 类型检查

仓库用 [mypy](https://mypy.readthedocs.io/) 做静态类型检查，配置在 `mypy.ini`（`mypy_path = .` + `explicit_package_bases`，因为 `src` 是使用相对导入的包）。

```bash
.venv/Scripts/python.exe -m mypy                      # 检查 src/、main.py、svg_to_png.py
.venv/Scripts/python.exe -m mypy -p src.custom_cats   # 只检查单个模块
```