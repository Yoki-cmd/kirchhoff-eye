#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""score_ir.py — 语义重画评分：truth IR vs candidate IR。

用法: score_ir.py truth.json candidate.json [--json] [--rounds N]
退出码: 0 评分完成 / 2 candidate 不过 schema / 3 IO 错误
对齐：确定性 RANSAC（全局平移+均匀缩放，不允许旋转；先试恒等变换）。
硬门禁：元件集合/类型、声明与几何 pin 连通、junction/crossing、元件方向/镜像。
软评分：相对方位、同排/同列、region 分组、走线方向序列、annotation 与元件文字语义。
绝对坐标、画布、标签坐标、RMSE 只作诊断，不进入最终质量分。
"""
import argparse
import json
import math
import sys

import jsonschema

import irlib
import validate_ir
from irlib import GeomIndex, IRModel, Report

BIG = 1e9
MATCH_MAX_DIST = 1.5   # config score_match.component_match_max_dist
INLIER_TOL = 0.75
KNN = 3
POLAR_TWO_TERMINAL_TYPES = {
    "polar_capacitor", "diode", "zener", "led", "battery",
    "vsource", "isource", "cvsource", "cisource",
}


# ---------------------------------------------------------------- 基础

def anchor_point(comp):
    if "from" in comp:
        return ((comp["from"][0] + comp["to"][0]) / 2.0,
                (comp["from"][1] + comp["to"][1]) / 2.0)
    return tuple(comp["at"])


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def normalize_text(s):
    for junk in ("\\mathrm", "{", "}", " "):
        s = s.replace(junk, "")
    return s


def hungarian(cost):
    """e-maxx 风格匈牙利算法：cost[n][m] (n<=m)，返回 row->col 匹配。"""
    n, m = len(cost), len(cost[0])
    u = [0.0] * (n + 1)
    v = [0.0] * (m + 1)
    p = [0] * (m + 1)
    way = [0] * (m + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [BIG * 10] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = BIG * 10
            j1 = -1
            for j in range(1, m + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    ans = [-1] * n
    for j in range(1, m + 1):
        if p[j] != 0:
            ans[p[j] - 1] = j - 1
    return ans


# ---------------------------------------------------------------- 对齐

def _inliers(truth_pts, cand_by_type, s, t):
    cnt = 0
    for ctype, pt in truth_pts:
        best = None
        for cp in cand_by_type.get(ctype, []):
            d = dist(((cp[0] - t[0]) / s, (cp[1] - t[1]) / s), pt)
            if best is None or d < best:
                best = d
        if best is not None and best <= INLIER_TOL:
            cnt += 1
    return cnt


def estimate_alignment(truth_comps, cand_comps):
    """确定性 RANSAC：p_cand = s·p_truth + t。返回 (s, (tx,ty))。"""
    truth_pts = [(c["type"], anchor_point(c)) for c in truth_comps]
    cand_by_type = {}
    for c in cand_comps:
        cand_by_type.setdefault(c["type"], []).append(anchor_point(c))
    if not truth_pts or not cand_by_type:
        return 1.0, (0.0, 0.0)
    n = len(truth_pts)
    best = (_inliers(truth_pts, cand_by_type, 1.0, (0.0, 0.0)), 0.0, 0.0,
            1.0, (0.0, 0.0))
    if best[0] < n:  # 恒等变换没全中才枚举
        for i1 in range(min(n, 8)):
            for i2 in range(i1 + 1, min(n, 8)):
                t1, t2 = truth_pts[i1], truth_pts[i2]
                d_t = dist(t1[1], t2[1])
                if d_t < 1.0:
                    continue
                for c1 in cand_by_type.get(t1[0], []):
                    for c2 in cand_by_type.get(t2[0], []):
                        if c1 == c2:
                            continue
                        s = dist(c1, c2) / d_t
                        if not 0.2 <= s <= 5.0:
                            continue
                        t = (c1[0] - s * t1[1][0], c1[1] - s * t1[1][1])
                        got = _inliers(truth_pts, cand_by_type, s, t)
                        key = (got, -abs(s - 1.0), -abs(t[0]) - abs(t[1]), s, t)
                        if key[:3] > best[:3]:
                            best = key
    s, t = best[3], best[4]
    # 内点最小二乘精化
    pairs = []
    for ctype, pt in truth_pts:
        cands = cand_by_type.get(ctype, [])
        if not cands:
            continue
        cp = min(cands, key=lambda c: dist(((c[0] - t[0]) / s, (c[1] - t[1]) / s), pt))
        if dist(((cp[0] - t[0]) / s, (cp[1] - t[1]) / s), pt) <= INLIER_TOL:
            pairs.append((pt, cp))
    if len(pairs) >= 2:
        mt = [sum(p[0][k] for p in pairs) / len(pairs) for k in (0, 1)]
        mc = [sum(p[1][k] for p in pairs) / len(pairs) for k in (0, 1)]
        num = sum((p[0][0] - mt[0]) * (p[1][0] - mc[0]) +
                  (p[0][1] - mt[1]) * (p[1][1] - mc[1]) for p in pairs)
        den = sum((p[0][0] - mt[0]) ** 2 + (p[0][1] - mt[1]) ** 2 for p in pairs)
        if den > 1e-9 and num > 1e-9:
            s = num / den
            t = (mc[0] - s * mt[0], mc[1] - s * mt[1])
    return s, t


# ---------------------------------------------------------------- 评分器

class Scorer(object):
    def __init__(self, truth, cand, anchors, config):
        self.truth = truth
        self.cand = cand
        self.t_model = IRModel(truth, anchors)
        self.c_model = IRModel(cand, anchors)
        self.t_geom = GeomIndex(self.t_model)
        self.c_geom = GeomIndex(self.c_model)
        self.c_validation = Report()
        validate_ir.run_checks(self.c_validation, self.c_model, cand, "full")
        self.w = config.get("score_weights", {})
        self.max_dist = config.get("score_match", {}).get(
            "component_match_max_dist", MATCH_MAX_DIST)
        self.tc = truth.get("components", [])
        self.cc = cand.get("components", [])
        self.s, self.t = estimate_alignment(self.tc, self.cc)
        self.matches = self._match(type_gated=True)     # [(ti, ci)]
        self.confusion = self._confusion()

    def inv(self, p):
        return ((p[0] - self.t[0]) / self.s, (p[1] - self.t[1]) / self.s)

    def _match(self, type_gated):
        if not self.tc or not self.cc:
            return []
        pairs = []
        used_t = set()
        used_c = set()
        candidate_by_id = {comp.get("id"): index for index, comp in enumerate(self.cc)}
        for ti, tcomp in enumerate(self.tc):
            ci = candidate_by_id.get(tcomp.get("id"))
            if ci is None:
                continue
            ccomp = self.cc[ci]
            if type_gated and tcomp["type"] != ccomp["type"]:
                continue
            pairs.append((ti, ci))
            used_t.add(ti)
            used_c.add(ci)
        remaining_t = [i for i in range(len(self.tc)) if i not in used_t]
        remaining_c = [i for i in range(len(self.cc)) if i not in used_c]
        if not remaining_t or not remaining_c:
            return sorted(pairs)
        cost = []
        for ti in remaining_t:
            tcomp = self.tc[ti]
            row = []
            tp = anchor_point(tcomp)
            for ci in remaining_c:
                ccomp = self.cc[ci]
                d = dist(tp, self.inv(anchor_point(ccomp)))
                ok = d <= self.max_dist and (
                    not type_gated or tcomp["type"] == ccomp["type"])
                row.append(d if ok else BIG)
            cost.append(row)
        n, m = len(cost), len(cost[0])
        if n > m:  # 匈牙利要求 n<=m：转置后求解再转回
            costT = [[cost[i][j] for i in range(n)] for j in range(m)]
            ansT = hungarian(costT)
            pairs.extend((remaining_t[ansT[j]], remaining_c[j]) for j in range(m)
                         if ansT[j] >= 0 and cost[ansT[j]][j] < BIG / 2)
        else:
            ans = hungarian(cost)
            pairs.extend((remaining_t[i], remaining_c[ans[i]]) for i in range(n)
                         if ans[i] >= 0 and cost[i][ans[i]] < BIG / 2)
        return sorted(pairs)

    def _confusion(self):
        saved = self.matches
        pairs = self._match(type_gated=False)
        conf = {}
        for ti, ci in pairs:
            key = "%s->%s" % (self.tc[ti]["type"], self.cc[ci]["type"])
            conf[key] = conf.get(key, 0) + 1
        self.matches = saved
        return conf

    # ------------------------------------------------ 网表层

    def f1(self):
        if not self.tc and not self.cc:
            return 1.0, 1.0, 1.0
        if not self.matches:
            return 0.0, 0.0, 0.0
        p = len(self.matches) / float(len(self.cc))
        r = len(self.matches) / float(len(self.tc))
        f = 2 * p * r / (p + r) if p + r else 0.0
        return p, r, f

    def _pin_net_pairs(self):
        out = []
        for ti, ci in self.matches:
            tnets = {p["name"]: p.get("net") for p in self.tc[ti].get("pins", [])}
            cnets = {p["name"]: p.get("net") for p in self.cc[ci].get("pins", [])}
            for name in sorted(tnets):
                if name in cnets:
                    out.append((tnets[name], cnets[name]))
        return out

    def connectivity(self):
        pins = self._pin_net_pairs()
        n = len(pins)
        if n < 2:
            return 1.0 if self.matches else 0.0, bool(self.matches)
        agree = total = 0
        for i in range(n):
            for j in range(i + 1, n):
                total += 1
                same_t = pins[i][0] == pins[j][0]
                same_c = pins[i][1] == pins[j][1]
                if same_t == same_c:
                    agree += 1
        rand = agree / float(total)
        _p, r, _f = self.f1()
        equivalent = (rand == 1.0 and r == 1.0 and
                      len(self.matches) == len(self.cc))
        return rand, equivalent

    def values(self):
        hit = total = 0
        for ti, ci in self.matches:
            for field in ("label", "value"):
                tv = self.tc[ti].get(field)
                if tv is None:
                    continue
                total += 1
                cv = self.cc[ci].get(field)
                if cv is not None and normalize_text(tv) == normalize_text(cv):
                    hit += 1
        return hit / float(total) if total else 1.0

    # ------------------------------------------------ 布局层

    def _matched_points(self):
        return [(anchor_point(self.tc[ti]), self.inv(anchor_point(self.cc[ci])))
                for ti, ci in self.matches]

    @staticmethod
    def _octant(a, b):
        ang = math.atan2(b[1] - a[1], b[0] - a[0])
        return int(round(ang / (math.pi / 4))) % 8

    def bearing(self):
        pts = self._matched_points()
        if len(pts) < 2:
            return 1.0 if pts else 0.0
        hit = total = 0
        for i, (tp, _cp) in enumerate(pts):
            neigh = sorted((dist(tp, pts[j][0]), j) for j in range(len(pts))
                           if j != i)[:KNN]
            for _d, j in neigh:
                total += 1
                if self._octant(tp, pts[j][0]) == self._octant(pts[i][1], pts[j][1]):
                    hit += 1
        return hit / float(total) if total else 1.0

    def rmse(self):
        pts = self._matched_points()
        if not pts:
            return 0.0, None
        ms = sum(dist(t, c) ** 2 for t, c in pts) / len(pts)
        rmse = math.sqrt(ms)
        return max(0.0, 1.0 - rmse / self.max_dist), rmse

    @staticmethod
    def _dir_string(pts):
        s = []
        for k in range(1, len(pts)):
            dx = pts[k][0] - pts[k - 1][0]
            dy = pts[k][1] - pts[k - 1][1]
            if abs(dx) >= abs(dy):
                direction = "R" if dx >= 0 else "L"
            else:
                direction = "U" if dy >= 0 else "D"
            if not s or s[-1] != direction:
                s.append(direction)
        return "".join(s)

    @staticmethod
    def _edit(a, b):
        dp = list(range(len(b) + 1))
        for i in range(1, len(a) + 1):
            prev, dp[0] = dp[0], i
            for j in range(1, len(b) + 1):
                cur = min(dp[j] + 1, dp[j - 1] + 1,
                          prev + (a[i - 1] != b[j - 1]))
                prev, dp[j] = dp[j], cur
        return dp[-1]

    def _wire_geoms(self, model, invert):
        out = []
        for w in model.ir.get("wires", []):
            pts = [p[0] for p in model.wire_points(w) if p[0] is not None]
            if len(pts) >= 2:
                if invert:
                    pts = [self.inv(p) for p in pts]
                out.append(pts)
        return out

    def wires(self):
        tw = self._wire_geoms(self.t_model, invert=False)
        cw = self._wire_geoms(self.c_model, invert=True)
        if not tw:
            return 1.0
        if not cw:
            return 0.0
        cost = []
        for tp in tw:
            row = []
            for cp in cw:
                fwd = dist(tp[0], cp[0]) + dist(tp[-1], cp[-1])
                rev = dist(tp[0], cp[-1]) + dist(tp[-1], cp[0])
                row.append(min(fwd, rev) if min(fwd, rev) <= 4.0 else BIG)
            cost.append(row)
        n, m = len(cost), len(cost[0])
        if n > m:
            costT = [[cost[i][j] for i in range(n)] for j in range(m)]
            ansT = hungarian(costT)
            pairs = [(ansT[j], j) for j in range(m)
                     if ansT[j] >= 0 and cost[ansT[j]][j] < BIG / 2]
        else:
            ans = hungarian(cost)
            pairs = [(i, ans[i]) for i in range(n)
                     if ans[i] >= 0 and cost[i][ans[i]] < BIG / 2]
        score = 0.0
        for ti, ci in pairs:
            ts = self._dir_string(tw[ti])
            fwd = dist(tw[ti][0], cw[ci][0]) + dist(tw[ti][-1], cw[ci][-1])
            rev = dist(tw[ti][0], cw[ci][-1]) + dist(tw[ti][-1], cw[ci][0])
            cpts = cw[ci] if fwd <= rev else list(reversed(cw[ci]))
            cs = self._dir_string(cpts)
            denom = max(len(ts), len(cs), 1)
            score += 1.0 - self._edit(ts, cs) / float(denom)
        return score / max(len(tw), len(cw))

    def label_sides(self):
        hit = total = 0
        for ti, ci in self.matches:
            for field in ("label_side", "value_side"):
                tv = self.tc[ti].get(field)
                if tv is None:
                    continue
                total += 1
                if self.cc[ci].get(field) == tv:
                    hit += 1
        return hit / float(total) if total else 1.0

    def orientation(self):
        hit = total = 0
        for ti, ci in self.matches:
            tcomp, ccomp = self.tc[ti], self.cc[ci]
            if "from" in tcomp and "from" in ccomp:
                total += 1
                tdx = tcomp["to"][0] - tcomp["from"][0]
                tdy = tcomp["to"][1] - tcomp["from"][1]
                cdx = ccomp["to"][0] - ccomp["from"][0]
                cdy = ccomp["to"][1] - ccomp["from"][1]
                sgn = lambda v: (v > 1e-9) - (v < -1e-9)
                if (sgn(tdx), sgn(tdy)) == (sgn(cdx), sgn(cdy)):
                    hit += 1
            elif self.t_model.kind_of(tcomp) == "multi":
                total += 1
                if (int(tcomp.get("rotate", 0)) == int(ccomp.get("rotate", 0))
                        and bool(tcomp.get("mirror")) == bool(ccomp.get("mirror"))
                        and tcomp.get("variant") == ccomp.get("variant")):
                    hit += 1
        return hit / float(total) if total else 1.0

    # ------------------------------------------------ 语义重画门禁与软指标

    def component_set_type_gate(self):
        truth = sorted((c.get("id"), c.get("type")) for c in self.tc)
        candidate = sorted((c.get("id"), c.get("type")) for c in self.cc)
        return truth == candidate

    @staticmethod
    def _pin_partitions(components):
        by_net = {}
        for comp in components:
            for pin in comp.get("pins", []):
                by_net.setdefault(pin.get("net"), set()).add(
                    (comp.get("id"), pin.get("name")))
        return sorted(tuple(sorted(members)) for members in by_net.values())

    def pin_net_gate(self):
        return self._pin_partitions(self.tc) == self._pin_partitions(self.cc)

    @staticmethod
    def _geometric_pin_partitions(model, geom):
        by_root = {}
        for comp in model.ir.get("components", []):
            for pin_name, coord in (model.pin_positions(comp) or {}).items():
                by_root.setdefault(geom.root_of(coord), set()).add((comp.get("id"), pin_name))
        return sorted(tuple(sorted(members)) for members in by_root.values() if members)

    def geometric_topology_gate(self):
        if self._geometric_pin_partitions(self.t_model, self.t_geom) != self._geometric_pin_partitions(
                self.c_model, self.c_geom):
            return False
        report = Report()
        validate_ir.check_topology(report, self.c_model, self.cand, self.c_geom)
        validate_ir.check_markers_on_wires(report, self.c_model, self.cand, self.c_geom)
        return not report.has_error()

    def candidate_full_validation_gate(self):
        return not self.c_validation.has_error()

    def orientation_gate(self):
        candidate = {c.get("id"): c for c in self.cc}
        for truth in self.tc:
            cand = candidate.get(truth.get("id"))
            if cand is None or truth.get("type") != cand.get("type"):
                return False
            if "from" in truth and truth.get("type") in POLAR_TWO_TERMINAL_TYPES:
                def sign(value):
                    return (value > 1e-9) - (value < -1e-9)
                tdir = (sign(truth["to"][0] - truth["from"][0]),
                        sign(truth["to"][1] - truth["from"][1]))
                cdir = (sign(cand["to"][0] - cand["from"][0]),
                        sign(cand["to"][1] - cand["from"][1]))
                if tdir != cdir:
                    return False
            elif self.t_model.kind_of(truth) == "multi":
                fields = ("rotate", "mirror", "variant")
                if any(truth.get(field) != cand.get(field) for field in fields):
                    return False
        return True

    @staticmethod
    def _point_on_segment(point, start, end, tolerance=irlib.EPS):
        return (irlib.pt_close(point, start, tolerance)
                or irlib.pt_close(point, end, tolerance)
                or irlib.point_on_segment_interior(point, start, end, tolerance))

    @classmethod
    def _incident_signature(cls, model, point):
        pins = []
        for comp in model.ir.get("components", []):
            for name, coord in (model.pin_positions(comp) or {}).items():
                if irlib.pt_close(coord, point):
                    pins.append("%s.%s" % (comp["id"], name))
        directions = []
        for wire in model.ir.get("wires", []):
            coords = [coord for coord, _kind, _raw in model.wire_points(wire)
                      if coord is not None]
            for index in range(1, len(coords)):
                start, end = coords[index - 1], coords[index]
                if not cls._point_on_segment(point, start, end):
                    continue
                if abs(end[0] - start[0]) >= abs(end[1] - start[1]):
                    directions.append("horizontal")
                else:
                    directions.append("vertical")
        return tuple(sorted(pins)), tuple(sorted(directions))

    @classmethod
    def _mark_signatures(cls, model, section):
        result = []
        for item in model.ir.get(section, []):
            signature = [section]
            if section == "crossings":
                signature.append(item.get("style"))
            signature.extend(cls._incident_signature(model, tuple(item["at"])))
            result.append(tuple(signature))
        return sorted(result)

    def junction_crossing_gate(self):
        return (self._mark_signatures(self.t_model, "junctions") ==
                self._mark_signatures(self.c_model, "junctions") and
                self._mark_signatures(self.t_model, "crossings") ==
                self._mark_signatures(self.c_model, "crossings"))

    @staticmethod
    def _relations(points, tolerance=0.2):
        result = {}
        ids = sorted(points)
        for i, left in enumerate(ids):
            for right in ids[i + 1:]:
                a, b = points[left], points[right]
                dx, dy = b[0] - a[0], b[1] - a[1]
                result[(left, right)] = (
                    (dx > tolerance) - (dx < -tolerance),
                    (dy > tolerance) - (dy < -tolerance),
                    abs(dy) <= tolerance,
                    abs(dx) <= tolerance,
                )
        return result

    def relative_relations(self):
        truth_points = {self.tc[ti]["id"]: anchor_point(self.tc[ti])
                        for ti, _ci in self.matches}
        candidate_points = {self.tc[ti]["id"]: self.inv(anchor_point(self.cc[ci]))
                            for ti, ci in self.matches}
        truth_rel = self._relations(truth_points)
        if not truth_rel:
            return 1.0 if truth_points else 0.0
        candidate_rel = self._relations(candidate_points)
        return sum(candidate_rel.get(key) == value for key, value in truth_rel.items()) / float(len(truth_rel))

    @staticmethod
    def _region_pairs(ir):
        pairs = set()
        for region in ir.get("regions", []):
            ids = sorted(set(region.get("component_ids", [])))
            for i, left in enumerate(ids):
                for right in ids[i + 1:]:
                    pairs.add((left, right))
        return pairs

    def region_grouping(self):
        truth_pairs = self._region_pairs(self.truth)
        candidate_pairs = self._region_pairs(self.cand)
        ids = sorted(c.get("id") for c in self.tc)
        universe = [(left, right) for i, left in enumerate(ids) for right in ids[i + 1:]]
        if not universe:
            return 1.0
        return sum((pair in truth_pairs) == (pair in candidate_pairs)
                   for pair in universe) / float(len(universe))

    @staticmethod
    def _net_partitions_with_degrees(ir):
        by_net = {}
        for comp in ir.get("components", []):
            for pin in comp.get("pins", []):
                by_net.setdefault(pin.get("net"), set()).add(
                    (comp.get("id"), pin.get("name")))
        return {tuple(sorted(members)): len(members) for members in by_net.values()}

    @staticmethod
    def _rank_relations(values):
        keys = sorted(values)
        return {(left, right): (values[left] > values[right]) - (values[left] < values[right])
                for i, left in enumerate(keys) for right in keys[i + 1:]}

    @staticmethod
    def _pin_partition_for_net(model, name):
        return tuple(sorted(
            (comp.get("id"), pin.get("name"))
            for comp in model.ir.get("components", [])
            for pin in comp.get("pins", [])
            if pin.get("net") == name
        ))

    @staticmethod
    def _pin_partition_for_root(model, geom, root):
        return tuple(sorted(
            (comp.get("id"), pin_name)
            for comp in model.ir.get("components", [])
            for pin_name, coord in (model.pin_positions(comp) or {}).items()
            if geom.root_of(coord) == root
        ))

    @classmethod
    def _wire_role(cls, model, geom, wire_id):
        wire = model.wires.get(wire_id)
        if wire is None:
            return None
        points = [coord for coord, _kind, _raw in model.wire_points(wire) if coord is not None]
        if len(points) < 2:
            return ("wire", ())
        partitions = {
            cls._pin_partition_for_root(model, geom, geom.root_of(points[0])),
            cls._pin_partition_for_root(model, geom, geom.root_of(points[-1])),
        }
        nonempty = tuple(sorted(part for part in partitions if part))
        return ("wire", nonempty, cls._dir_string(points))

    @classmethod
    def _target_signature(cls, annotation, model, geom):
        if "target" in annotation:
            target = annotation["target"]
            if "component" in target:
                return ("component", target["component"])
            if "net" in target:
                return ("electrical", cls._pin_partition_for_net(model, target["net"]))
            if "node" in target:
                node = model.explicit_nodes.get(target["node"])
                root = geom.root_of(tuple(node["at"])) if node else None
                return ("electrical", cls._pin_partition_for_root(model, geom, root))
            if "wire" in target:
                return cls._wire_role(model, geom, target["wire"])
        if annotation.get("kind") == "voltage_measurement":
            def ref_signature(ref):
                return cls._target_signature(
                    {"target": {key: value for key, value in ref.items() if key != "marker_at"}},
                    model, geom)
            positive = ref_signature(annotation["positive_ref"])
            negative = ref_signature(annotation["negative_ref"])
            return (positive, negative)
        return None

    @classmethod
    def _annotation_signature(cls, annotation, model, geom):
        kind = annotation.get("kind")
        fields = [kind, cls._target_signature(annotation, model, geom), annotation.get("label")]
        if kind == "current_direction":
            fields.append(annotation.get("direction"))
        elif kind == "node_polarity":
            fields.append(annotation.get("polarity"))
        return tuple(fields)

    def annotation_ownership(self):
        truth = sorted(self._annotation_signature(a, self.t_model, self.t_geom)
                       for a in self.truth.get("annotations", []))
        candidate = sorted(self._annotation_signature(a, self.c_model, self.c_geom)
                           for a in self.cand.get("annotations", []))
        if not truth and not candidate:
            return 1.0
        matched = list(candidate)
        hit = 0
        for signature in truth:
            if signature in matched:
                hit += 1
                matched.remove(signature)
        return hit / float(max(len(truth), len(candidate)))

    def component_text(self):
        candidate = {component.get("id"): component for component in self.cc}
        total = hit = 0
        for truth in self.tc:
            cand = candidate.get(truth.get("id"), {})
            for field in ("label", "value"):
                if truth.get(field) is None and cand.get(field) is None:
                    continue
                total += 1
                if normalize_text(truth.get(field, "")) == normalize_text(cand.get(field, "")):
                    hit += 1
        return hit / float(total) if total else 1.0

    def human_label_coordinate_distance(self):
        candidate = {c.get("id"): c for c in self.cc}
        distances = []
        for truth in self.tc:
            if truth.get("label_at") is None:
                continue
            cand = candidate.get(truth.get("id"), {})
            if cand.get("label_at") is not None:
                distances.append(dist(tuple(truth["label_at"]), self.inv(tuple(cand["label_at"]))))
        return sum(distances) / float(len(distances)) if distances else 0.0

    # ------------------------------------------------ 汇总

    def report(self, rounds=None):
        p, r, f = self.f1()
        rand, equivalent = self.connectivity()
        val = self.values()
        bearing = self.bearing()
        rmse_score, rmse_raw = self.rmse()
        wires = self.wires()
        sides = self.label_sides()
        orient = self.orientation()
        wn = self.w.get("netlist", {"f1": 0.5, "connectivity": 0.4, "values": 0.1})
        wl = self.w.get("layout", {"bearing": 0.4, "rmse": 0.2, "wire_shape": 0.2,
                                   "label_side": 0.1, "orientation": 0.1})
        netlist = (wn["f1"] * f + wn["connectivity"] * rand + wn["values"] * val)
        legacy_layout = (wl["bearing"] * bearing + wl["rmse"] * rmse_score +
                         wl["wire_shape"] * wires + wl["label_side"] * sides +
                         wl["orientation"] * orient)

        gate_results = {
            "component_set_type": self.component_set_type_gate(),
            "pin_net_connectivity": self.pin_net_gate(),
            "geometric_topology": self.geometric_topology_gate(),
            "candidate_full_validation": self.candidate_full_validation_gate(),
            "junction_crossing": self.junction_crossing_gate(),
            "orientation_mirror": self.orientation_gate(),
        }
        failed = [name for name, passed in gate_results.items() if not passed]
        semantic_values = {
            "relative_relations": self.relative_relations(),
            "region_grouping": self.region_grouping(),
            "route_shape": wires,
            "annotation_ownership": self.annotation_ownership(),
            "component_text": self.component_text(),
        }
        semantic_weights = self.w.get("semantic", {
            "relative_relations": 0.30,
            "region_grouping": 0.15,
            "route_shape": 0.30,
            "annotation_ownership": 0.15,
            "component_text": 0.10,
        })
        weight_total = sum(semantic_weights.get(name, 0.0) for name in semantic_values)
        semantic = (sum(semantic_weights.get(name, 0.0) * value
                        for name, value in semantic_values.items()) / weight_total
                    if weight_total else 1.0)
        total = semantic if not failed else 0.0
        rnd = lambda x: round(x, 4)
        return {
            "score_version": "kirchhoff-semantic-score/2.0",
            "alignment": {"scale": rnd(self.s), "translate": [rnd(self.t[0]), rnd(self.t[1])]},
            "gates": {"passed": not failed, "failed": failed, **gate_results},
            "netlist": {
                "precision": rnd(p), "recall": rnd(r), "f1": rnd(f),
                "connectivity_rand": rnd(rand), "netlist_equivalent": equivalent,
                "values": rnd(val), "type_confusion": self.confusion,
                "score": rnd(netlist),
            },
            "semantic": {**{name: rnd(value) for name, value in semantic_values.items()},
                         "score": rnd(semantic)},
            "layout": {
                "bearing": rnd(bearing), "rmse_score": rnd(rmse_score),
                "rmse_raw": rnd(rmse_raw) if rmse_raw is not None else None,
                "wire_shape": rnd(wires), "label_side": rnd(sides),
                "orientation": rnd(orient), "score": rnd(legacy_layout),
                "diagnostic_only": True,
            },
            "diagnostics": {
                "human_label_coordinate_distance": rnd(self.human_label_coordinate_distance()),
                "absolute_geometry_affects_total": False,
                "candidate_validation_errors": sorted({
                    finding["code"] for finding in self.c_validation.findings
                    if finding["severity"] == "E"
                }),
            },
            "total": rnd(total),
            "rounds": rounds,
            "counts": {"truth": len(self.tc), "candidate": len(self.cc),
                       "matched": len(self.matches)},
        }


def main(argv=None):
    irlib.ensure_utf8_io()
    ap = argparse.ArgumentParser(description="truth vs candidate IR 评分")
    ap.add_argument("truth")
    ap.add_argument("candidate")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--rounds", type=int, default=None)
    args = ap.parse_args(argv)

    try:
        truth = irlib.load_json(args.truth)
        cand = irlib.load_json(args.candidate)
        schema = irlib.load_schema()
        anchors = irlib.load_anchors()
        config = irlib.load_config()
    except (OSError, ValueError) as e:
        sys.stderr.write("ERROR: 无法读取输入: %s\n" % e)
        return irlib.EXIT_ENV

    errs = list(jsonschema.Draft7Validator(schema).iter_errors(cand))
    if errs:
        sys.stderr.write("ERROR: candidate 不过 schema（%d 处），先 validate 再评分\n"
                         % len(errs))
        return irlib.EXIT_ERROR

    rep = Scorer(truth, cand, anchors, config).report(rounds=args.rounds)
    if args.json:
        sys.stdout.write(json.dumps(rep, ensure_ascii=False, indent=2,
                                    sort_keys=True) + "\n")
    else:
        n, s, l, gates = rep["netlist"], rep["semantic"], rep["layout"], rep["gates"]
        sys.stdout.write(
            "Total %.4f  gates=%s failed=%s  Semantic %.4f  rounds=%s\n"
            "  F1 %.4f (P %.4f R %.4f)  连接 %.4f  等价 %s  值 %.4f\n"
            "  相对关系 %.4f  分组 %.4f  走线 %.4f  标注归属 %.4f  元件文字 %.4f\n"
            "  诊断: 方位 %.4f RMSE %.4f(raw %s) 标签侧 %.4f 朝向 %.4f\n"
            "  对齐 s=%.4f t=%s  匹配 %d/%d(truth) %d(cand)\n"
            % (rep["total"], gates["passed"], gates["failed"], s["score"],
               rep["rounds"], n["f1"], n["precision"], n["recall"],
               n["connectivity_rand"], n["netlist_equivalent"], n["values"],
               s["relative_relations"], s["region_grouping"], s["route_shape"],
               s["annotation_ownership"], s["component_text"],
               l["bearing"], l["rmse_score"], l["rmse_raw"],
               l["label_side"], l["orientation"],
               rep["alignment"]["scale"], rep["alignment"]["translate"],
               rep["counts"]["matched"], rep["counts"]["truth"],
               rep["counts"]["candidate"]))
    return irlib.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
