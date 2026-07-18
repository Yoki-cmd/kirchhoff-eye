#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""irlib.py — Kirchhoff-eye 确定性工具链共享库。

职责：IR 装载与 schema 校验、引脚解析（anchors.json + 位姿公式）、几何原语、
连通性（union-find）、报告机（{code,severity,path,message,hint} + 退出码约定）。
位姿公式（Phase 0 probe07 机读锁定）：pin = at + M^mirror · R(rotate) · offset
（offset 先旋转、再水平镜像，与 [xscale=-1, rotate=θ] 的 TikZ 行为一致）。
"""
import json
import math
import os
from functools import lru_cache

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
SCHEMA_PATH = os.path.join(ROOT, "schemas", "ir.schema.json")
ANCHORS_PATH = os.path.join(ROOT, "templates", "anchors.json")
CONFIG_PATH = os.path.join(ROOT, "config.json")
CATALOG_PATH = os.path.join(ROOT, "catalog", "components.json")

EPS = 1e-4          # 坐标重合容差（旋转浮点误差防护，lt2ti 同款坑）
SNAP = 0.5

# 元件类型词表的单一真源 = catalog/components.json。以下集合全部由它派生
# （kind / invert / variants / tikz key），取代旧的手写 frozenset —— 新增元件只改目录。
@lru_cache(maxsize=None)
def load_catalog():
    with open(CATALOG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


COMPONENTS = load_catalog()["components"]

TWO_TERMINAL_TYPES = frozenset(t for t, v in COMPONENTS.items() if v["kind"] == "two")
MULTI_TYPES = frozenset(t for t, v in COMPONENTS.items() if v["kind"] == "multi")
SINGLE_TYPES = frozenset(t for t, v in COMPONENTS.items() if v["kind"] == "single")
VARIANTS = {t: frozenset(v["variants"]) for t, v in COMPONENTS.items() if v.get("variants")}
# 极性实现（Phase 0 probe03/03b/03c 实测）：invert=true 的类型序列化时加 invert
INVERT_TYPES = frozenset(t for t, v in COMPONENTS.items() if v.get("invert"))
# 两端件 IR type -> circuitikz to[] 名（ir2tikz 引用 irlib.TO_NAME）
TO_NAME = {t: v["tikz"] for t, v in COMPONENTS.items() if v["kind"] == "two"}

EXIT_OK, EXIT_WARN, EXIT_ERROR, EXIT_ENV = 0, 1, 2, 3


def tex_content_has_cjk(text):
    """剥掉 % 行注释后，正文是否含非 ASCII。

    注释里的中文（region 名、debug 层说明）不应触发 lualatex/ctex——
    pdflatex 跳过注释字节没有问题；只有排版内容里的 CJK 才需要换引擎。
    """
    for line in text.splitlines():
        cut = line.find("%")
        content = line if cut < 0 else line[:cut]
        if any(ord(ch) > 127 for ch in content):
            return True
    return False


def ensure_utf8_io():
    """契约：全链 UTF-8 输出（Windows 控制台默认 cp936 会烂中文）。"""
    import sys
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


# ---------------------------------------------------------------- 基础 IO

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=None)
def load_schema():
    return load_json(SCHEMA_PATH)


@lru_cache(maxsize=None)
def load_anchors():
    return load_json(ANCHORS_PATH)


@lru_cache(maxsize=None)
def load_config():
    return load_json(CONFIG_PATH)


# ---------------------------------------------------------------- 报告机

class Report(object):
    """收集 findings；exit code：有 E→2，仅 W→1，全空→0。"""

    def __init__(self):
        self.findings = []

    def add(self, code, severity, path, message, hint):
        self.findings.append({
            "code": code, "severity": severity, "path": path,
            "message": message, "hint": hint})

    def has_error(self):
        return any(f["severity"] == "E" for f in self.findings)

    def has_warning(self):
        return any(f["severity"] == "W" for f in self.findings)

    def exit_code(self):
        if self.has_error():
            return EXIT_ERROR
        if self.has_warning():
            return EXIT_WARN
        return EXIT_OK

    def to_json(self, extra=None):
        status = {EXIT_OK: "ok", EXIT_WARN: "warn", EXIT_ERROR: "error"}[self.exit_code()]
        doc = {"status": status, "findings": self.findings}
        if extra:
            doc.update(extra)
        return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True)

    def to_text(self):
        if not self.findings:
            return "OK: 0 findings"
        lines = []
        for f in self.findings:
            lines.append("[%s/%s] %s  %s" % (f["code"], f["severity"], f["path"], f["message"]))
            lines.append("    hint: %s" % f["hint"])
        lines.append("total: %d E, %d W" % (
            sum(1 for f in self.findings if f["severity"] == "E"),
            sum(1 for f in self.findings if f["severity"] == "W")))
        return "\n".join(lines)


# ---------------------------------------------------------------- 几何原语

def close(a, b, tol=EPS):
    return abs(a - b) <= tol


def pt_close(p, q, tol=EPS):
    return close(p[0], q[0], tol) and close(p[1], q[1], tol)


def snapped(v, snap=SNAP, tol=1e-9):
    r = v / snap
    return abs(r - round(r)) <= tol


def rotate_ccw(v, deg):
    """逆时针旋转，角度限 0/90/180/270，用整数矩阵避免浮点误差。"""
    x, y = v
    d = deg % 360
    if d == 0:
        return (x, y)
    if d == 90:
        return (-y, x)
    if d == 180:
        return (-x, -y)
    if d == 270:
        return (y, -x)
    raise ValueError("rotate 只允许 0/90/180/270: %r" % deg)


def transform_offset(offset, mirror, rotate):
    """位姿公式：先旋转、再水平镜像（probe07 + lt2ti 双重印证）。"""
    x, y = rotate_ccw(offset, rotate)
    if mirror:
        x = -x
    return (x, y)


def seg_is_horizontal(p, q, tol=EPS):
    # "是否真线段"恒用 EPS 判——tol 只放宽横轴偏差（PIN-TOL 下短段曾被误判为点重合）
    return close(p[1], q[1], tol) and not pt_close(p, q, EPS)


def seg_is_vertical(p, q, tol=EPS):
    return close(p[0], q[0], tol) and not pt_close(p, q, EPS)


def seg_is_orthogonal(p, q, tol=EPS):
    return seg_is_horizontal(p, q, tol) or seg_is_vertical(p, q, tol)


def is_strictly_orthogonal(p, q, eps=EPS):
    """相邻两点是否构成严格水平/竖直的非零线段。

    eps 仅吸收坐标计算的浮点误差；元件类别、pin 类型和网格策略都不得放宽此规则。
    """
    return seg_is_orthogonal(p, q, eps)


def point_on_segment_interior(pt, p, q, tol=EPS):
    """pt 是否落在正交线段 (p,q) 的内部（不含端点）。仅支持水平/垂直段。"""
    if pt_close(pt, p, tol) or pt_close(pt, q, tol):
        return False
    if seg_is_horizontal(p, q, tol):
        lo, hi = min(p[0], q[0]), max(p[0], q[0])
        return close(pt[1], p[1], tol) and (lo + tol) < pt[0] < (hi - tol)
    if seg_is_vertical(p, q, tol):
        lo, hi = min(p[1], q[1]), max(p[1], q[1])
        return close(pt[0], p[0], tol) and (lo + tol) < pt[1] < (hi - tol)
    return False


def segments_cross_interior(p1, q1, p2, q2, tol=EPS):
    """两条正交线段是否在各自内部相交（十字），返回交点或 None。"""
    if seg_is_horizontal(p1, q1, tol) and seg_is_vertical(p2, q2, tol):
        h, v = (p1, q1), (p2, q2)
    elif seg_is_vertical(p1, q1, tol) and seg_is_horizontal(p2, q2, tol):
        h, v = (p2, q2), (p1, q1)
    else:
        return None
    x, y = v[0][0], h[0][1]
    hlo, hhi = min(h[0][0], h[1][0]), max(h[0][0], h[1][0])
    vlo, vhi = min(v[0][1], v[1][1]), max(v[0][1], v[1][1])
    if (hlo + tol) < x < (hhi - tol) and (vlo + tol) < y < (vhi - tol):
        return (x, y)
    return None


class UnionFind(object):
    def __init__(self):
        self.parent = {}

    def find(self, x):
        p = self.parent.setdefault(x, x)
        if p != x:
            self.parent[x] = self.find(p)
        return self.parent[x]

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


# ---------------------------------------------------------------- IR 模型

class IRModel(object):
    """解析后的 IR 访问器：id 索引、pin 坐标解析、按类分派。

    构造前提：IR 已过 schema（E001）；本类对结构宽容（.get），语义检查在 validator。
    """

    def __init__(self, ir, anchors):
        self.ir = ir
        self.anchors = anchors
        self.components = {c.get("id"): c for c in ir.get("components", [])}
        self.wires = {w.get("id"): w for w in ir.get("wires", [])}
        self.unknowns = {u.get("id"): u for u in ir.get("unknowns", [])}
        self.explicit_nodes = {n.get("name"): n for n in ir.get("nodes", [])}

    @staticmethod
    def kind_of(comp):
        t = comp.get("type")
        if t in TWO_TERMINAL_TYPES:
            return "two"
        if t in MULTI_TYPES:
            return "multi"
        if t in SINGLE_TYPES:
            return "single"
        return None

    def anchor_entry(self, comp):
        """多端件的 anchors.json 条目（考虑 variant）。"""
        key = comp.get("type", "")
        variant = comp.get("variant")
        if variant:
            vkey = "%s|%s" % (key, variant)
            if vkey in self.anchors.get("types", {}):
                return self.anchors["types"][vkey]
        return self.anchors.get("types", {}).get(key)

    def pin_positions(self, comp):
        """返回 {pin_name: (x, y)}；未知类型/缺 anchor 条目返回 None。"""
        kind = self.kind_of(comp)
        if kind == "two":
            frm, to = comp.get("from"), comp.get("to")
            if not frm or not to:
                return None
            return {"1": tuple(frm), "2": tuple(to)}
        if kind == "single":
            at = comp.get("at")
            return {"p": tuple(at)} if at else None
        if kind == "multi":
            entry = self.anchor_entry(comp)
            at = comp.get("at")
            if not entry or not at:
                return None
            # v1.1: pin = at + M^mirror · R(rotate) · (offset × scale)。均匀缩放与
            # 旋转/镜像可交换；circuitikz 侧 node 选项 scale=k 实测同公式（GATE ① 探针）。
            scale = float(comp.get("scale", 1.0))
            out = {}
            for name, spec in entry.get("pins", {}).items():
                ox, oy = spec["offset"]
                dx, dy = transform_offset((ox * scale, oy * scale),
                                          bool(comp.get("mirror")),
                                          int(comp.get("rotate", 0)))
                out[name] = (at[0] + dx, at[1] + dy)
            return out
        return None

    def resolve_pin_ref(self, ref):
        """'Q1.B' -> (comp, pin_name, (x,y)) 或 (None, None, None)。"""
        if "." not in ref:
            return None, None, None
        cid, pname = ref.split(".", 1)
        comp = self.components.get(cid)
        if comp is None:
            return None, None, None
        pos = self.pin_positions(comp)
        if pos is None or pname not in pos:
            return comp, pname, None
        return comp, pname, pos[pname]

    def wire_points(self, wire):
        """解析 wire.points -> [(coord, kind, raw)]；kind ∈ xy|pin|node；解析失败 coord=None。

        pin 端点的 kind 附带元件类别（pin:two / pin:multi / pin:single）。
        """
        out = []
        for p in wire.get("points", []):
            if "xy" in p:
                out.append((tuple(p["xy"]), "xy", p))
            elif "pin" in p:
                comp, _pname, coord = self.resolve_pin_ref(p["pin"])
                kind = "pin"
                if comp is not None:
                    k = self.kind_of(comp)
                    kind = "pin:%s" % (k or "?")
                out.append((coord, kind, p))
            elif "node" in p:
                node = self.explicit_nodes.get(p["node"])
                out.append((tuple(node["at"]) if node else None, "node", p))
            else:
                out.append((None, "?", p))
        return out

    def comp_bbox(self, comp):
        """粗重叠检查用的元件包围盒 [(x0,y0),(x1,y1)]；不可解析返回 None。"""
        kind = self.kind_of(comp)
        scale = float(comp.get("scale", 1.0))  # v1.1: 符号体随 scale 放大/缩小
        if kind == "two":
            frm, to = comp.get("from"), comp.get("to")
            if not frm or not to:
                return None
            x0, x1 = min(frm[0], to[0]), max(frm[0], to[0])
            y0, y1 = min(frm[1], to[1]), max(frm[1], to[1])
            pad = 0.3 * scale  # 符号体半宽的保守估计
            return ((x0 - (pad if x0 == x1 else 0), y0 - (pad if y0 == y1 else 0)),
                    (x1 + (pad if x0 == x1 else 0), y1 + (pad if y0 == y1 else 0)))
        if kind == "single":
            at = comp.get("at")
            if not at:
                return None
            r = 0.3 * scale
            return ((at[0] - r, at[1] - r), (at[0] + r, at[1] + r))
        if kind == "multi":
            entry = self.anchor_entry(comp)
            at = comp.get("at")
            if not entry or not at or "bbox" not in entry:
                return None
            (x0, y0), (x1, y1) = entry["bbox"]
            corners = [(x0 * scale, y0 * scale), (x0 * scale, y1 * scale),
                       (x1 * scale, y0 * scale), (x1 * scale, y1 * scale)]
            tc = [transform_offset(c, bool(comp.get("mirror")), int(comp.get("rotate", 0)))
                  for c in corners]
            xs = [c[0] for c in tc]
            ys = [c[1] for c in tc]
            return ((at[0] + min(xs), at[1] + min(ys)), (at[0] + max(xs), at[1] + max(ys)))
        return None


def bbox_overlap(b1, b2, shrink=0.05):
    """两包围盒是否有正面积重叠（shrink 缩边防贴边误报）。"""
    (ax0, ay0), (ax1, ay1) = b1
    (bx0, by0), (bx1, by1) = b2
    return (ax0 + shrink < bx1 - shrink and bx0 + shrink < ax1 - shrink and
            ay0 + shrink < by1 - shrink and by0 + shrink < ay1 - shrink)


# ---------------------------------------------------------------- 几何索引

def quant(p):
    """坐标 → 量化键（1e-3 网格），吸收旋转/求和浮点误差。"""
    return (int(round(p[0] * 1000)), int(round(p[1] * 1000)))


class Node(object):
    """一个电气点：坐标 + 汇聚于此的 pin / wire 顶点 / terminal / 标记。"""

    def __init__(self, coord):
        self.coord = coord
        self.pins = []        # (comp_id, pin_name, net)
        self.wire_pts = []    # (wire_id, point_idx, is_endpoint)
        self.terminals = []   # terminal 下标
        self.junction = None  # junctions 下标
        self.crossing = None  # (下标, style)

    def branches(self):
        """汇合支路数：wire 在此的邻接线段数 + pin 数。"""
        n = len(self.pins)
        for _wid, _idx, is_endpoint in self.wire_pts:
            n += 1 if is_endpoint else 2
        return n


class GeomIndex(object):
    """全图几何索引 + 连通性（union-find），E007/E008/E013/E014 与 ir2tikz 共用。

    连通语义（ir-schema.md §4/§5）：顶点重合=连通（同量化键即同 Node）；
    wire 相邻点连通；内部×内部十字交叉不连通（除非声明 junction——而 junction
    又必须落在顶点上，故"连通的十字"必然要求两线都在交点设顶点）。
    """

    def __init__(self, model):
        self.model = model
        self.nodes = {}       # quant key -> Node
        self.segments = []    # (wire_id, seg_idx, a, b, a_kind, b_kind)
        self.uf = UnionFind()
        self.unresolved_wire_points = []  # (wire_id, idx) 解析失败的点
        self._build()

    def _node(self, coord):
        k = quant(coord)
        if k not in self.nodes:
            self.nodes[k] = Node(coord)
        return self.nodes[k]

    def _build(self):
        ir = self.model.ir
        power_rails = {}  # 单端件类型 -> 首个 at 键；同类单端件经隐式电源轨互连
        for comp in ir.get("components", []):
            pos = self.model.pin_positions(comp)
            if not pos:
                continue
            net_by_name = {p.get("name"): p.get("net") for p in comp.get("pins", [])}
            for pname, coord in pos.items():
                self._node(coord).pins.append(
                    (comp.get("id"), pname, net_by_name.get(pname)))
            if self.model.kind_of(comp) == "single":
                k = quant(pos["p"])
                t = comp.get("type")
                if t in power_rails:
                    self.uf.union(power_rails[t], k)
                else:
                    power_rails[t] = k
        for explicit in ir.get("nodes", []):
            self._node(tuple(explicit.get("at", (0, 0))))
        for wire in ir.get("wires", []):
            pts = self.model.wire_points(wire)
            prev_key = None
            for idx, (coord, _kind, _raw) in enumerate(pts):
                if coord is None:
                    self.unresolved_wire_points.append((wire.get("id"), idx))
                    prev_key = None
                    continue
                node = self._node(coord)
                is_endpoint = idx in (0, len(pts) - 1)
                node.wire_pts.append((wire.get("id"), idx, is_endpoint))
                k = quant(coord)
                if prev_key is not None:
                    self.uf.union(prev_key, k)
                    a = pts[idx - 1][0]
                    self.segments.append((wire.get("id"), idx - 1, a, coord,
                                          pts[idx - 1][1], _kind))
                prev_key = k
        for i, t in enumerate(ir.get("terminals", [])):
            self._node(tuple(t.get("at", (0, 0)))).terminals.append(i)
        for i, j in enumerate(ir.get("junctions", [])):
            self._node(tuple(j.get("at", (0, 0)))).junction = i
        for i, c in enumerate(ir.get("crossings", [])):
            self._node(tuple(c.get("at", (0, 0)))).crossing = (i, c.get("style"))

    def root_of(self, coord):
        return self.uf.find(quant(coord))

    def interior_crossings(self):
        """全部 内部×内部 十字交点：[(coord, wire_id_1, wire_id_2)]。"""
        out = []
        segs = self.segments
        for i in range(len(segs)):
            for j in range(i + 1, len(segs)):
                w1, _s1, a1, b1 = segs[i][0], segs[i][1], segs[i][2], segs[i][3]
                w2, _s2, a2, b2 = segs[j][0], segs[j][1], segs[j][2], segs[j][3]
                pt = segments_cross_interior(a1, b1, a2, b2)
                if pt is not None:
                    out.append((pt, w1, w2))
        return out

    def net_members(self):
        """net 名 -> [(comp_id, pin_name, coord)]。"""
        out = {}
        for node in self.nodes.values():
            for cid, pname, net in node.pins:
                if net:
                    out.setdefault(net, []).append((cid, pname, node.coord))
        return out

    def net_of_root(self, root):
        """某连通分量中出现的 net 名集合。"""
        nets = set()
        for k, node in self.nodes.items():
            if self.uf.find(k) == root:
                for _cid, _pname, net in node.pins:
                    if net:
                        nets.add(net)
        return nets
