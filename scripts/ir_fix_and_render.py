#!/usr/bin/env python3
"""
ir_fix_and_render.py -- IR JSON 自动修复 + 序列化渲染 + 线条布局诊断

功能：
  1. 验证 IR JSON，自动修复 E008（缺失 junction/crossing）
  2. 序列化为 circuitikz .tex + 渲染 .png
  3. [NEW] --layout-check：对 .tex 或 .ir.json 执行线条布局铁律检测

用法：
  python ir_fix_and_render.py <ir.json> [-o out_dir] [--dpi 300]
  python ir_fix_and_render.py <circuit.tex> --layout-check [--json]

退出码：0=成功, 1=有遗留错误需人工, 2=工具链故障, 3=环境错
"""

import argparse, json, os, re, subprocess, sys, math
from pathlib import Path
from collections import defaultdict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PROJECT_ROOT / "scripts"
ANCHORS_PATH = PROJECT_ROOT / "templates" / "anchors.json"
sys.path.insert(0, str(SCRIPTS))
import irlib

EPS = irlib.EPS

# ──────────────────────────────── utils ────────────────────────────────

def run_cmd(cmd, timeout=120):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                       encoding='utf-8', errors='replace')
    return r.returncode, r.stdout, r.stderr


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ──────────────────────────────── anchors / pin positions ──────────────

def _load_anchors():
    return load_json(ANCHORS_PATH)


def _pin_offsets(ctype, variant=None):
    """返回 {pin_name: (ox, oy)} 偏移量。"""
    anchors = _load_anchors()
    types = anchors.get("types", {})
    key = ctype
    if variant:
        vkey = f"{ctype}|{variant}"
        if vkey in types:
            key = vkey
    entry = types.get(key)
    if not entry or "pins" not in entry:
        return {}
    return {p: tuple(v["offset"]) for p, v in entry["pins"].items()}


def _rotate_ccw(v, deg):
    x, y = v
    d = deg % 360
    if d == 0:   return (x, y)
    if d == 90:  return (-y, x)
    if d == 180: return (-x, -y)
    if d == 270: return (y, -x)
    return v  # fallback


def pin_position(ctype, pin, at, rotate=0, mirror=False, variant=None):
    """Compute actual (x, y) for a component pin."""
    offsets = _pin_offsets(ctype, variant)
    if pin not in offsets:
        return None
    ox, oy = offsets[pin]
    ox, oy = _rotate_ccw((ox, oy), rotate)
    if mirror:
        ox = -ox
    return (at[0] + ox, at[1] + oy)


def seg_is_horizontal(p, q, tol=EPS):
    return abs(p[1] - q[1]) <= tol and not (abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol)


def seg_is_vertical(p, q, tol=EPS):
    return abs(p[0] - q[0]) <= tol and not (abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol)


# ──────────────────── existing IR fix logic ────────────────────────────

def validate(ir_path):
    rc, stdout, stderr = run_cmd([
        sys.executable, str(SCRIPTS / "validate_ir.py"),
        str(ir_path), "--phase", "full", "--json"
    ])
    if rc not in (0, 1, 2):
        print(f"ERROR: 验证器退出码 {rc}\n{stderr}")
        sys.exit(3)
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        print(f"ERROR: 验证器输出非 JSON\n{stdout[:500]}")
        sys.exit(3)
    return data.get("findings", [])


def classify_findings(findings):
    auto_fixable = []
    needs_human = []
    for f in findings:
        if f["severity"] != "E":
            continue
        if f["code"] == "E008":
            auto_fixable.append(f)
        else:
            needs_human.append(f)
    return auto_fixable, needs_human


def extract_coord_from_e008(msg):
    m = re.search(r'\[([0-9.\-]+),\s*([0-9.\-]+)\]', msg)
    if m:
        return (float(m.group(1)), float(m.group(2)))
    return None


