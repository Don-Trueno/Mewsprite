import os

# ================================================== #
# 改成ffdec实际安装的路径，指定FFDEC的cli文件而不是本体。
ffdecDefault = r"D:/Program Files/FFDec/ffdec-cli.exe" if os.name == "nt" else "ffdec-cli"
outDirDefault = r"./out"
# ================================================== #

# ================================================== #
# 名称修复，当同一猫在NAME2系列文件与NAME1系列文件中使用不同的名字时进行转换。
# 如运行遇到问题可尝试在这里添加转换。
# 格式： "在NAME2的名字": "在NAME1中的名字"
namefix = {
    "Pebbles": "ColorlessCat_Tutorial",
    "TerminatorCat": "Terminator1",
    "Terminator2Cat": "Terminator2"
}
# ================================================== #

# ================================================== #
# 如果你不熟悉，不要修改下面的路径。
#
# : Catgen definiton; Required parts, palettes, etc.
CUSTOM_CAT_GON = "./data/data/custom_cats.gon"  # NAME1
# : Face & Voice definiton
CATGEN_GON = "./data/data/catgen.gon"           # NAME1
# : SWF assets
CATPARTS_SWF = "./data/swfs/catparts.swf"       # NAME1

# : Required equip data
CAT_MINIBOSSES_GON = "./data/data/characters/cat_minibosses.gon"    # NAME2
# : Required equip data (for terminators & miniboss cats' terminator verion)
TERMINATOR_GON = "./data/data/characters/terminator.gon"            # NAME2

