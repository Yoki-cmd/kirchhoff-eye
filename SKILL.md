---
name: kirchhoff-eye
description: "Use for IR-driven circuit drawing tasks: redraw a printed/software-exported schematic, draw from a description or netlist, edit/review/repair an IR, or render deterministic circuitikz. Every route converges on canonical JSON IR. Do not claim autonomous arbitrary image/prose/netlist-to-IR recognition."
metadata:
  version: 0.3.0
---

# Kirchhoff-eye：AI 辅助电路图重画 → circuitikz

**心法**：电路图 = 带几何布局的图（graph）。你的任务不是"画一张像的图"，而是从有损渲染
反解出"网表+布局"（ir.json，唯一真相源），再机械重表达。全链路只有两处需要动脑：
**①看图填 IR（§3–§4）②看对比图出差异清单（§5）**——其余全部交给确定性工具。
质量由回路收敛保证，不靠一次看对。这里的布局保真是**语义/构图保真**：保留相对方位、
分组、母线、主路由、重要转角与标签归属；允许为清晰度调整尺寸、间距、画布和次要对齐。
精确像素重合、线长和符号尺寸不是默认验收目标，除非用户明确要求摹图。

**能力边界**：公开仓库提供确定性的 IR 校验、序列化、渲染、对比和布局检查后端；
图片理解仍由 AI/人工审阅完成，不得宣称已提供任意电路图的全自动 image-to-IR 识别器。
自然语言和 netlist 入口同样是 **Agent 先产出/审阅 IR，再交给确定性后端**，不是内置的自动转换器。

规范文件（先读再干活）：
- `references/ir-schema.md` — IR 语义正本 + 字段检查清单（§10）
- `references/circuitikz-style.md` — 序列化规范（工具已实现，人只需懂约定）
- `references/perception-roadmap.md` — 未来独立图像感知的窄范围、证据架构、模型使用和状态边界
- `templates/anchors.json` — 多端件引脚偏移实测表
- `SKILL-ir-fix.md` — **线条布局铁律**（斜线/折返/中点/级联，6 条铁律 + 验证五步法）


## 1. 工具 CLI（确定性，全在 scripts/）

统一使用项目虚拟环境中的 Python 3.9+。首次使用先安装：

```bash
python -m pip install -e ".[dev]"
kirchhoff-eye --help
```

v0.3 已提供稳定顶层 CLI、显式审阅状态机和统一任务路由；现有 `scripts/` 命令继续作为
向后兼容入口。若当前解释器缺少依赖，应切换虚拟环境，不把个人机器路径写入仓库。

| 命令 | 作用 |
|---|---|
| `kirchhoff-eye build ir.json [--source source.png] --out out/job [--dpi 300]` | 生产编排；无 source 得 `valid`，有 source 开启 `needs_review` 第 1 轮 |
| `kirchhoff-eye review out/job round-review.json` | 写入逐区结论和结构化差异；每个 IR region 必须恰有一条结论 |
| `kirchhoff-eye repair out/job repaired.ir.json --patches patches.json` | 校验 Agent 已修改的 IR，记录本轮 ≤5 个 patch，并开启下一轮 |
| `kirchhoff-eye approve out/job [--note ...]` | 仅在逐区审读完整且差异为空时显式批准 |
| `kirchhoff-eye task <route> ...` | 统一路由：redraw-image / draw-from-description / draw-from-netlist / edit-ir / review / repair / render / approve |
| `kirchhoff-eye labels apply ir.json positions.json -o labelled.ir.json` | 批量应用人工确认的 `元件ID -> [x,y]` 编号坐标；`null` 保持当前位置 |
| `kirchhoff-eye doctor [--json]` | 检查 Python、打包资源、TeX 引擎、`pdftoppm`、真实 circuitikz 编译和可写输出目录 |
| `python scripts/validate_ir.py ir.json [--phase skeleton\|geometry\|full] [--json]` | 校验（0 干净/1 仅警告/2 有错/3 环境错） |
| `python scripts/ir2tikz.py ir.json -o circuit.tex` | IR→tex（内嵌 full 校验门禁；每次自动另出 `circuit.debug.tex` 网格+ID 版） |
| `python scripts/render.py circuit.tex -o circuit.png [--dpi 300]` | tex→png；若同目录存在 `circuit.debug.tex`，自动同时生成 `circuit.debug.png` |
| `python scripts/compare.py 原图.png 渲染.png -o cmp.png [--mode side\|overlay\|both]` | 并排对比图 |
| `python scripts/crop.py 图.png -o 局部.png --rect x0,y0,x1,y1 [--scale 2] [--ruler]` | 像素放大取证 |
| `python scripts/ir_fix_and_render.py circuit.tex --layout-check [--json]` | **布局铁律检测**（斜线/折返/中点/引脚，详见 SKILL-ir-fix.md） |
| `python scripts/score_ir.py truth.json candidate.json --json` | 语义重画评分：拓扑/方向硬门禁 + 平移缩放不变的构图软评分 |
| `python scripts/generate_synthetic_fixture.py --out tests/fixtures --dpi 72` | 从公开 IR 确定性生成 20 组 synthetic IR/图片基准（不使用私有扫描图） |