def fix_e008(ir_data, findings):
    fixed = 0
    for f in findings:
        if f["code"] != "E008":
            continue
        coord = extract_coord_from_e008(f["message"])
        if coord is None:
            print(f"  [SKIP] 无法从 '{f['message'][:80]}' 提取坐标")
            continue
        msg = f["message"]
        at = [coord[0], coord[1]]
        if "四路汇合" in msg or "junction" in msg.lower():
            existing = [j["at"] for j in ir_data.get("junctions", [])]
            if at not in existing:
                ir_data.setdefault("junctions", []).append({"at": at})
                print(f"  [FIX] 添加 junction at {at}")
                fixed += 1
        elif "十字交叉" in msg:
            existing = [c["at"] for c in ir_data.get("crossings", [])]
            if at not in existing:
                ir_data.setdefault("crossings", []).append({"at": at, "style": "plain"})
                print(f"  [FIX] 添加 crossing at {at}")
                fixed += 1
        else:
            print(f"  [SKIP] 无法判断 E008 类型: {msg[:80]}")
    return fixed


def serialize(ir_path, tex_path):
    rc, stdout, stderr = run_cmd([
        sys.executable, str(SCRIPTS / "ir2tikz.py"),
        str(ir_path), "-o", str(tex_path), "--debug"
    ])
    if rc != 0:
        if "No such file or directory" in stderr:
            os.makedirs(os.path.dirname(tex_path), exist_ok=True)
            rc, stdout, stderr = run_cmd([
                sys.executable, str(SCRIPTS / "ir2tikz.py"),
                str(ir_path), "-o", str(tex_path), "--debug"
            ])
    if rc != 0:
        print(f"ERROR: 序列化失败\n{stderr[-500:]}")
        return False
    print(f"  OK -> {tex_path}")
    return True


def render(tex_path, png_path, dpi=300):
    rc, stdout, stderr = run_cmd([
        sys.executable, str(SCRIPTS / "render.py"),
        str(tex_path), "-o", str(png_path), "--dpi", str(dpi)
    ])
    if rc != 0:
        print(f"ERROR: 渲染失败\n{stderr[-300:]}")
        return False
    print(f"  OK -> {png_path}")
    return True


# ════════════════════════ layout check (NEW) ════════════════════════════

# ──── TikZ parser ────

def _parse_tex_coord(s):
    """Parse '(x,y)' or 'x,y' or 'N_xxx' or 'Q1.B' into components.
    Returns ('literal', (x, y)) or ('named', 'Q1.B') or ('coord', 'N_1')."""
    s = s.strip().strip('()')  # strip outer parentheses
    # literal coordinate: 1.5,2.55
    m = re.match(r'^([\d.\-]+),\s*([\d.\-]+)$', s)
    if m:
        return ('literal', (float(m.group(1)), float(m.group(2))))
    # named: Q1.B, N_4
    if re.match(r'^[A-Za-z_][A-Za-z0-9_.]*$', s):
        if '.' in s:
            return ('named', s)
        return ('coord', s)
    return ('unknown', s)


def parse_tex_components(tex_content):
    """Extract component positions and types from .tex circuitikz code."""
    comps = {}
    # \node[npn] (Q3) at (4,0.45) {};
    for m in re.finditer(
        r'\\node\[([^\]]*)\]\s*\((\w+)\)\s*at\s*\(([\d.\-]+),([\d.\-]+)\)',
        tex_content
    ):
        props, name, x, y = m.group(1), m.group(2), float(m.group(3)), float(m.group(4))
        # Determine type from props
        ctype = None
        mirror = False
        rotate = 0
        if 'npn' in props:
            ctype = 'npn'
        elif 'pnp' in props:
            ctype = 'pnp'
        elif 'nmos' in props:
            ctype = 'nmos'
        elif 'pmos' in props:
            ctype = 'pmos'
        if 'xscale=-1' in props:
            mirror = True
        rot_m = re.search(r'rotate=(\d+)', props)
        if rot_m:
            rotate = int(rot_m.group(1))
        if ctype:
            comps[name] = {'type': ctype, 'at': (x, y), 'mirror': mirror, 'rotate': rotate}
        else:
            comps[name] = {'type': 'unknown', 'at': (x, y), 'mirror': mirror, 'rotate': rotate,
                           'props': props}

    # Two-terminal components: \draw (...) to[R, name=Rx, ...] (...);
    for m in re.finditer(
        r'\\draw\s*\(([^)]+)\)\s*to\[([^\]]*)\]\s*\(([^)]+)\)',
        tex_content
    ):
        p1_str, props, p2_str = m.group(1), m.group(2), m.group(3)
        # extract name
        name_m = re.search(r'name=(\w+)', props)
        if not name_m:
            continue
        name = name_m.group(1)
        ctype = None
        for t in ['R', 'C', 'L', 'I', 'V', 'D', 'battery', 'capacitor', 'polar_capacitor',
                   'diode', 'leD', 'zzener', 'cute_inductor', 'american_inductor']:
            # match type: [R, ...] or [I, ...] etc
            type_m = re.match(r'([A-Za-z_]+)', props.split(',')[0].strip())
            if type_m:
                ctype = type_m.group(1)
                break
        if not ctype:
            ctype = 'unknown_two'
        # parse coordinates
        c1 = _parse_tex_coord(p1_str)
        c2 = _parse_tex_coord(p2_str)
        from_pt = c1[1] if c1[0] == 'literal' else None
        to_pt = c2[1] if c2[0] == 'literal' else None
        comps[name] = {
            'type': ctype, 'kind': 'two',
            'from': from_pt, 'to': to_pt,
        }

    return comps


