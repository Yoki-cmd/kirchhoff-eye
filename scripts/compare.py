#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""compare.py — 原图 vs 渲染图 对比图生成（供模型逐区审读，不产相似度数字）。

用法: compare.py original.png rendered.png -o cmp.png [--mode side|overlay|both]
退出码: 0 成功 / 3 环境或 IO 错误
side（主用）：等比缩放同高并排，标注 ORIGINAL/RENDERED；
overlay：内容 bbox 裁剪对齐后 原图灰底 + 渲染图红色 50% 叠加（不配准，仅粗看）。
"""
import argparse
import sys

import irlib

from PIL import Image, ImageDraw, ImageOps

BANNER_H = 28
GAP = 16
BG = (255, 255, 255)


def load_rgb(path):
    return Image.open(path).convert("RGB")


def content_bbox(im):
    """内容包围盒：反相灰度的非零区域；全白图返回整幅。"""
    inv = ImageOps.invert(im.convert("L"))
    return inv.getbbox() or (0, 0, im.width, im.height)


def scale_to_height(im, h):
    w = max(1, int(round(im.width * (float(h) / im.height))))
    return im.resize((w, h), Image.LANCZOS)


def make_side(orig, rend, height):
    a = scale_to_height(orig, height)
    b = scale_to_height(rend, height)
    w = a.width + GAP + b.width
    canvas = Image.new("RGB", (w, height + BANNER_H), BG)
    canvas.paste(a, (0, BANNER_H))
    canvas.paste(b, (a.width + GAP, BANNER_H))
    d = ImageDraw.Draw(canvas)
    d.text((4, 6), "ORIGINAL", fill=(0, 0, 0))
    d.text((a.width + GAP + 4, 6), "RENDERED", fill=(200, 0, 0))
    d.line([(a.width + GAP // 2, 0), (a.width + GAP // 2, canvas.height)],
           fill=(160, 160, 160), width=1)
    return canvas


def make_overlay(orig, rend):
    ob = orig.crop(content_bbox(orig))
    rb = rend.crop(content_bbox(rend))
    rb = rb.resize(ob.size, Image.LANCZOS)
    base = ob.convert("L").point(lambda v: 128 + v // 2).convert("RGB")  # 原图淡灰
    rend_l = rb.convert("L")
    red = Image.new("RGB", ob.size, (255, 0, 0))
    alpha = rend_l.point(lambda v: (255 - v) // 2)  # 渲染图越黑越红，50% 上限
    return Image.composite(red, base, alpha)


def main(argv=None):
    irlib.ensure_utf8_io()
    ap = argparse.ArgumentParser(description="原图 vs 渲染图对比")
    ap.add_argument("original")
    ap.add_argument("rendered")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--mode", choices=("side", "overlay", "both"), default="side")
    args = ap.parse_args(argv)

    try:
        orig = load_rgb(args.original)
        rend = load_rgb(args.rendered)
    except OSError as e:
        sys.stderr.write("ERROR: 读图失败: %s\n" % e)
        return irlib.EXIT_ENV

    height = irlib.load_config().get("compare", {}).get("side_height_px", 1200)
    try:
        if args.mode == "side":
            out = make_side(orig, rend, height)
        elif args.mode == "overlay":
            out = make_overlay(orig, rend)
        else:
            side = make_side(orig, rend, height)
            over = make_overlay(orig, rend)
            over = scale_to_height(over, height // 2)
            w = max(side.width, over.width)
            out = Image.new("RGB", (w, side.height + GAP + over.height), BG)
            out.paste(side, (0, 0))
            out.paste(over, (0, side.height + GAP))
        out.save(args.output)
    except (OSError, ValueError) as e:
        sys.stderr.write("ERROR: 生成对比图失败: %s\n" % e)
        return irlib.EXIT_ENV
    sys.stdout.write("OK -> %s (mode=%s)\n" % (args.output, args.mode))
    return irlib.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