**失败重试协议**：任何工具 exit 2 → 读报告逐条修 ir.json 后重跑；同一错误码连续 3 次
不消 → 停下，写入遗留问题交人工。报告里每条 finding 的 `hint` 就是修复指引，照做。

每次任务建工作目录 `out/<job名>/`，产物全放里面。

## 2. 预检与简繁判定

1. 环境自检：`pdflatex`/`pdftoppm` 可用；任一工具 `--help` 能跑通。
2. 通看整幅原图，**只数不记**：元件总数、多端件（三极管/MOS/运放/变压器/spdt）数、
   独立文字数、是否多子图。
3. **简单路径条件（须全部满足）**：元件 ≤15 且多端件 ≤2 且无多子图且图像清晰
   （短边 ≥600px）。满足走 §3，否则走 §4。

**坐标换算法**（两条路都要）：取图中最常见的水平两端元件，规定其跨度 = 2.0 网格，
建立 像素/网格 比例尺；**像素 y 向下、IR y 向上，录入必须翻转**；主干和元件中心通常
吸附 0.5，但离网 pin 的正交接入点可以离网（默认只报 W）。样式判定：电阻是锯齿 →
`flavor:"american"`；矩形框（国标）→ `"european"`。

## 3. 简单路径（聪明活 ①，可独立引用）

对照 `references/ir-schema.md` §10 的字段检查清单**一次写全** ir.json →
`validate_ir.py --phase full` → 按 hint 修到 exit ≤1 → 进 §5 回路。

写 IR 时的铁规矩：
- 每个可见符号 ↔ components 恰一条；词表外符号**禁止就近顶替**，建 unknowns 条目
  （UNKNOWN 协议，ir-schema.md §8）。
- **先写 nets**（拓扑意图），再录几何——E007 双通道校验靠它抓你自己的幻觉。
- 需要稳定命名的汇合点可写顶层 `nodes:[{name,at}]`，wire 用 `{"node":"N_x"}` 引用；
  后续移动 node.at 不需要改每条 wire 的 endpoint。
- 极性类元件（二极管/电源/电解电容）对照 ir-schema.md §3.5 表定 from/to 方向。
- **电容分有极/无极**：见到一直一弯极板（弯板=−）或大 μF（电解，≥~1μF 如 470μF）→ 用
  `polar_capacitor`（直板端为 +），**不是** `capacitor`；类型看错整只元件 F1 不匹配。拿不准
  就 `crop.py` 放大看极板弯不弯。
- 多端件先看引脚朝向定 (rotate, mirror)，`pins[].at` 填观测像素换算值（W103 会帮你
  核对位姿有没有看错）。