def parse_tex_wires(tex_content):
    """Extract wire paths from .tex circuitikz code.
    Returns list of paths, each = list of (type, value) waypoints."""
    paths = []
    for m in re.finditer(r'\\draw\s*(.+?);', tex_content, re.DOTALL):
        body = m.group(1).strip()
        # Skip component draw commands (those with 'to[')
        if 'to[' in body:
            continue
        # Split by ' -- '
        parts = body.split('--')
        waypoints = []
        for p in parts:
            wp = _parse_tex_coord(p)
            if wp[0] != 'unknown':
                waypoints.append(wp)
        if len(waypoints) >= 2:
            paths.append(waypoints)
    return paths


def parse_tex_coordinates(tex_content):
    """Extract named coordinate definitions."""
    coords = {}
    for m in re.finditer(
        r'\\coordinate\s*\((\w+)\)\s*at\s*\(([\d.\-]+),([\d.\-]+)\)',
        tex_content
    ):
        coords[m.group(1)] = (float(m.group(2)), float(m.group(3)))
    return coords


def parse_tex_current_sources(tex_content):
    """Find current source (I) components and their from/to positions."""
    sources = []
    for m in re.finditer(
        r'\\draw\s*\(([^)]+)\)\s*to\[I,\s*name=(\w+)[^\]]*\]\s*\(([^)]+)\)',
        tex_content
    ):
        c1 = _parse_tex_coord(m.group(1))
        c2 = _parse_tex_coord(m.group(3))
        name = m.group(2)
        sources.append({
            'name': name,
            'from': c1[1] if c1[0] == 'literal' else None,
            'to': c2[1] if c2[0] == 'literal' else None,
        })
    return sources


# ──── resolver: name/coord → (x, y) ────

class TexResolver:
    """Resolve named anchors and coordinates in a .tex circuit to (x,y)."""

    def __init__(self, tex_content):
        self.coords = parse_tex_coordinates(tex_content)
        self.comps = parse_tex_components(tex_content)

    def resolve(self, wp):
        """wp is ('literal', (x,y)) or ('named', 'Q1.B') or ('coord', 'N_4')."""
        typ, val = wp
        if typ == 'literal':
            return val
        if typ == 'coord':
            return self.coords.get(val)
        if typ == 'named':
            # Q1.B
            parts = val.split('.')
            if len(parts) == 2:
                comp_name, pin = parts
                comp = self.comps.get(comp_name)
                if comp and 'at' in comp:
                    return pin_position(
                        comp['type'], pin, comp['at'],
                        rotate=comp.get('rotate', 0),
                        mirror=comp.get('mirror', False)
                    )
            return None
        return None


# ──── layout checks ────

def check_orthogonality(wire_paths, resolver):
    """铁律一：检测斜线。"""
    findings = []
    for pi, path in enumerate(wire_paths):
        for i in range(len(path) - 1):
            p1 = resolver.resolve(path[i])
            p2 = resolver.resolve(path[i + 1])
            if p1 is None or p2 is None:
                continue
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            if not irlib.is_strictly_orthogonal(p1, p2):
                findings.append({
                    'code': 'E004',
                    'path': f'/tex/wires/{pi}/segments/{i}',
                    'rule': '铁律一·斜线',
                    'severity': 'E',
                    'path_index': pi,
                    'seg_index': i,
                    'p1': p1, 'p2': p2,
                    'dx': round(dx, 4), 'dy': round(dy, 4),
                    'message': f'斜线: ({p1[0]:.2f},{p1[1]:.2f}) -> ({p2[0]:.2f},{p2[1]:.2f})  dx={dx:.3f} dy={dy:.3f}',
                    'hint': '平移连接点或增加 L 形 elbow 消除斜线',
                })
    return findings


