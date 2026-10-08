#!/usr/bin/env python3
"""
批量将文件夹中的 SVG 文件转换为 PNG（支持递归子文件夹）。
依赖：wand (需要 ImageMagick)

用法：
    python svg_to_png.py <输入文件夹> [--output 输出根目录] [--recursive] [--delete-svg] [--trim]

示例：
    python svg_to_png.py ./out/furniture --output ./out/furniture_png --trim
"""

import os
import sys
import argparse
from wand.image import Image
from wand.color import Color

def convert_svg_to_png(svg_path, png_path, trim=False):
    """将单个 SVG 文件转换为 PNG，可选自动裁剪空白边距"""
    with Image(filename=svg_path, background=Color('transparent')) as img:
        if trim:
            img.trim(color=Color('transparent'), fuzz=0.05)
        img.format = 'png'
        img.save(filename=png_path)

def main():
    parser = argparse.ArgumentParser(description="Batch convert SVG to PNG")
    parser.add_argument("input_dir", help="Input directory containing SVG files")
    parser.add_argument("--output", default=None, help="Output root directory (default: same as input_dir)")
    parser.add_argument("--recursive", action="store_true", help="Search subdirectories recursively")
    parser.add_argument("--delete-svg", action="store_true", help="Delete original SVG after conversion")
    parser.add_argument("--trim", action="store_true", help="Automatically trim transparent borders")
    args = parser.parse_args()

    if not os.path.isdir(args.input_dir):
        print(f"Error: {args.input_dir} is not a directory")
        sys.exit(1)

    # 确定输出根目录
    out_root = args.output if args.output else args.input_dir

    # 收集所有 SVG 文件
    svg_files = []
    if args.recursive:
        for root, dirs, files in os.walk(args.input_dir):
            for f in files:
                if f.lower().endswith('.svg'):
                    svg_files.append(os.path.join(root, f))
    else:
        for f in os.listdir(args.input_dir):
            if f.lower().endswith('.svg'):
                svg_files.append(os.path.join(args.input_dir, f))

    if not svg_files:
        print("No SVG files found.")
        return

    for svg_path in svg_files:
        # 计算相对路径和输出 PNG 路径
        rel_path = os.path.relpath(svg_path, args.input_dir)
        png_path = os.path.join(out_root, rel_path[:-4] + '.png')
        os.makedirs(os.path.dirname(png_path), exist_ok=True)

        try:
            convert_svg_to_png(svg_path, png_path, trim=args.trim)
            print(f"Converted: {svg_path} -> {png_path}")
            if args.delete_svg:
                os.remove(svg_path)
                print(f"Deleted: {svg_path}")
        except Exception as e:
            print(f"Failed to convert {svg_path}: {e}")

    print("Done.")

if __name__ == "__main__":
    main()