- **多端件引脚天生离网**（opamp、transformer、spdt 等）：`pins[].at` 照填观测值；连接它的
  wire 必须在 pin 前显式加入一个或多个 **L 形 waypoint**，使每一段严格水平或竖直。短桩
  waypoint 可使用 pin 的离网 x/y；默认 `routing.grid_snap=warn` 时只报布局建议，绝不允许
  用“近似正交”斜线直连。
- 走线转角逐点录 waypoints；原图实心点 → junctions；四路十字必须声明连/不连。
- **一条干线（母线/地轨）抽头接多个元件引脚时，每个抽头点必须打断成显式顶点**（该点即
  junction）：引脚只在 wire 顶点处连通，压在线段中段=E014 悬空、net 几何分裂（E007）。
- 图上每段文字三选一归属：元件 label/value（定 side）/ 独立 texts / 端口标号。
- 电流方向、电压测量、节点极性等物理量优先写 `annotations[]`：语义归属用 `target` 或
  `positive_ref/negative_ref`，视觉位置用 `marker_at/label_at`；不得从元件类型静默猜物理量。
- **编号位置默认交给人类定稿**：每次渲染都必须同时生成 `circuit.debug.png`。用户查看网格后给出
  `元件ID -> [x,y]`；把坐标写入该元件的 `label_at`，不要继续让模型反复猜 `label_side/gap`。
  `label_at` 是编号的绝对网格坐标，优先级高于 `label_side/label_gap`。

## 4. 复杂路径：四遍扫描（聪明活 ①，可独立引用）

每遍产出后跑对应档位 validate；**自检问题必须逐条回答，不许跳**——跳步是首要失败模式。