def check_backtrack(wire_paths, resolver):
    """铁律二：检测水平/竖直折返。"""
    findings = []
    for pi, path in enumerate(wire_paths):
        segments = []
        for i in range(len(path) - 1):
            p1 = resolver.resolve(path[i])
            p2 = resolver.resolve(path[i + 1])
            if p1 is None or p2 is None:
                continue
            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            if abs(dx) > EPS and abs(dy) <= EPS:
                segments.append(('H', dx, i, p1, p2))
            elif abs(dy) > EPS and abs(dx) <= EPS:
                segments.append(('V', dy, i, p1, p2))

        # check consecutive same-direction segments
        for j in range(len(segments) - 1):
            s1 = segments[j]
            s2 = segments[j + 1]
            if s1[0] == s2[0] and s1[2] + 1 == s2[2]:  # same dir, consecutive in path
                if s1[0] == 'H' and s1[1] * s2[1] < 0:
                    findings.append({
                        'rule': '铁律二·水平折返',
                        'severity': 'E',
                        'path_index': pi,
                        'seg_indices': [s1[2], s2[2]],
                        'message': f'水平折返: dx1={s1[1]:.2f} dx2={s2[1]:.2f} — 导线先{"右" if s1[1]>0 else "左"}后{"右" if s2[1]>0 else "左"}',
                        'hint': '检查是否有多余绕路点（如 N_8 在端点之外），去掉绕路直连',
                    })
                elif s1[0] == 'V' and s1[1] * s2[1] < 0:
                    findings.append({
                        'rule': '铁律二·竖直折返',
                        'severity': 'E',
                        'path_index': pi,
                        'seg_indices': [s1[2], s2[2]],
                        'message': f'竖直折返: dy1={s1[1]:.2f} dy2={s2[1]:.2f} — 导线先{"上" if s1[1]>0 else "下"}后{"上" if s2[1]>0 else "下"}',
                        'hint': '移动元件使两端引脚对齐到同一水平/竖直线，消除折返',
                    })
    return findings


