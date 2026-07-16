#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""validate_ir.py — kirchhoff-ir/1.0 校验器。

用法: validate_ir.py ir.json [--phase skeleton|geometry|full] [--json]
退出码: 0 干净 / 1 仅 W 级 / 2 有 E 级 / 3 环境或 IO 错误
规则清单见 PLAN.md §7.1 与 references/ir-schema.md；hint 写给任意模型的修复指引。

phase 与感知遍次对应（§8.2）：
  skeleton  遍1 骨架     E001 E002 E003 E005 E006 + W104 W105 W107 W109
  geometry  遍2 分区细扫  += E004 E013 E014 + W103
  full      遍3/4 终检    += E007 E008 + W101 W102 W106
"""
import argparse
import sys

import jsonschema

import irlib
from irlib import (EPS, GeomIndex, IRModel, Report, is_strictly_orthogonal,
                   pt_close, point_on_segment_interior, seg_is_orthogonal, snapped)

PHASES = ("skeleton", "geometry", "full")


def jptr(*parts):
    return "/" + "/".join(str(p) for p in parts)


# ---------------------------------------------------------------- E001

def check_schema(report, ir, schema):
    """E001：结构不合法 / type 不在词表。返回是否可继续深查。"""
    known = irlib.TWO_TERMINAL_TYPES | irlib.MULTI_TYPES | irlib.SINGLE_TYPES
    bad_type_idx = set()
    for i, comp in enumerate(ir.get("components", []) if isinstance(ir, dict) else []):
        if isinstance(comp, dict) and comp.get("type") not in known:
            bad_type_idx.add(i)
            report.add("E001", "E", jptr("components", i, "type"),
                       "type %r 不在 v1 词表" % comp.get("type"),
                       "词表见 references/ir-schema.md §3.4；词表外符号禁止顶替，"
                       "改走 unknowns 条目（UNKNOWN 协议，ir-schema.md §8）")
    validator = jsonschema.Draft7Validator(schema)
    for err in sorted(validator.iter_errors(ir), key=lambda e: list(e.absolute_path)):
        path = list(err.absolute_path)
        if len(path) >= 2 and path[0] == "components" and path[1] in bad_type_idx:
            continue  # 该元件已按"词表外"报过，压掉 oneOf 噪音
        msg = err.message
        if err.validator == "oneOf" and err.context:
            best = jsonschema.exceptions.best_match(err.context)
            if best is not None:
                path = list(best.absolute_path) or path
                msg = best.message
        report.add("E001", "E", jptr(*path) if path else "/",
                   msg[:300],
                   "对照 schemas/ir.schema.json 修正该字段结构；"
                   "字段语义见 references/ir-schema.md")
    return not report.has_error()


# ---------------------------------------------------------------- E002

def pin_name_set(model, comp):
    kind = model.kind_of(comp)
    if kind == "two":
        return {"1", "2"}
    if kind == "single":
        return {"p"}
    if kind == "multi":
        entry = model.anchor_entry(comp)
        return set(entry.get("pins", {}).keys()) if entry else set()
    return set()


def check_ids_refs(report, model, ir):
    seen = {}
    for section in ("components", "wires", "unknowns"):
        for i, item in enumerate(ir.get(section, [])):
            iid = item.get("id")
            if iid in seen:
                report.add("E002", "E", jptr(section, i, "id"),
                           "id %r 与 %s 重复" % (iid, seen[iid]),
                           "全图 id 必须唯一（components/wires/unknowns 共用命名空间），"
                           "给其中一个换新序号")
            else:
                seen[iid] = jptr(section, i)
    for wi, wire in enumerate(ir.get("wires", [])):
        for pi, p in enumerate(wire.get("points", [])):
            if "node" in p:
                if p["node"] not in model.explicit_nodes:
                    report.add("E002", "E", jptr("wires", wi, "points", pi, "node"),
                               "引用了不存在的显式 node %r" % p["node"],
                               "先在顶层 nodes 中声明 {name,at}，或修正 node 名")
                continue
            if "pin" not in p:
                continue
            ref = p["pin"]
            cid = ref.split(".", 1)[0]
            comp = model.components.get(cid)
            if comp is None:
                report.add("E002", "E", jptr("wires", wi, "points", pi, "pin"),
                           "引用了不存在的元件 %r" % ref,
                           "检查元件 id 拼写，或先在 components 里补上该元件")
                continue
            pname = ref.split(".", 1)[1]
            if pname not in pin_name_set(model, comp):
                report.add("E002", "E", jptr("wires", wi, "points", pi, "pin"),
                           "元件 %s(%s) 没有引脚 %r" % (cid, comp.get("type"), pname),
                           "该类型合法引脚名见 references/ir-schema.md §3.4"
                           "（两端件恒为 1/2，1=from 端 2=to 端）")
    valid_region_ids = set(model.components) | set(model.unknowns)
    for ri, region in enumerate(ir.get("regions", [])):
        for ci, cid in enumerate(region.get("component_ids", [])):
            if cid not in valid_region_ids:
                report.add("E002", "E", jptr("regions", ri, "component_ids", ci),
                           "region %r 引用了不存在的元件 %r" % (region.get("name"), cid),
                           "region 只能引用 components/unknowns 里已存在的 id")


# ---------------------------------------------------------------- E003

def _routing_policy(ir):
    routing = ir.get("routing") or {}
    return (routing.get("grid_snap", "warn"),
            float(routing.get("grid_step", ir.get("meta", {}).get("grid", {}).get("snap", 0.5))))


def _check_snap(report, coord, path, mode, step):
    if mode == "off":
        return
    for axis, v in zip(("x", "y"), coord):
        if not snapped(v, snap=step):
            severity = "E" if mode == "strict" else "W"
            report.add("E003", severity, path,
                       "坐标 %s=%s 未吸附 %s 网格" % (axis, v, step),
                       "grid_snap=%s：主干和元件建议吸附网格；离网 pin 的严格正交短桩可保留"
                       "（texts.at 与 pins[].at 观测值豁免此规则）" % mode)
            return


def check_snap(report, model, ir):
    mode, step = _routing_policy(ir)
    for i, node in enumerate(ir.get("nodes", [])):
        _check_snap(report, node["at"], jptr("nodes", i, "at"), mode, step)
    for i, comp in enumerate(ir.get("components", [])):
        kind = model.kind_of(comp)
        if kind == "two":
            for f in ("from", "to"):
                if comp.get(f):
                    _check_snap(report, comp[f], jptr("components", i, f), mode, step)
        elif comp.get("at"):
            _check_snap(report, comp["at"], jptr("components", i, "at"), mode, step)
    for wi, wire in enumerate(ir.get("wires", [])):
        for pi, p in enumerate(wire.get("points", [])):
            if "xy" in p:
                _check_snap(report, p["xy"], jptr("wires", wi, "points", pi, "xy"), mode, step)
    for section in ("junctions", "crossings", "terminals"):
        for i, item in enumerate(ir.get(section, [])):
            if item.get("at"):
                _check_snap(report, item["at"], jptr(section, i, "at"), mode, step)
    for i, u in enumerate(ir.get("unknowns", [])):
        for f in ("at", "size"):
            if u.get(f):
                _check_snap(report, u[f], jptr("unknowns", i, f), mode, step)


# ---------------------------------------------------------------- E004 / E005

def check_two_terminal_axis(report, model, ir):
    for i, comp in enumerate(ir.get("components", [])):
        if model.kind_of(comp) != "two":
            continue
        frm, to = comp.get("from"), comp.get("to")
        if not frm or not to or pt_close(frm, to):
            continue  # from==to 由 E005 报
        if "allow_diagonal" in (comp.get("flags") or []):
            continue
        if not seg_is_orthogonal(tuple(frm), tuple(to)):
            report.add("E004", "E", jptr("components", i),
                       "两端件 %s from→to 非水平/垂直" % comp.get("id"),
                       "调整 from/to 使其共 x 或共 y；确为斜放时加 "
                       "flags:[\"allow_diagonal\"] 豁免")


def check_wire_orthogonal(report, model, ir):
    for wi, wire in enumerate(ir.get("wires", [])):
        pts = model.wire_points(wire)
        for k in range(1, len(pts)):
            a, akind, _ = pts[k - 1]
            b, bkind, _ = pts[k]
            if a is None or b is None:
                continue  # E002 已报
            if pt_close(a, b):
                report.add("E004", "E", jptr("wires", wi, "points", k),
                           "wire %s 相邻点重合" % wire.get("id"),
                           "删掉重复顶点")
                continue
            if not is_strictly_orthogonal(a, b):
                report.add("E004", "E", jptr("wires", wi, "points", k),
                           "wire %s 第 %d 段非正交: %s → %s"
                           % (wire.get("id"), k, list(a), list(b)),
                           "在离网 pin 前添加一个 L 形 waypoint；原图转角必须逐点显式录入，"
                           "不得用近似正交斜线直连")


def check_span(report, model, ir):
    for i, comp in enumerate(ir.get("components", [])):
        if model.kind_of(comp) != "two":
            continue
        frm, to = comp.get("from"), comp.get("to")
        if not frm or not to:
            continue
        if pt_close(frm, to):
            report.add("E005", "E", jptr("components", i),
                       "两端件 %s from==to" % comp.get("id"),
                       "两端件必须有跨度（推荐 2.0，最小 1.0）")
            continue
        span = ((to[0] - frm[0]) ** 2 + (to[1] - frm[1]) ** 2) ** 0.5
        if span < 1.0 - EPS:
            report.add("E005", "E", jptr("components", i),
                       "两端件 %s 跨度 %.2f < 1.0" % (comp.get("id"), span),
                       "拉开 from/to 距离至 ≥1.0（推荐 2.0），周边坐标同步平移")
        # v1.1: 符号体原生长 2 × scale；超出引脚跨度只警告（编辑器会阻止，
        # 此检查针对手写文件）。恰好等长不告警。
        scale = comp.get("scale")
        if scale is not None and 2.0 * float(scale) > span + EPS:
            report.add("W109", "W", jptr("components", i),
                       "两端件 %s 体长 2×scale=%.2f 超出跨度 %.2f"
                       % (comp.get("id"), 2.0 * float(scale), span),
                       "缩小 scale 或拉开 from/to（体长 ≤ 跨度时引线才有落脚处）")


# ---------------------------------------------------------------- E006

def check_multi_pins(report, model, ir):
    for i, comp in enumerate(ir.get("components", [])):
        kind = model.kind_of(comp)
        if kind == "multi":
            ctype = comp.get("type")
            variant = comp.get("variant")
            if variant and variant not in irlib.VARIANTS.get(ctype, frozenset()):
                report.add("E006", "E", jptr("components", i, "variant"),
                           "%s 不支持 variant %r" % (ctype, variant),
                           "v1 variant 词表：opamp→noinv_up；transformer→core；"
                           "其余类型不允许 variant")
                continue
            want = pin_name_set(model, comp)
            got = {p.get("name") for p in comp.get("pins", [])}
            if got != want:
                report.add("E006", "E", jptr("components", i, "pins"),
                           "%s(%s) 引脚名 %s 与词表 %s 不符"
                           % (comp.get("id"), ctype, sorted(got), sorted(want)),
                           "多端件引脚必须恰好是该类型的 anchor 词表"
                           "（references/ir-schema.md §3.4），不多不少不改名")
        elif kind == "single":
            got = {p.get("name") for p in comp.get("pins", [])}
            if got != {"p"}:
                report.add("E006", "E", jptr("components", i, "pins"),
                           "单端件 %s 引脚必须恒为 p" % comp.get("id"),
                           "改成 pins:[{\"name\":\"p\",\"net\":...}]")


# ---------------------------------------------------------------- E007 / E008

def check_topology(report, model, ir, geom):
    declared = model.ir.get("nets")
    members = geom.net_members()
    for net, plist in sorted(members.items()):
        roots = {geom.root_of(coord) for _cid, _pn, coord in plist}
        if len(roots) > 1:
            groups = {}
            for cid, pn, coord in plist:
                groups.setdefault(geom.root_of(coord), []).append(
                    "%s.%s@%s" % (cid, pn, list(coord)))
            report.add("E007", "E", jptr("nets"),
                       "net %s 声明为一体但几何上分裂成 %d 块: %s [evidence=explicit+geometric]"
                       % (net, len(roots), " | ".join(", ".join(g) for g in groups.values())),
                       "explicit 来自 pin/net/node 引用，geometric 来自当前坐标连通；"
                       "补 wire 连通，或修正其中一块的 net 声明")
    root_nets = {}
    for net, plist in members.items():
        for _cid, _pn, coord in plist:
            root_nets.setdefault(geom.root_of(coord), set()).add(net)
    for root, nets in sorted(root_nets.items()):
        if len(nets) > 1:
            evidence = []
            for net in sorted(nets):
                pins = ["%s.%s" % (cid, pn) for cid, pn, coord in members[net]
                        if geom.root_of(coord) == root]
                evidence.append("%s{%s}" % (net, ",".join(pins)))
            report.add("E007", "E", jptr("nets"),
                       "几何上连通的一块里出现了多个 net 声明: %s [evidence=explicit+geometric]"
                       % " vs ".join(evidence),
                       "explicit 声明互相冲突，或 geometric 走线误合并；统一 net 名、"
                       "修正 wire/顶点，或在十字处声明 crossing")
    _ = declared  # nets 清单本身的对账在 W106


def check_crossings_declared(report, model, ir, geom):
    declared_pts = {}
    for i, j in enumerate(ir.get("junctions", [])):
        declared_pts[irlib.quant(tuple(j.get("at", (0, 0))))] = ("junction", i)
    for i, c in enumerate(ir.get("crossings", [])):
        declared_pts[irlib.quant(tuple(c.get("at", (0, 0))))] = ("crossing", i)
    seen = set()
    for coord, w1, w2 in geom.interior_crossings():
        k = irlib.quant(coord)
        if k in seen:
            continue
        seen.add(k)
        if k not in declared_pts:
            report.add("E008", "E", jptr("crossings"),
                       "wire %s 与 %s 在 %s 十字交叉，既无 junction 也无 crossing"
                       % (w1, w2, [round(coord[0], 3), round(coord[1], 3)]),
                       "看原图该处：相连(有实心点)→两条 wire 都在交点加顶点并录 "
                       "junction；不相连→录 crossings:{at,style:plain|jump}")
    for k, node in geom.nodes.items():
        if node.branches() >= 4 and node.junction is None and node.crossing is None:
            report.add("E008", "E", jptr("junctions"),
                       "四路汇合点 %s 未显式声明 junction"
                       % [round(node.coord[0], 3), round(node.coord[1], 3)],
                       "四路及以上交汇必须声明：相连录 junction（并画实心点），"
                       "不相连改成 crossing 或错开走线")


# ---------------------------------------------------------------- E013 / E014

def check_markers_on_wires(report, model, ir, geom):
    for i, j in enumerate(ir.get("junctions", [])):
        at = tuple(j.get("at", (0, 0)))
        node = geom.nodes.get(irlib.quant(at))
        if node is None or (not node.wire_pts and not node.pins):
            report.add("E013", "E", jptr("junctions", i),
                       "junction %s 下没有任何 wire 顶点或引脚" % list(at),
                       "junction 必须落在电气点上；十字相连时两条 wire 都要在交点"
                       "加显式顶点，再放 junction")
    for i, c in enumerate(ir.get("crossings", [])):
        at = tuple(c.get("at", (0, 0)))
        crossing_here = [x for x in geom.interior_crossings()
                         if irlib.quant(x[0]) == irlib.quant(at)]
        if not crossing_here:
            report.add("E013", "E", jptr("crossings", i),
                       "crossing %s 处没有两条 wire 的内部交叉" % list(at),
                       "crossing 只用于两条 wire 中段十字穿越处；端点相接处"
                       "不需要 crossing")


def _point_on_segment(pt, a, b, tol=EPS):
    """pt 落在正交线段 (a,b) 上（含端点）。仅支持水平/竖直段。"""
    if irlib.seg_is_horizontal(a, b, tol):
        lo, hi = min(a[0], b[0]), max(a[0], b[0])
        return abs(pt[1] - a[1]) <= tol and lo - tol <= pt[0] <= hi + tol
    if irlib.seg_is_vertical(a, b, tol):
        lo, hi = min(a[1], b[1]), max(a[1], b[1])
        return abs(pt[0] - a[0]) <= tol and lo - tol <= pt[1] <= hi + tol
    return False


def check_arrows(report, model, ir, geom):
    """E013：电流箭头 at 必须落在某 wire 段上，dir 必须与该段平行。

    arrows 是标注类（v1.1 增补）：at 豁免 E003（不在 check_snap 名单内），
    但方向标注必须真的贴在一条导线上，且方向与导线共线，否则语义无意义。
    """
    arrows = ir.get("arrows")
    if not arrows:
        return
    for i, ar in enumerate(arrows):
        at = tuple(ar.get("at", (0, 0)))
        direction = int(ar.get("dir", 0))
        host = None
        for _wid, _idx, a, b, _ak, _bk in geom.segments:
            if a is None or b is None:
                continue
            if _point_on_segment(at, a, b):
                host = (a, b)
                break
        if host is None:
            report.add("E013", "E", jptr("arrows", i, "at"),
                       "arrow %s 未落在任何 wire 段上" % list(at),
                       "电流箭头必须标注在某条 wire 上：把 at 移到导线段上，"
                       "或先补一条 wire 承载它")
            continue
        a, b = host
        horiz = irlib.seg_is_horizontal(a, b)
        parallel = (direction in (0, 180)) if horiz else (direction in (90, 270))
        if not parallel:
            report.add("E013", "E", jptr("arrows", i, "dir"),
                       "arrow %s 的 dir=%d 与所在 wire 段不平行" % (list(at), direction),
                       "电流方向必须与所标注的导线段平行：水平段用 dir 0/180，"
                       "竖直段用 dir 90/270")


def check_ambiguous_touch(report, model, ir, geom):
    point_objs = []
    for k, node in geom.nodes.items():
        if not node.pins and not node.wire_pts:
            continue  # 纯标记节点（如 crossing 声明点本身）不是电气点对象
        label = []
        for cid, pn, _net in node.pins:
            label.append("%s.%s" % (cid, pn))
        for wid, idx, _ep in node.wire_pts:
            label.append("%s[%d]" % (wid, idx))
        point_objs.append((node.coord, "+".join(label)))
    for wid, seg_idx, a, b, _ak, _bk in geom.segments:
        for coord, label in point_objs:
            if point_on_segment_interior(coord, a, b, tol=EPS):
                report.add("E014", "E", jptr("wires"),
                           "wire %s 第 %d 段中段恰好穿过 %s (%s)"
                           % (wid, seg_idx, label,
                              [round(coord[0], 3), round(coord[1], 3)]),
                           "模糊连接：若确实相连，给 %s 在该点加显式顶点；"
                           "若不相连，把走线错开 ≥0.5" % wid)


# ---------------------------------------------------------------- W 级

def check_dangling(report, model, ir, geom):
    for net, plist in sorted(geom.net_members().items()):
        if len(plist) != 1:
            continue
        cid, pn, coord = plist[0]
        root = geom.root_of(coord)
        has_terminal = any(node.terminals and geom.uf.find(k) == root
                           for k, node in geom.nodes.items())
        if not has_terminal:
            report.add("W101", "W", jptr("nets"),
                       "net %s 只有一个成员 %s.%s 且所在分量无 terminal"
                       % (net, cid, pn),
                       "悬空引脚：看原图它是否接了别处（漏录 wire），"
                       "或该处是端口（补 terminals 条目）")


def check_junction_confluence(report, model, ir, geom):
    for i, j in enumerate(ir.get("junctions", [])):
        node = geom.nodes.get(irlib.quant(tuple(j.get("at", (0, 0)))))
        if node is not None and 0 < node.branches() < 3:
            report.add("W102", "W", jptr("junctions", i),
                       "junction %s 处只汇合了 %d 路" % (list(node.coord), node.branches()),
                       "实心点通常在 ≥3 路汇合处；2 路直连不需要 junction，"
                       "检查是否漏录了第三路 wire")


def check_pose_observation(report, model, ir):
    for i, comp in enumerate(ir.get("components", [])):
        if model.kind_of(comp) != "multi":
            continue
        pos = model.pin_positions(comp)
        if not pos:
            continue
        for pi, p in enumerate(comp.get("pins", [])):
            obs = p.get("at")
            name = p.get("name")
            if not obs or name not in pos:
                continue
            cx, cy = pos[name]
            d = ((obs[0] - cx) ** 2 + (obs[1] - cy) ** 2) ** 0.5
            if d > 0.5:
                report.add("W103", "W", jptr("components", i, "pins", pi, "at"),
                           "%s.%s 观测位置 %s 与位姿推算 %s 偏差 %.2f"
                           % (comp.get("id"), name, list(obs),
                              [round(cx, 2), round(cy, 2)], d),
                           "位姿疑似看错：重看原图该引脚朝向，修正 rotate/mirror/at"
                           "（位姿公式见 ir-schema.md §3.2），或修正观测值")


def check_overlap(report, model, ir):
    boxes = []
    for i, comp in enumerate(ir.get("components", [])):
        b = model.comp_bbox(comp)
        if b:
            pinkeys = {irlib.quant(c) for c in (model.pin_positions(comp) or {}).values()}
            boxes.append((i, comp.get("id"), b, pinkeys))
    for x in range(len(boxes)):
        for y in range(x + 1, len(boxes)):
            i1, id1, b1, k1 = boxes[x]
            i2, id2, b2, k2 = boxes[y]
            if k1 & k2:
                continue  # 共享引脚坐标 = 端点相接的正常连接，非重叠
            if irlib.bbox_overlap(b1, b2):
                report.add("W104", "W", jptr("components", i2),
                           "元件 %s 与 %s 几何重叠（粗检）" % (id2, id1),
                           "对照原图确认相对位置，通常是坐标看错一格；"
                           "确属紧凑排布可忽略")


def check_canvas(report, model, ir):
    canvas = ir.get("meta", {}).get("canvas", {})
    w, h = canvas.get("w", 0), canvas.get("h", 0)
    if w > 30 or h > 20:
        report.add("W105", "W", jptr("meta", "canvas"),
                   "画布 %sx%s 超过建议上限 30x20" % (w, h),
                   "过大通常是比例尺定错：最常见水平两端件跨度应为 2.0")
    for i, comp in enumerate(ir.get("components", [])):
        pos = model.pin_positions(comp) or {}
        for name, (x, y) in pos.items():
            if x < -EPS or y < -EPS or x > w + EPS or y > h + EPS:
                report.add("W105", "W", jptr("components", i),
                           "%s.%s 位于 %s，出画布 [0,%s]x[0,%s]"
                           % (comp.get("id"), name, [round(x, 2), round(y, 2)], w, h),
                           "坐标应非负且落在画布内；整体平移或扩大 canvas")
                break


def check_nets_ledger(report, model, ir, geom):
    if "nets" not in ir:
        return
    declared = {n.get("name") for n in ir.get("nets", [])}
    used = set(geom.net_members().keys())
    for net in sorted(declared - used):
        report.add("W106", "W", jptr("nets"),
                   "net %s 已声明但没有任何 pin 使用" % net,
                   "拓扑意图与录入不对账：检查是否漏录元件/引脚，或删掉多余声明")
    for net in sorted(used - declared):
        report.add("W106", "W", jptr("nets"),
                   "net %s 被 pin 使用但未在 nets 清单声明" % net,
                   "把它补进 nets（先声明拓扑意图是 E007 双通道校验的前提）")


def check_region_coverage(report, model, ir):
    covered = set()
    for region in ir.get("regions", []):
        covered.update(region.get("component_ids", []))
    missing = sorted(set(model.components) - covered)
    if missing:
        report.add("W107", "W", jptr("regions"),
                   "以下元件未被任何 region 覆盖: %s" % ", ".join(missing),
                   "把它们加进合适的 region（分区注释与分区审读都依赖 region 全覆盖）")


def check_unknowns_status(report, model, ir):
    """W108：unknowns 非空 → 交付状态必须 needs_human，不得当 ok 交付、不得就近顶替。"""
    n = len(ir.get("unknowns", []))
    if n:
        report.add("W108", "W", jptr("unknowns"),
                   "存在 %d 个 unknowns 占位，交付状态必须标 needs_human 并附遗留差异清单" % n,
                   "词表外符号已按 UNKNOWN 协议留虚线框；DELIVERY 状态禁止填 ok")


# ---------------------------------------------------------------- 主流程

def run_checks(report, model, ir, phase):
    check_ids_refs(report, model, ir)
    check_snap(report, model, ir)
    check_span(report, model, ir)
    check_multi_pins(report, model, ir)
    check_two_terminal_axis(report, model, ir)
    check_overlap(report, model, ir)
    check_canvas(report, model, ir)
    check_region_coverage(report, model, ir)
    check_unknowns_status(report, model, ir)
    if phase == "skeleton":
        return
    geom = GeomIndex(model)
    check_wire_orthogonal(report, model, ir)
    check_markers_on_wires(report, model, ir, geom)
    check_arrows(report, model, ir, geom)
    check_ambiguous_touch(report, model, ir, geom)
    check_pose_observation(report, model, ir)
    if phase == "geometry":
        return
    check_topology(report, model, ir, geom)
    check_crossings_declared(report, model, ir, geom)
    check_dangling(report, model, ir, geom)
    check_junction_confluence(report, model, ir, geom)
    check_nets_ledger(report, model, ir, geom)


def main(argv=None):
    irlib.ensure_utf8_io()
    ap = argparse.ArgumentParser(description="kirchhoff-ir/1.0 校验器")
    ap.add_argument("ir_file")
    ap.add_argument("--phase", choices=PHASES, default="full")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        ir = irlib.load_json(args.ir_file)
        schema = irlib.load_schema()
        anchors = irlib.load_anchors()
    except (OSError, ValueError) as e:
        sys.stderr.write("ERROR: 无法读取输入: %s\n" % e)
        return irlib.EXIT_ENV

    report = Report()
    if check_schema(report, ir, schema):
        model = IRModel(ir, anchors)
        run_checks(report, model, ir, args.phase)

    out = report.to_json({"phase": args.phase}) if args.json else report.to_text()
    sys.stdout.write(out + "\n")
    return report.exit_code()


if __name__ == "__main__":
    sys.exit(main())