| 遍 | 动作 | 产出 | validate |
|---|---|---|---|
| 1 全局清单 | 蛇形通看清点 | components 骨架（id/type/大致 at）、regions、unknowns 候选、terminals | `--phase skeleton` |
| 2 分区细扫 | 每 region 用 crop.py 放大 | 精化 from/to 或 at/rotate/mirror、pins[].at 观测值 | 每区 `--phase geometry` |
| 3 连线核对 | **先写 nets 拓扑意图**，再对每个交点 crop 放大录几何 | nets、wires、junctions、crossings、pins[].net | `--phase full`，清 E007/E008 |
| 4 文字归属 | 逐条三选一 | label/value/*_side、texts | 终跑 `--phase full` |

**遍 1 强制自检（逐条作答）**：计数与预检一致吗？每个符号都有 id 或 unknown 条目吗？
**遍 2 强制自检**：每个多端件都是先看引脚朝向再定位姿的吗？pins[].at 都填了吗？
**遍 3 强制自检**：把每个 T 型/十字交点**逐个列坐标**并写连/不连判定，一个不许漏。
**遍 4 强制自检**：哪个元件还没有 label/value？对照原图确认它确实没有。

## 5. 迭代回路（聪明活 ②，可独立引用）

单轮流程：

```
python scripts/ir2tikz.py ir.json -o circuit.tex
python scripts/render.py circuit.tex -o circuit.png
python scripts/compare.py source.png circuit.png -o cmp_round<N>.png
```

**审读协议**：打开 cmp_round<N>.png，按 region 逐区对照，每区要么列出差异、要么明确
写"该区无差异"——不许整图扫一眼了事。可疑处用 crop.py 对两侧同位置取证后再下结论。

**编号坐标反馈协议**：同时把 `circuit.debug.png` 交给用户。图中的红色十字是元件内部锚点，
用于区别锚点坐标和文字外框。用户按网格返回，例如：
`T2(Q2) -> [4.8, 3.4]`。将其写为 `components[Q2].label_at:[4.8,3.4]` 后重出图。
编号位置不再要求机器自动验收；机器只保证坐标被精确序列化、debug 网格图始终生成。
多个坐标优先写入 positions JSON 并用 `kirchhoff-eye labels apply` 批量应用；未知 ID 必须报错，
`null` 表示保持当前自动或人工位置，重复应用必须产出逐字节一致的 IR。

**布局铁律检查**（每轮必须执行，详见 `SKILL-ir-fix.md`）：
```
python scripts/ir_fix_and_render.py circuit.tex --layout-check --json
```
检测六条铁律：斜线（铁律一）、水平/竖直折返（铁律二）、电流源中点（铁律三）、
引脚漏接（铁律五）。发现 E 级违规必须在本轮修复，不允许带到下一轮。

**差异清单固定表**（templates/diff_table.md）：

```
| # | 位置(网格坐标+原图rect) | 类别 | 描述 | patch操作 | IR path |
```

修复优先级（先拓扑后外观）：**错连 > 缺件/多件 > 错型 > 错位 > 错标签 > 错样式**。

**patch 最小操作集**：ADD/REMOVE_COMPONENT, CHANGE_TYPE, MOVE, ROTATE, MIRROR,
SET_VALUE/LABEL/LABEL_SIDE, REWIRE, ADD/REMOVE_WIRE, SET_WAYPOINTS,
ADD/REMOVE_JUNCTION, ADD_CROSSING, MOVE_TEXT, SET_REGION。
每轮只执行优先级最高的 **≤5 条**（小步防震荡），改完 validate 再进下一轮。

**收敛与止损**（config.json `max_rounds`，默认 3）：
- 状态语义：`valid`=IR 与产物有效；`needs_review`=待逐区审读或待显式批准；
  `needs_human`=明确 blocker（如 W108 unknown）、收敛止损或轮次上限；普通 W 级布局/画布建议
  只保留在 validation/layout 报告，不阻塞批准；`approved`=零差异审读后显式批准。
- 收敛成功 = 某轮差异清单为空 **且** 逐区确认语句齐全 → `needs_review + ready_for_approval`；
  再执行 `approve` 才成为 `approved`。
- 已审读轮次不可覆盖；若审读有差异，只能通过 repair 开启下一轮。
- patch 必须引用当前差异的 `difference_id`，且 operation / IR path 必须与差异一致；每个
  difference 每轮只能引用一次。字段类操作使用精确 leaf path（如 `SET_VALUE -> /components/1/value`、
  `SET_WAYPOINTS -> /wires/0/points`），增删操作使用集合索引 path。候选 IR 必须产生对应实际变化，
  未声明变化、无变化和不存在路径一律拒绝。状态保存前记录前后 SHA-256。
- 连续 2 轮差异条数不降 → 生产状态机转 `needs_human` 并禁止继续 repair；同一 IR path
  被 patch ≥3 次 → 冻结任务并禁止继续 repair。
- 到上限仍有差异，或 unknowns 非空 → 状态 `needs_human`，交付物附遗留差异清单
  （每条带取证图路径）。**绝不为了收敛而删掉看得见的差异。**

## 6. 交付与轮次历史

工作目录 `out/<job>/` 交付：
1. `circuit.tex` — 带分区块注释的 circuitikz 代码
2. `circuit.png` — 渲染图
3. `circuit.debug.png` — 网格+元件 ID 版（用户指着说话用）
4. `circuit.ir.json` — canonical truth source
5. `review.json` — 状态、轮次、逐区差异、patch 记录、批准状态
6. `cmp_round<N>.png` + `rounds/round-<NN>/` — 每轮不可变对比与快照
7. `DELIVERY.md` + `FEEDBACK.md` — 完整交付报告和反馈话术

## 7. 用户反馈处理

**人的反馈永远落到 ir.json 再重序列化，绝不手改 tex。**
用户话术 → patch 操作对照表见 `templates/FEEDBACK.md`（随每次交付附带）。
改完 IR 后写 `patches.json`，执行 `repair`；最新产物覆盖顶层，但历史轮次保留在 `rounds/`。

## 8. v1 边界（遇到就明说，别硬画）

手绘/拍照图；电气控制原理图（继电器-接触器）；数字逻辑门；电位器滑臂接线；
垂直跳线。处理方式：能局部退化就 UNKNOWN 协议 + `needs_human`，整图超界就直接
告知用户这是 v2 范围。