def check_midpoint(wire_paths, resolver, sources, comps):
    """铁律三：检查电流源接入点是否在两管中点。"""
    findings = []
    for src in sources:
        # find which net the source terminal connects to
        for term_key, term_pt in [('from', src.get('from')), ('to', src.get('to'))]:
            if term_pt is None:
                continue
            # Look for wires that pass through or end at this point
            # Step 1: find paths directly containing the source terminal
            direct_paths = set()
            for pi, path in enumerate(wire_paths):
                for wp in path:
                    pt = resolver.resolve(wp)
                    if pt and abs(pt[0] - term_pt[0]) < EPS and abs(pt[1] - term_pt[1]) < EPS:
                        direct_paths.add(pi)
                        break

            # Step 2: collect resolved coords from direct paths (for junction tracing)
            shared_pts = set()
            for pi in direct_paths:
                for wp in wire_paths[pi]:
                    pt = resolver.resolve(wp)
                    if pt:
                        shared_pts.add((round(pt[0], 3), round(pt[1], 3)))

            # Step 3: find junction-connected paths (share any coord with direct paths)
            all_paths = set(direct_paths)
            for pi, path in enumerate(wire_paths):
                if pi in all_paths:
                    continue
                for wp in path:
                    pt = resolver.resolve(wp)
                    if pt and (round(pt[0], 3), round(pt[1], 3)) in shared_pts:
                        all_paths.add(pi)
                        break

            # Step 4: collect transistor pins from all connected paths
            connected_pins = []
            for pi in all_paths:
                for wp in wire_paths[pi]:
                    if wp[0] == 'named':
                        pin_pt = resolver.resolve(wp)
                        if pin_pt:
                            connected_pins.append({
                                'name': wp[1],
                                'pos': pin_pt
                            })

            # Group pins by y (for horizontal alignment) or x (for vertical alignment)
            if len(connected_pins) >= 2:
                # Check if source is vertical (from.x == to.x) → look for horizontal alignment
                if src.get('from') and src.get('to'):
                    fx, fy = src['from']
                    tx, ty = src['to']
                    if abs(fx - tx) < EPS:  # vertical source
                        # Check midpoint on horizontal wires
                        same_y_pins = defaultdict(list)
                        for pin in connected_pins:
                            same_y_pins[round(pin['pos'][1], 2)].append(pin)
                        for y, pins in same_y_pins.items():
                            if len(pins) >= 2 and abs(y - fy) < 5.0:  # source within reasonable reach
                                xs = sorted(p['pos'][0] for p in pins)
                                mid = (xs[0] + xs[-1]) / 2
                                if abs(term_pt[0] - mid) > 0.02:
                                    findings.append({
                                        'rule': '铁律三·中点偏移',
                                        'severity': 'W',
                                        'source': src['name'],
                                        'terminal': term_key,
                                        'current_x': term_pt[0],
                                        'expected_x': round(mid, 2),
                                        'pins': [p['name'] for p in pins],
                                        'message': f'{src["name"]}.{term_key} 接入点 x={term_pt[0]:.2f} 不在中点 x={mid:.2f}（管脚: {[p["name"] for p in pins]}）',
                                        'hint': f'若中点 x={mid:.2f} 不落 0.5 网格，移动两侧晶体管使中点落网；否则移动电流源至 x={mid:.2f}',
                                    })
                    elif abs(fy - ty) < EPS:  # horizontal source
                        # Check midpoint on vertical wires
                        same_x_pins = defaultdict(list)
                        for pin in connected_pins:
                            same_x_pins[round(pin['pos'][0], 2)].append(pin)
                        for x, pins in same_x_pins.items():
                            if len(pins) >= 2:
                                ys = sorted(p['pos'][1] for p in pins)
                                mid = (ys[0] + ys[-1]) / 2
                                if abs(term_pt[1] - mid) > 0.02:
                                    findings.append({
                                        'rule': '铁律三·中点偏移',
                                        'severity': 'W',
                                        'source': src['name'],
                                        'terminal': term_key,
                                        'current_y': term_pt[1],
                                        'expected_y': round(mid, 2),
                                        'pins': [p['name'] for p in pins],
                                        'message': f'{src["name"]}.{term_key} 接入点 y={term_pt[1]:.2f} 不在中点 y={mid:.2f}',
                                        'hint': f'若中点 y={mid:.2f} 不落 0.5 网格，移动两侧晶体管使中点落网；否则移动电流源至 y={mid:.2f}',
                                    })
    return findings


def check_pin_connectivity(wire_paths, resolver, comps):
    """铁律五·步骤4：检查所有多端件引脚是否接入导线。"""
    findings = []
    all_pins = []
    for name, comp in comps.items():
        if 'at' not in comp:
            continue
        ctype = comp['type']
        if ctype in ('unknown', 'unknown_two'):
            continue
        offsets = _pin_offsets(ctype)
        if not offsets:
            continue
        for pin in offsets:
            all_pins.append(f'{name}.{pin}')

    connected = set()
    for path in wire_paths:
        for wp in path:
            if wp[0] == 'named':
                connected.add(wp[1])

    for pin_ref in all_pins:
        if pin_ref not in connected:
            findings.append({
                'rule': '铁律五·引脚未接',
                'severity': 'E',
                'pin': pin_ref,
                'message': f'引脚 {pin_ref} 未接入任何导线',
                'hint': '检查是否遗漏了该引脚的连线',
            })

    return findings


def layout_check_ir(ir_path, output_json=False):
    """IR-driven layout check; explicit pin refs are the connectivity truth."""
    ir = irlib.load_json(ir_path)
    import validate_ir
    validated = validate_ir.validate_document(ir, "full")
    report = layout_report_from_validated(validated, file_name=str(ir_path))
    if output_json:
        Path(ir_path).with_suffix('.layout_report.json').write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return report["findings"]


