#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""score_ir.py — 基准评分：truth IR vs candidate IR（PLAN.md §11）。

用法: score_ir.py truth.json candidate.json [--json] [--rounds N]
退出码: 0 评分完成 / 2 candidate 不过 schema / 3 IO 错误
对齐：确定性 RANSAC（全局平移+均匀缩放，不允许旋转；先试恒等变换）。
网表层：元件 F1（类型同+匈牙利匹配）/ 连接一致率（Rand Index）/ 值匹配率。
布局层：方位保持 / RMSE 折算 / 走线形状 / 标签侧 / 朝向。权重取 config.json。
"""
import argparse
import json
import math
import sys

import jsonschema

import irlib
from irlib import IRModel

BIG = 1e9
MATCH_MAX_DIST = 1.5   # config score_match.component_match_max_dist
INLIER_TOL = 0.75
KNN = 3


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
        cost = []
        for tcomp in self.tc:
            row = []
            tp = anchor_point(tcomp)
            for ccomp in self.cc:
                d = dist(tp, self.inv(anchor_point(ccomp)))
                ok = d <= self.max_dist and (
                    not type_gated or tcomp["type"] == ccomp["type"])
                row.append(d if ok else BIG)
            cost.append(row)
        n, m = len(cost), len(cost[0])
        if n > m:  # 匈牙利要求 n<=m：转置后求解再转回
            costT = [[cost[i][j] for i in range(n)] for j in range(m)]
            ansT = hungarian(costT)
            pairs = [(ansT[j], j) for j in range(m)
                     if ansT[j] >= 0 and cost[ansT[j]][j] < BIG / 2]
        else:
            ans = hungarian(cost)
            pairs = [(i, ans[i]) for i in range(n)
                     if ans[i] >= 0 and cost[i][ans[i]] < BIG / 2]
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
                s.append("R" if dx >= 0 else "L")
            else:
                s.append("U" if dy >= 0 else "D")
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
        return score / len(tw)

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
        wt = self.w.get("total", {"netlist": 0.6, "layout": 0.4})
        netlist = (wn["f1"] * f + wn["connectivity"] * rand + wn["values"] * val)
        layout = (wl["bearing"] * bearing + wl["rmse"] * rmse_score +
                  wl["wire_shape"] * wires + wl["label_side"] * sides +
                  wl["orientation"] * orient)
        total = wt["netlist"] * netlist + wt["layout"] * layout
        rnd = lambda x: round(x, 4)
        return {
            "alignment": {"scale": rnd(self.s), "translate": [rnd(self.t[0]), rnd(self.t[1])]},
            "netlist": {
                "precision": rnd(p), "recall": rnd(r), "f1": rnd(f),
                "connectivity_rand": rnd(rand), "netlist_equivalent": equivalent,
                "values": rnd(val), "type_confusion": self.confusion,
                "score": rnd(netlist),
            },
            "layout": {
                "bearing": rnd(bearing), "rmse_score": rnd(rmse_score),
                "rmse_raw": rnd(rmse_raw) if rmse_raw is not None else None,
                "wire_shape": rnd(wires), "label_side": rnd(sides),
                "orientation": rnd(orient), "score": rnd(layout),
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
        n, l = rep["netlist"], rep["layout"]
        sys.stdout.write(
            "Total %.4f  (Netlist %.4f / Layout %.4f)  rounds=%s\n"
            "  F1 %.4f (P %.4f R %.4f)  连接 %.4f  等价 %s  值 %.4f\n"
            "  方位 %.4f  RMSE %.4f(raw %s)  走线 %.4f  标签侧 %.4f  朝向 %.4f\n"
            "  对齐 s=%.4f t=%s  匹配 %d/%d(truth) %d(cand)\n"
            % (rep["total"], n["score"], l["score"], rep["rounds"],
               n["f1"], n["precision"], n["recall"], n["connectivity_rand"],
               n["netlist_equivalent"], n["values"],
               l["bearing"], l["rmse_score"], l["rmse_raw"], l["wire_shape"],
               l["label_side"], l["orientation"],
               rep["alignment"]["scale"], rep["alignment"]["translate"],
               rep["counts"]["matched"], rep["counts"]["truth"],
               rep["counts"]["candidate"]))
    return irlib.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
