#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ir2tikz.py — IR → circuitikz 确定性序列化器（无任何自动布局）。

用法: ir2tikz.py ir.json -o out.tex [--fragment]
退出码: 0 成功（W 级警告打到 stderr）/ 2 validate E 级失败（垃圾不进）/ 3 IO 错误
输出结构与写法规范：references/circuitikz-style.md（金样 tests/golden/*/golden.tex 同构）。
每次自动产 <out>.debug.tex：浅灰 0.5 网格 + 坐标刻度 + 红色元件 id
（debug 文件是诊断产物，允许内联样式，不受 style §12 约束）。
"""
import argparse
import re
import sys

import irlib
import validate_ir
from irlib import GeomIndex, IRModel, Report, quant

# l=/a= 四方向查表（probe04 实测）：travel -> {side: key}
LABEL_KEY = {
    "right": {"above": "l", "below": "l_"},
    "left":  {"above": "l_", "below": "l"},
    "up":    {"left": "l", "right": "l_"},
    "down":  {"left": "l_", "right": "l"},
}
VALUE_KEY = {
    "right": {"above": "a^", "below": "a"},
    "left":  {"above": "a", "below": "a^"},
    "up":    {"left": "a^", "right": "a"},
    "down":  {"left": "a", "right": "a^"},
}
# 行进方向的左手侧（缺省 label 侧）与右手侧（缺省 value 侧）
PORT_SIDE = {"right": "above", "left": "below", "up": "left", "down": "right"}
STARBOARD = {"right": "below", "left": "above", "up": "right", "down": "left"}

# 两端件 IR type -> to[] 名现由 catalog/components.json 派生，见 irlib.TO_NAME
# （probe01/02 实测；INVERT 见 irlib.INVERT_TYPES）。本文件引用 irlib.TO_NAME[...]。
ANCHOR_OPP = {"right": "west", "left": "east", "above": "south", "below": "north"}

# 电流箭头方向 -> 单位向量（dir 约定同 rotate：0=+x, 90=+y, 逆时针）
ARROW_UNIT = {0: (1.0, 0.0), 90: (0.0, 1.0), 180: (-1.0, 0.0), 270: (0.0, -1.0)}
ANNOTATION_DIRECTION = {"right": 0, "up": 90, "left": 180, "down": 270}
ARROW_LEN = 0.6  # 覆盖在导线上的短箭头长度

# v1.1 label_gap/value_gap：side -> 外法向单位向量（独立标签节点 = 参考点 + 法向×gap）
SIDE_NORMAL = {"above": (0.0, 1.0), "below": (0.0, -1.0),
               "left": (-1.0, 0.0), "right": (1.0, 0.0)}


def fmt(v):
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return ("%.4f" % v).rstrip("0").rstrip(".")


def fmt_pt(p):
    return "(%s,%s)" % (fmt(p[0]), fmt(p[1]))


def comment_text(value):
    """Keep untrusted metadata on one TeX comment line."""
    text = "".join(" " if ord(ch) < 32 or ch in "\u2028\u2029" else ch for ch in str(value))
    return text.replace("^^", "^ ^")


def travel_of(frm, to):
    dx, dy = to[0] - frm[0], to[1] - frm[1]
    if abs(dx) >= abs(dy):
        return "right" if dx >= 0 else "left"
    return "up" if dy >= 0 else "down"


class Serializer(object):
    def __init__(self, ir, anchors, config):
        self.ir = ir
        self.model = IRModel(ir, anchors)
        self.geom = GeomIndex(self.model)
        self.config = config
        self.coords = self._pick_net_coordinates()  # quant key -> net 名
        self.jumps = self._index_jumps()            # quant key -> (节点名, coord)
        self.component_annotation_kinds = {}
        for annotation in ir.get("annotations", []):
            target = annotation.get("target", {})
            if "component" in target and annotation.get("kind") in ("component_id", "component_value"):
                self.component_annotation_kinds.setdefault(target["component"], set()).add(annotation["kind"])
        # v1.1 scale 的两端件基数：单一真源 = config.style.ctikzset 里的 bipoles/length，
        # emit_two 输出 per-instance length = 基数 × scale（解析不到时按 circuitikz 默认 1.0）。
        m = re.search(r"bipoles/length=([0-9.]+)cm",
                      config.get("style", {}).get("ctikzset", ""))
        self.bipole_base = float(m.group(1)) if m else 1.0

    # -------------------------------------------------- 预索引

    def _net_order(self):
        declared = [n.get("name") for n in self.ir.get("nets", [])]
        used = sorted(self.geom.net_members().keys())
        return declared + [n for n in used if n not in declared]

    def _pick_net_coordinates(self):
        """每 net 至多一个 named coordinate：junction 优先，否则首个 wire xy 顶点。"""
        members = self.geom.net_members()
        picked = {}
        for net in self._net_order():
            if net not in members:
                continue
            root = self.geom.root_of(members[net][0][2])
            cand = None
            for j in self.ir.get("junctions", []):
                k = quant(tuple(j["at"]))
                if self.geom.uf.find(k) == root:
                    cand = (k, tuple(j["at"]))
                    break
            if cand is None:
                for wire in self.ir.get("wires", []):
                    for p in wire.get("points", []):
                        if "xy" in p and self.geom.uf.find(quant(tuple(p["xy"]))) == root:
                            cand = (quant(tuple(p["xy"])), tuple(p["xy"]))
                            break
                    if cand:
                        break
            if cand and cand[0] not in picked:
                picked[cand[0]] = (net, cand[1])
        return picked

    def _index_jumps(self):
        out = {}
        n = 0
        for c in self.ir.get("crossings", []):
            if c.get("style") == "jump":
                n += 1
                out[quant(tuple(c["at"]))] = ("XJ%d" % n, tuple(c["at"]))
        return out

    # -------------------------------------------------- 坐标/引用输出

    def ref(self, coord, kind, raw):
        """wire 点 → TikZ 引用：多端 pin 用 anchor；重合 named coordinate 用名；其余具体坐标。"""
        if kind == "pin:multi":
            cid, pname = raw["pin"].split(".", 1)
            comp = self.model.components[cid]
            entry = self.model.anchor_entry(comp)
            anchor = entry["pins"][pname]["anchor"]
            return "(%s.%s)" % (cid, anchor)
        if kind == "node":
            return "(%s)" % raw["node"]
        k = quant(coord)
        if k in self.coords:
            return "(%s)" % self.coords[k][0]
        return fmt_pt(coord)

    # -------------------------------------------------- 元件

    def emit_two(self, comp):
        frm, to = tuple(comp["from"]), tuple(comp["to"])
        opts = [irlib.TO_NAME[comp["type"]]]
        if comp["type"] in irlib.INVERT_TYPES:
            opts.append("invert")
        travel = travel_of(frm, to)
        owned = self.component_annotation_kinds.get(comp["id"], set())
        extra = []  # v1.1 gap 标签：退出 to[] 选项，改独立节点（缺省时 l=/a= 原样）
        if "component_id" not in owned and comp.get("label_at") is not None and comp.get("label"):
            extra.append("\\node[anchor=center] at %s {$%s$};" % (
                fmt_pt(tuple(comp["label_at"])), comp["label"]))
        elif "component_id" not in owned and comp.get("label"):
            side = comp.get("label_side") or PORT_SIDE[travel]
            if comp.get("label_gap") is not None:
                extra.append(self._gapped_two_label(frm, to, side,
                                                    comp["label"], comp["label_gap"]))
            else:
                key = LABEL_KEY[travel].get(side, "l")
                opts.append("%s=$%s$" % (key, comp["label"]))
        if "component_value" not in owned and comp.get("value"):
            side = comp.get("value_side") or STARBOARD[travel]
            if comp.get("value_gap") is not None:
                extra.append(self._gapped_two_label(frm, to, side,
                                                    comp["value"], comp["value_gap"]))
            else:
                key = VALUE_KEY[travel].get(side, "a")
                opts.append("%s=$%s$" % (key, comp["value"]))
        opts.append("name=%s" % comp["id"])
        if comp.get("scale") is not None:
            opts.append("/tikz/circuitikz/bipoles/length=%scm"
                        % fmt(self.bipole_base * comp["scale"]))
        return ["\\draw %s to[%s] %s;" % (fmt_pt(frm), ", ".join(opts), fmt_pt(to))] + extra

    def _gapped_two_label(self, frm, to, side, text, gap):
        """两端件 gap 标签：锚定 side 反侧，置于中点 + side 法向 × gap（与编辑器几何一致）。"""
        nx, ny = SIDE_NORMAL[side]
        pos = ((frm[0] + to[0]) / 2.0 + nx * gap, (frm[1] + to[1]) / 2.0 + ny * gap)
        return "\\node[anchor=%s] at %s {$%s$};" % (ANCHOR_OPP[side], fmt_pt(pos), text)

    def emit_multi(self, comp):
        entry = self.model.anchor_entry(comp)
        opts = [entry["node"]]
        if comp.get("mirror"):
            opts.append("xscale=-1")
        if comp.get("rotate"):
            opts.append("rotate=%d" % comp["rotate"])
        if comp.get("scale") is not None:
            # v1.1: node 均匀缩放。锚点随变换精确 ×scale（GATE ① 探针），与
            # irlib.pin_positions 的 offset×scale 保持同一几何。
            opts.append("scale=%s" % fmt(comp["scale"]))
        lines = ["\\node[%s] (%s) at %s {};"
                 % (", ".join(opts), comp["id"], fmt_pt(tuple(comp["at"])))]
        if "component_id" not in self.component_annotation_kinds.get(comp["id"], set()) and comp.get("label"):
            lines.append(self._label_node_multi(comp))
        return lines

    def _label_node_multi(self, comp):
        side = comp.get("label_side") or "right"
        gap = float(comp.get("label_gap", 0.2))  # v1.1：缺省 = 既有常量
        if comp.get("label_at") is not None:
            return "\\node[anchor=center] at %s {$%s$};" % (
                fmt_pt(tuple(comp["label_at"])), comp["label"])
        (x0, y0), (x1, y1) = self.model.comp_bbox(comp)
        ax, ay = tuple(comp["at"])
        pos = {"right": (x1 + gap, ay), "left": (x0 - gap, ay),
               "above": (ax, y1 + gap), "below": (ax, y0 - gap)}[side]
        return "\\node[anchor=%s] at %s {$%s$};" % (
            ANCHOR_OPP[side], fmt_pt(pos), comp["label"])

    def emit_single(self, comp):
        at = tuple(comp["at"])
        opts = [comp["type"]]
        if comp.get("scale") is not None:
            opts.append("scale=%s" % fmt(comp["scale"]))
        lines = ["\\node[%s] at %s {};" % (", ".join(opts), fmt_pt(at))]
        owned = self.component_annotation_kinds.get(comp["id"], set())
        if "component_id" not in owned and comp.get("label_at") is not None and comp.get("label"):
            lines.append("\\node[anchor=center] at %s {$%s$};" % (
                fmt_pt(tuple(comp["label_at"])), comp["label"]))
        elif "component_id" not in owned and comp.get("label"):
            side = comp.get("label_side") or ("above" if comp["type"] == "vcc" else "below")
            g = float(comp.get("label_gap", 0.5))  # v1.1：缺省 = 既有常量
            dx, dy = {"above": (0, g), "below": (0, -g),
                      "left": (-g, 0), "right": (g, 0)}[side]
            lines.append("\\node[anchor=%s] at %s {$%s$};" % (
                ANCHOR_OPP[side], fmt_pt((at[0] + dx, at[1] + dy)), comp["label"]))
        return lines

    # -------------------------------------------------- wires

    def _jump_hits(self, a, b):
        """线段内部命中的 jump crossing，按行进方向排序：[(节点名, into锚, outof锚)]。"""
        hits = []
        for _k, (name, coord) in self.jumps.items():
            if irlib.point_on_segment_interior(coord, a, b, tol=irlib.EPS):
                hits.append((name, coord))
        if not hits:
            return []
        horiz = irlib.seg_is_horizontal(a, b)
        axis = 0 if horiz else 1
        rev = (b[axis] < a[axis])
        hits.sort(key=lambda h: h[1][axis], reverse=rev)
        into, outof = ("west", "east") if horiz else ("south", "north")
        if rev:
            into, outof = outof, into
        return [(name, into, outof) for name, _c in hits]

    def _wire_chains(self, wire):
        """wire → 若干条 ref 链（jump crossing 会把链切开）。"""
        pts = self.model.wire_points(wire)
        if len(pts) < 2 or pts[0][0] is None:
            return []
        chains = [[self.ref(*pts[0])]]
        for k in range(1, len(pts)):
            a, _ak, _ar = pts[k - 1]
            b, bkind, braw = pts[k]
            if a is None or b is None:
                continue
            for name, into, outof in self._jump_hits(a, b):
                chains[-1].append("(%s.%s)" % (name, into))
                chains.append(["(%s.%s)" % (name, outof)])
            chains[-1].append(self.ref(b, bkind, braw))
        return [c for c in chains if len(c) >= 2]

    def emit_wires(self):
        by_net = {}
        order = []
        for wire in self.ir.get("wires", []):
            pts = self.model.wire_points(wire)
            net = "?"
            for coord, _kind, _raw in pts:
                if coord is None:
                    continue
                nets = self.geom.net_of_root(self.geom.root_of(coord))
                if nets:
                    net = sorted(nets)[0]
                    break
            if net not in by_net:
                by_net[net] = []
                order.append(net)
            by_net[net].append(wire)
        net_rank = {n: i for i, n in enumerate(self._net_order())}
        order.sort(key=lambda n: net_rank.get(n, 999))
        lines = []
        for net in order:
            lines.append("%% net %s" % net)
            for wire in by_net[net]:
                for chain in self._wire_chains(wire):
                    lines.append("\\draw %s;   %% %s"
                                 % (" -- ".join(chain), wire["id"]))
        return lines

    # -------------------------------------------------- 其余要素

    def emit_jump_nodes(self):
        """jump crossing 节点必须先于 wires 声明（TikZ 不允许前向引用 node）。"""
        return ["\\node[jump crossing] (%s) at %s {};" % (name, fmt_pt(coord))
                for _k, (name, coord) in sorted(self.jumps.items(),
                                                key=lambda x: x[1][0])]

    def emit_marks(self):
        lines = []
        for j in self.ir.get("junctions", []):
            k = quant(tuple(j["at"]))
            ref = "(%s)" % self.coords[k][0] if k in self.coords else fmt_pt(tuple(j["at"]))
            lines.append("\\node[circ] at %s {};" % ref)
        for t in self.ir.get("terminals", []):
            at = tuple(t["at"])
            lines.append("\\node[%s] at %s {};" % (t.get("style", "ocirc"), fmt_pt(at)))
            if t.get("label"):
                side = t.get("label_side") or "right"
                dx, dy = {"above": (0, 0.3), "below": (0, -0.3),
                          "left": (-0.3, 0), "right": (0.3, 0)}[side]
                lines.append("\\node[anchor=%s] at %s {$%s$};" % (
                    ANCHOR_OPP[side], fmt_pt((at[0] + dx, at[1] + dy)), t["label"]))
        for tx in self.ir.get("texts", []):
            anchor = tx.get("anchor", "center")
            lines.append("\\node[anchor=%s] at %s {$%s$};" % (
                anchor, fmt_pt(tuple(tx["at"])), tx["content"]))
        return lines

    def emit_arrows(self):
        """电流方向箭头：短 -{Latex} 覆盖在导线上，+ 可选 $label$ 节点。"""
        lines = []
        for a in self.ir.get("arrows", []):
            at = tuple(a["at"])
            ux, uy = ARROW_UNIT[int(a.get("dir", 0))]
            p0 = (at[0] - ux * ARROW_LEN / 2.0, at[1] - uy * ARROW_LEN / 2.0)
            p1 = (at[0] + ux * ARROW_LEN / 2.0, at[1] + uy * ARROW_LEN / 2.0)
            lines.append("\\draw[-{Latex}] %s -- %s;" % (fmt_pt(p0), fmt_pt(p1)))
            if a.get("label"):
                side = a.get("label_side") or "above"
                dx, dy = {"above": (0, 0.3), "below": (0, -0.3),
                          "left": (-0.3, 0), "right": (0.3, 0)}[side]
                lines.append("\\node[anchor=%s] at %s {$%s$};" % (
                    ANCHOR_OPP[side], fmt_pt((at[0] + dx, at[1] + dy)), a["label"]))
        return lines

    def emit_annotations(self):
        """一等物理标注：语义归属来自 target，绘制位置严格来自 marker_at/label_at。"""
        lines = []
        for annotation in self.ir.get("annotations", []):
            kind = annotation["kind"]
            if kind == "current_direction":
                at = tuple(annotation["marker_at"])
                ux, uy = ARROW_UNIT[ANNOTATION_DIRECTION[annotation["direction"]]]
                p0 = (at[0] - ux * ARROW_LEN / 2.0, at[1] - uy * ARROW_LEN / 2.0)
                p1 = (at[0] + ux * ARROW_LEN / 2.0, at[1] + uy * ARROW_LEN / 2.0)
                lines.append("\\draw[-{Latex}] %s -- %s;" % (fmt_pt(p0), fmt_pt(p1)))
                if annotation.get("label") and annotation.get("label_at"):
                    lines.append("\\node at %s {$%s$};" %
                                 (fmt_pt(tuple(annotation["label_at"])), annotation["label"]))
            elif kind == "voltage_measurement":
                lines.append("\\node at %s {$+$};" %
                             fmt_pt(tuple(annotation["positive_ref"]["marker_at"])))
                lines.append("\\node at %s {$-$};" %
                             fmt_pt(tuple(annotation["negative_ref"]["marker_at"])))
                lines.append("\\node at %s {$%s$};" %
                             (fmt_pt(tuple(annotation["label_at"])), annotation["label"]))
            elif kind == "node_polarity":
                symbol = "+" if annotation["polarity"] == "positive" else "-"
                lines.append("\\node at %s {$%s$};" %
                             (fmt_pt(tuple(annotation["marker_at"])), symbol))
                if annotation.get("label"):
                    lines.append("\\node[anchor=west] at %s {$%s$};" %
                                 (fmt_pt(tuple(annotation["marker_at"])), annotation["label"]))
            else:
                label = annotation.get("label")
                target = annotation.get("target", {})
                if label is None and "component" in target:
                    comp = self.model.components[target["component"]]
                    label = comp.get("label" if kind == "component_id" else "value", "")
                lines.append("\\node at %s {$%s$};" %
                             (fmt_pt(tuple(annotation["label_at"])), label or ""))
        return lines

    def emit_unknowns(self):
        lines = []
        for u in self.ir.get("unknowns", []):
            cx, cy = u["at"]
            w, h = u["size"]
            lines.append("\\draw[dashed] %s rectangle %s;" % (
                fmt_pt((cx - w / 2.0, cy - h / 2.0)), fmt_pt((cx + w / 2.0, cy + h / 2.0))))
            lines.append("\\node[font=\\small] at %s {%s?};" % (fmt_pt((cx, cy)), u["id"]))
        return lines

    # -------------------------------------------------- region 组织

    def emit_regions(self):
        lines = []
        emitted = set()
        regions = list(self.ir.get("regions", []))
        rest = [c for c in self.ir.get("components", [])
                if c["id"] not in {cid for r in regions for cid in r["component_ids"]}]
        if rest:
            regions.append({"name": "(unassigned)",
                            "component_ids": [c["id"] for c in rest]})
        for region in regions:
            lines.append("")
            lines.append("%%%% ==== [region] %s ====" % comment_text(region["name"]))
            comps = [self.model.components[cid] for cid in region["component_ids"]
                     if cid in self.model.components and cid not in emitted]
            emitted.update(c["id"] for c in comps)
            for k, (net, coord) in sorted(self.coords.items(),
                                          key=lambda x: x[1][0]):
                if self._coord_region(coord, comps):
                    lines.append("\\coordinate (%s) at %s;" % (net, fmt_pt(coord)))
            for c in comps:
                if self.model.kind_of(c) == "multi":
                    lines.extend(self.emit_multi(c))
            for c in comps:
                if self.model.kind_of(c) == "two":
                    lines.extend(self.emit_two(c))
            for c in comps:
                if self.model.kind_of(c) == "single":
                    lines.extend(self.emit_single(c))
        return lines

    def _coord_region(self, coord, comps):
        """coordinate 声明落在"含有该点引脚"的首个 region。"""
        if getattr(self, "_declared_coords", None) is None:
            self._declared_coords = set()
        k = quant(coord)
        if k in self._declared_coords:
            return False
        for c in comps:
            pos = self.model.pin_positions(c) or {}
            if any(quant(p) == k for p in pos.values()):
                self._declared_coords.add(k)
                return True
        return False

    # -------------------------------------------------- 汇总

    def header_comment(self):
        meta = self.ir.get("meta", {})
        lines = ["%% source: %s  (%s)" % (comment_text(meta.get("source_image", "?")),
                                          comment_text(meta.get("title", ""))),
                 "% nets:"]
        members = self.geom.net_members()
        for net in self._net_order():
            if net in members:
                pins = ", ".join("%s.%s" % (cid, pn) for cid, pn, _c in members[net])
                lines.append("%%   %s: %s" % (net, pins))
        return lines

    def body(self):
        lines = []
        lines.extend(self.header_comment())
        lines.extend(self.emit_regions())
        if self.ir.get("nodes"):
            lines.append("")
            lines.append("%% ==== explicit nodes ====")
            for node in self.ir["nodes"]:
                lines.append("\\coordinate (%s) at %s;" %
                             (node["name"], fmt_pt(tuple(node["at"]))))
        # 兜底：没落进任何 region 的 named coordinate（纯导线顶点）在 wires 前声明
        declared = getattr(self, "_declared_coords", set())
        leftovers = [(net, coord) for k, (net, coord) in sorted(
            self.coords.items(), key=lambda x: x[1][0]) if k not in declared]
        if leftovers:
            lines.append("")
            for net, coord in leftovers:
                lines.append("\\coordinate (%s) at %s;" % (net, fmt_pt(coord)))
        jumps = self.emit_jump_nodes()
        if jumps:
            lines.append("")
            lines.append("%% ==== crossings (jump) ====")
            lines.extend(jumps)
        lines.append("")
        lines.append("%% ==== wires ====")
        lines.extend(self.emit_wires())
        marks = self.emit_marks()
        if marks:
            lines.append("")
            lines.append("%% ==== junctions / terminals / texts ====")
            lines.extend(marks)
        arrows = self.emit_arrows()
        if arrows:
            lines.append("")
            lines.append("%% ==== arrows ====")
            lines.extend(arrows)
        annotations = self.emit_annotations()
        if annotations:
            lines.append("")
            lines.append("%% ==== annotations ====")
            lines.extend(annotations)
        unk = self.emit_unknowns()
        if unk:
            lines.append("")
            lines.append("%% ==== unknowns ====")
            lines.extend(unk)
        return lines

    def debug_layer(self):
        canvas = self.ir.get("meta", {}).get("canvas", {})
        w, h = canvas.get("w", 10), canvas.get("h", 10)
        lines = ["% debug 层：网格 + 刻度 + 元件锚点 + id",
                 "\\draw[help lines, line width=0.1pt, gray!40, step=0.5] (0,0) grid %s;"
                 % fmt_pt((w, h)),
                 "\\draw[help lines, gray!70, step=1] (0,0) grid %s;" % fmt_pt((w, h)),
                 "\\foreach \\x in {0,...,%d} {\\node[gray, font=\\tiny, anchor=north]"
                 " at (\\x,-0.15) {\\x};}" % int(w),
                 "\\foreach \\y in {0,...,%d} {\\node[gray, font=\\tiny, anchor=east]"
                 " at (-0.15,\\y) {\\y};}" % int(h)]
        for comp in self.ir.get("components", []):
            kind = self.model.kind_of(comp)
            if kind == "two":
                cx = (comp["from"][0] + comp["to"][0]) / 2.0
                cy = (comp["from"][1] + comp["to"][1]) / 2.0
            else:
                cx, cy = comp["at"]
            lines.append("%% component anchor %s" % comp["id"])
            lines.append("\\draw[red, line width=0.4pt] %s -- %s %s -- %s;" % (
                fmt_pt((cx - 0.08, cy)), fmt_pt((cx + 0.08, cy)),
                fmt_pt((cx, cy - 0.08)), fmt_pt((cx, cy + 0.08))))
            lines.append("\\node[red, font=\\tiny, anchor=south west] at %s {%s};"
                         % (fmt_pt((cx + 0.1, cy + 0.1)), comp["id"]))
        return lines

    def document(self, debug=False, fragment=False):
        flavor = self.ir.get("style", {}).get("flavor", "american")
        ctikzset = self.config.get("style", {}).get("ctikzset", "")
        body = []
        body.append("\\begin{circuitikz}")
        if debug:
            body.extend(self.debug_layer())
        body.extend(self.body())
        body.append("\\end{circuitikz}")
        if fragment:
            return "\n".join(body) + "\n"
        head = ["\\documentclass[margin=5pt]{standalone}"]
        if irlib.tex_content_has_cjk("\n".join(body)):
            head.append("\\usepackage{ctex}")  # 排版内容含中文 -> lualatex+ctex（render --engine auto 配合）
        head.append("\\usepackage[%s]{circuitikz}" % flavor)
        if ctikzset:
            head.append("\\ctikzset{%s}" % ctikzset)
        return "\n".join(head + ["\\begin{document}"] + body +
                         ["\\end{document}"]) + "\n"


def serialize_validated(validated, output, fragment=False, config=None):
    if validated.report.has_error() or validated.model is None:
        raise ValueError("validate 未通过，拒绝序列化（垃圾不进）")
    config = config if config is not None else irlib.load_config()
    output = str(output)
    ser = Serializer(validated.document, validated.model.anchors, config)
    with open(output, "w", encoding="utf-8") as f:
        f.write(ser.document(fragment=fragment))
    dbg = output[:-4] + ".debug.tex" if output.endswith(".tex") else output + ".debug.tex"
    ser2 = Serializer(validated.document, validated.model.anchors, config)
    with open(dbg, "w", encoding="utf-8") as f:
        f.write(ser2.document(debug=True, fragment=fragment))


def main(argv=None):
    irlib.ensure_utf8_io()
    ap = argparse.ArgumentParser(description="IR -> circuitikz 序列化")
    ap.add_argument("ir_file")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--fragment", action="store_true")
    args = ap.parse_args(argv)

    try:
        ir = irlib.load_json(args.ir_file)
        schema = irlib.load_schema()
        anchors = irlib.load_anchors()
        config = irlib.load_config()
    except (OSError, ValueError) as e:
        sys.stderr.write("ERROR: 无法读取输入: %s\n" % e)
        return irlib.EXIT_ENV

    validated = validate_ir.validate_document(ir, "full", schema=schema, anchors=anchors)
    report = validated.report
    if report.has_error():
        sys.stdout.write(report.to_text() + "\n")
        sys.stderr.write("ERROR: validate 未通过，拒绝序列化（垃圾不进）\n")
        return irlib.EXIT_ERROR
    if report.has_warning():
        sys.stderr.write(report.to_text() + "\n")

    try:
        serialize_validated(validated, args.output, fragment=args.fragment, config=config)
    except (OSError, ValueError) as e:
        sys.stderr.write("ERROR: 写输出失败: %s\n" % e)
        return irlib.EXIT_ENV
    sys.stdout.write("OK -> %s\n" % args.output)
    return irlib.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