def layout_report_from_validated(validated, file_name="<memory>"):
    if validated.model is None:
        raise ValueError("layout check requires a schema-valid IR")
    ir = validated.document
    model = validated.model
    findings = []
    connected = {
        point["pin"]
        for wire in ir.get("wires", [])
        for point in wire.get("points", [])
        if "pin" in point
    }
    for ci, comp in enumerate(ir.get("components", [])):
        if model.kind_of(comp) != "multi":
            continue
        for pin in (model.pin_positions(comp) or {}):
            ref = "%s.%s" % (comp["id"], pin)
            if ref not in connected:
                findings.append({
                    "code": "E900", "severity": "E",
                    "path": "/components/%d/pins" % ci,
                    "rule": "铁律五·引脚未接", "pin": ref,
                    "message": "引脚 %s 未被任何 wire 显式引用" % ref,
                    "hint": "在 wires[].points 中加入 {\"pin\":\"%s\"}" % ref,
                })
    for finding in validated.report.findings:
        item = dict(finding)
        if item["code"] == "E004":
            item["rule"] = "铁律一·斜线"
        else:
            item.setdefault("rule", "IR geometry")
        findings.append(item)
    n_E = sum(1 for f in findings if f["severity"] == "E")
    n_W = sum(1 for f in findings if f["severity"] == "W")
    return {
        'file': file_name,
        'status': 'error' if n_E else ('warn' if n_W else 'ok'),
        'errors': n_E, 'warnings': n_W,
        'rules_hit': sorted({f.get('rule', '') for f in findings if f.get('rule')}),
        'findings': findings,
        'iron_rules_version': '1.1 (IR-driven connectivity)',
    }


# ──── layout check entry point ────

def layout_check(tex_path, output_json=False):
    """对 circuit.tex 执行全部布局铁律检测，返回 findings 列表。"""
    with open(tex_path, "r", encoding="utf-8") as f:
        tex_content = f.read()

    resolver = TexResolver(tex_content)
    wire_paths = parse_tex_wires(tex_content)
    sources = parse_tex_current_sources(tex_content)

    all_findings = []
    all_findings.extend(check_orthogonality(wire_paths, resolver))
    all_findings.extend(check_backtrack(wire_paths, resolver))
    all_findings.extend(check_midpoint(wire_paths, resolver, sources, resolver.comps))
    all_findings.extend(check_pin_connectivity(wire_paths, resolver, resolver.comps))

    # 与主校验器统一为 {code,severity,path,message,hint}；保留 rule 等诊断扩展字段。
    for i, finding in enumerate(all_findings):
        finding.setdefault('code', 'E900' if finding.get('severity') == 'E' else 'W900')
        finding.setdefault('path', '/tex/layout/%d' % i)

    # Summary
    n_E = sum(1 for f in all_findings if f['severity'] == 'E')
    n_W = sum(1 for f in all_findings if f['severity'] == 'W')
    rules_hit = set(f['rule'] for f in all_findings)

    print(f"\n=== 布局检查: {Path(tex_path).name} ===")
    print(f"  Errors: {n_E}, Warnings: {n_W}")
    print(f"  触犯铁律: {rules_hit if rules_hit else '无'}")

    if not all_findings:
        print("  [OK] 全部铁律通过！")
    else:
        for f in all_findings:
            sev = f['severity']
            print(f"  [{sev}] [{f['rule']}] {f.get('message', '')[:120]}")
            print(f"       hint: {f.get('hint', '')[:120]}")

    if output_json:
        report_path = Path(tex_path).with_suffix('.layout_report.json')
        report = {
            'file': str(tex_path),
            'status': 'error' if n_E > 0 else ('warn' if n_W > 0 else 'ok'),
            'errors': n_E,
            'warnings': n_W,
            'rules_hit': sorted(rules_hit),
            'findings': all_findings,
            'iron_rules_version': '1.0 (2026-07-12, out/circuit2 四轮实战)',
        }
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n  报告已保存: {report_path}")

    return all_findings


