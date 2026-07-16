#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""crop.py — 像素裁剪 + Lanczos 放大 + 可选像素刻度线（分区细扫/交点取证用）。

用法: crop.py image.png -o crop.png --rect x0,y0,x1,y1 [--pad 20] [--scale 2] [--ruler]
退出码: 0 成功 / 3 环境、IO 或参数错误
--ruler 的刻度数字是**原图像素坐标**（方便在差异清单里引用原图 rect）。
"""
import argparse
import sys

import irlib

from PIL import Image, ImageDraw

RULER_STEP = 50
RULER_MARGIN = 22


def parse_rect(s):
    parts = [int(v) for v in s.split(",")]
    if len(parts) != 4:
        raise ValueError("rect 需要 4 个整数: x0,y0,x1,y1")
    x0, y0, x1, y1 = parts
    if x1 <= x0 or y1 <= y0:
        raise ValueError("rect 必须 x1>x0 且 y1>y0")
    return x0, y0, x1, y1


def add_ruler(im, ox0, oy0, scale):
    """左/上加边距画刻度；数字为原图坐标。"""
    w, h = im.size
    canvas = Image.new("RGB", (w + RULER_MARGIN, h + RULER_MARGIN), (245, 245, 245))
    canvas.paste(im, (RULER_MARGIN, RULER_MARGIN))
    d = ImageDraw.Draw(canvas)
    x = ((ox0 + RULER_STEP - 1) // RULER_STEP) * RULER_STEP
    while (x - ox0) * scale < w:
        sx = RULER_MARGIN + int((x - ox0) * scale)
        d.line([(sx, RULER_MARGIN - 6), (sx, RULER_MARGIN)], fill=(0, 0, 0))
        d.text((sx + 2, 2), str(x), fill=(0, 0, 0))
        x += RULER_STEP
    y = ((oy0 + RULER_STEP - 1) // RULER_STEP) * RULER_STEP
    while (y - oy0) * scale < h:
        sy = RULER_MARGIN + int((y - oy0) * scale)
        d.line([(RULER_MARGIN - 6, sy), (RULER_MARGIN, sy)], fill=(0, 0, 0))
        d.text((2, sy + 2), str(y), fill=(0, 0, 0))
        y += RULER_STEP
    return canvas


def main(argv=None):
    irlib.ensure_utf8_io()
    ap = argparse.ArgumentParser(description="像素裁剪放大")
    ap.add_argument("image")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--rect", required=True)
    ap.add_argument("--pad", type=int, default=20)
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--ruler", action="store_true")
    args = ap.parse_args(argv)

    try:
        rect = parse_rect(args.rect)
    except ValueError as e:
        sys.stderr.write("ERROR: %s\n" % e)
        return irlib.EXIT_ENV
    try:
        im = Image.open(args.image).convert("RGB")
    except OSError as e:
        sys.stderr.write("ERROR: 读图失败: %s\n" % e)
        return irlib.EXIT_ENV

    x0 = max(0, rect[0] - args.pad)
    y0 = max(0, rect[1] - args.pad)
    x1 = min(im.width, rect[2] + args.pad)
    y1 = min(im.height, rect[3] + args.pad)
    if x1 <= x0 or y1 <= y0:
        sys.stderr.write("ERROR: rect 与图像无交集\n")
        return irlib.EXIT_ENV
    out = im.crop((x0, y0, x1, y1))
    if args.scale != 1.0:
        out = out.resize((max(1, int(out.width * args.scale)),
                          max(1, int(out.height * args.scale))), Image.LANCZOS)
    if args.ruler:
        out = add_ruler(out, x0, y0, args.scale)
    try:
        out.save(args.output)
    except OSError as e:
        sys.stderr.write("ERROR: 写图失败: %s\n" % e)
        return irlib.EXIT_ENV
    sys.stdout.write("OK -> %s (crop=[%d,%d,%d,%d] scale=%s)\n"
                     % (args.output, x0, y0, x1, y1, args.scale))
    return irlib.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