# ════════════════════════ main ═════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="IR JSON 自动修复 + 序列化渲染 + 布局检测")
    parser.add_argument("input_file", help="IR JSON 或 circuit.tex 文件路径")
    parser.add_argument("-o", "--outdir", default=None,
                        help="输出目录（默认与输入同目录）")
    parser.add_argument("--dpi", type=int, default=300,
                        help="渲染 DPI（默认 300）")
    parser.add_argument("--max-rounds", type=int, default=3,
                        help="最大修复轮数（默认 3）")
    parser.add_argument("--layout-check", action="store_true",
                        help="执行线条布局铁律检测（输入 .tex 文件）")
    parser.add_argument("--json", action="store_true",
                        help="布局检查输出 JSON 报告")
    args = parser.parse_args()

    in_path = Path(args.input_file).resolve()
    if not in_path.exists():
        print(f"ERROR: 文件不存在: {in_path}")
        sys.exit(3)

    # ── layout-check mode ──
    if args.layout_check:
        if in_path.suffix == '.json':
            findings = layout_check_ir(in_path, output_json=args.json)
        elif in_path.suffix == '.tex':
            findings = layout_check(in_path, output_json=args.json)
        else:
            print("ERROR: --layout-check 需要 .tex 或 .json 文件")
            sys.exit(3)
        n_E = sum(1 for f in findings if f['severity'] == 'E')
        sys.exit(irlib.EXIT_ERROR if n_E > 0 else irlib.EXIT_OK)

    # ── IR fix mode ──
    if in_path.suffix not in ('.json',):
        print("ERROR: IR 修复模式需要 .json 文件（或使用 --layout-check 对 .tex 检查）")
        sys.exit(3)

    outdir = Path(args.outdir) if args.outdir else in_path.parent
    outdir.mkdir(parents=True, exist_ok=True)

    with open(in_path, "r", encoding="utf-8") as f:
        ir_data = json.load(f)

    print(f"=== IR 修复与渲染: {in_path.name} ===")
    print(f"    输出目录: {outdir}")

    for round_num in range(1, args.max_rounds + 1):
        print(f"\n--- Round {round_num}: 验证 ---")
        findings = validate(in_path)
        auto_fixable, needs_human = classify_findings(findings)
        n_err = len([f for f in findings if f["severity"] == "E"])
        n_warn = len([f for f in findings if f["severity"] == "W"])
        print(f"  Errors: {n_err}, Warnings: {n_warn}")
        print(f"  可自动修复: {len(auto_fixable)}, 需人工: {len(needs_human)}")

        if n_err == 0:
            print("  [OK] 无错误，进入序列化")
            break
        if not auto_fixable:
            print("  [ERR] 无可自动修复的错误，需人工处理：")
            for f in needs_human:
                print(f"    [{f['code']}] {f['message'][:100]}")
                print(f"         hint: {f.get('hint', 'N/A')[:100]}")
            sys.exit(1)

        print(f"\n--- Round {round_num}: 修复 ---")
        fixed = fix_e008(ir_data, auto_fixable)
        if fixed > 0:
            with open(in_path, "w", encoding="utf-8") as f:
                json.dump(ir_data, f, indent=2, ensure_ascii=False)
            print(f"  [OK] 共修复 {fixed} 处")

    findings = validate(in_path)
    n_err = len([f for f in findings if f["severity"] == "E"])
    if n_err > 0:
        print(f"\n[ERR] 仍有 {n_err} 个错误，需人工处理")
        for f in findings:
            if f["severity"] == "E":
                print(f"  [{f['code']}] {f['message'][:120]}")
        sys.exit(1)

    # serialize
    print(f"\n--- 序列化 ---")
    tex_name = in_path.stem + ".tex" if in_path.suffix == ".json" else in_path.name + ".tex"
    tex_path = outdir / tex_name
    if not serialize(in_path, tex_path):
        sys.exit(2)

    debug_name = in_path.stem + ".debug.tex"
    debug_tex = outdir / debug_name
    debug_png = outdir / debug_name.replace(".tex", ".png")

    # render
    print(f"\n--- 渲染 ---")
    png_path = outdir / tex_name.replace(".tex", ".png")
    if not render(tex_path, png_path, args.dpi):
        sys.exit(2)
    if debug_tex.exists():
        render(debug_tex, debug_png, args.dpi)

    # [NEW] auto-run layout check on the output tex
    print(f"\n--- 布局铁律检查（自动） ---")
    layout_findings = layout_check(tex_path, output_json=True)
    n_layout_err = sum(1 for f in layout_findings if f['severity'] == 'E')

    print(f"\n=== 完成 ===")
    print(f"  TikZ: {tex_path}")
    print(f"  渲染: {png_path}")
    print(f"  调试: {debug_png}")
    if n_layout_err > 0:
        print(f"  ⚠ 布局铁律发现 {n_layout_err} 个错误，请查看 layout_report.json")
        return irlib.EXIT_ERROR
    return irlib.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
