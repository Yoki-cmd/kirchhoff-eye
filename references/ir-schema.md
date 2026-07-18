# kirchhoff-ir/1.0 — IR 语义正本

> 结构合法性以 `schemas/ir.schema.json` 为准（E001）；本文档定义 schema 表达不了的**语义**规则
> （连接判定、极性约定、位姿公式、消歧铁律），由 `validate_ir.py` 机器执行（E002+/W101+）。
> IR 是唯一真相源：TikZ 永远是生成物，人的反馈也是改 IR 再重序列化。

## 1. 坐标系约定

| 项 | 约定 |
|---|---|
| 单位 | 1 网格单位 = 1 cm（TikZ 坐标直接等于网格数） |
| 吸附 | `routing.grid_snap` 控制网格检查：`strict`=E003、`warn`=E003/W、`off`=不检查；缺省 `warn` |
| 吸附豁免 | `texts[].at` 与 `pins[].at`（观测冗余）**不受** 0.5 吸附约束；就近取 0.5 倍数即可 |
| 原点/方向 | 左下角附近、坐标非负；**y 向上为正**（与图片像素相反，录入必须翻转 y） |
| 画布 | ≤ 30×20（超限 W105，非硬错） |
| 两端件跨度 | 推荐 2.0，最小 1.0（<1.0 报 E005） |

**像素→网格换算法**：取图中最常见的水平两端元件规定跨度=2.0，建立像素/网格比例尺；
像素 y 向下、IR y 向上；主干通常就近吸附 0.5，离网 pin 的正交短桩可保留真实坐标。

元件编号位置可用 `label_at:[x,y]` 由用户按 debug 网格直接指定。存在 `label_at` 时，序列化器
忽略 `label_side/label_gap` 的自动位置，按该绝对网格坐标放置编号。每次正常序列化都会同时
生成 `.debug.tex`；其中每个元件内部锚点用红色十字标出，避免把锚点坐标和文字外框混淆。
渲染为 `.debug.png` 后，用户可把多个 `元件ID -> [x,y]` 写入 positions JSON，并执行：

```bash
kirchhoff-eye labels apply circuit.ir.json positions.json -o circuit.labelled.ir.json
```

positions JSON 由 `schemas/label-positions.schema.json` 约束；`null` 表示保持当前自动或人工位置
不变，未知元件 ID、`NaN` 与无穷坐标为错误。应用结果确定且幂等。

## 2. 顶层结构

`version, meta, style, routing(可选), nodes(可选), components, wires, junctions, crossings, terminals, texts, annotations(可选), regions, nets(可选), unknowns`

除 `nets`、`routing`、`nodes`、`annotations` 外全部**必填**——没有内容也要写空数组 `[]`。
`annotations` 是 v0.2 的可选增量字段；其余必填空数组继续强迫感知端对“这张图没有
junction/crossing/unknown”做显式断言，而不是漏写。

- `style.flavor`：`american`（默认，模电教材西式画法）或 `european`（GB/T 4728 国标画法，
  电阻为矩形框）。整图统一，不支持混合。
- `nets`：感知端在录几何**之前**先声明的拓扑意图清单。E007 把"声明拓扑"与"几何推导拓扑"
  互相质检——这是防拓扑幻觉的主通道，强烈建议复杂图必写。
- `routing` 缺省等价于 `{"orthogonal":"strict","grid_snap":"warn","grid_step":0.5}`。
  `orthogonal` 在 v1 恒为 `strict`；网格策略无论取何值都不得放宽 E004。
- `nodes`：可选稳定电气节点表 `[{"name":"N_B","at":[4.15,4.35]}]`。wire point 可用
  `{"node":"N_B"}` 显式引用；未知引用报 E002。node 是拓扑身份，`at` 是其当前视觉位置。

## 3. 元件（components）

### 3.1 两端元件（to-path 类）

```json
{"id":"R1","type":"resistor","from":[1,4],"to":[3,4],
 "pins":[{"name":"1","net":"N_IN"},{"name":"2","net":"N_B"}],
 "label":"R_1","value":"10\\mathrm{k}\\Omega","label_side":"above","value_side":"below"}
```

- **pin "1" 恒在 from 端，pin "2" 恒在 to 端**。
- from/to 必须水平或垂直（斜放需 `flags:["allow_diagonal"]` 豁免，否则 E004 同族检查拒绝）。
- `label` = 元件符号名（如 `R_1`），`value` = 数值（如 `10\mathrm{k}\Omega`）；两者都是
  **不带 `$` 的受限 TeX 数学内容**。只允许普通文字、上下标及校验器白名单中的数学命令；
  `\input`、`\write`、`\typeout` 等可执行命令会报 E016。归属元件的值/标签**禁止**放 texts。
- `label_side`/`value_side` ∈ above/below/left/right：标签相对元件的位置（以原图为准）。
  水平元件用 above/below，垂直元件用 left/right；同侧同用会重叠（风格文档有映射表）。

### 3.1a v1.1 可选字段（三类元件通用规则）

全部**可选，缺省 ⇒ 与 v1.0 输出逐字节相同**（纯增量，`version` 常量不变）。新文档使用
这些字段时应在顶层 `extensions` 声明对应能力；旧文档为兼容可省略：

- `scale`：数值 ∈ [0.5, 2.0] 且 0.25 步进（`multipleOf`，二进制精确）。语义 = 符号整体
  均匀缩放。两端件序列化为 per-instance `/tikz/circuitikz/bipoles/length=基数×scale`
  （基数=config `style.ctikzset` 里的 `bipoles/length`），引脚(from/to)不动、引线自动
  补齐；多端/单端件序列化为 node 选项 `scale=k`，**引脚锚点随之精确 ×k**（实测锁定），
  位姿公式变为 `pin = at + M^mirror · R(rotate) · (offset × scale)`。
  两端件若 `2×scale > 跨度`（符号体伸出引脚）报 **W109** 警告。
- `label_gap`：数值 ∈ [0, 2.0]，世界单位（=cm）。标签到符号的间距；多端件缺省 0.2、
  单端件缺省 0.5（即既有常量）；两端件设置时 label 从 `l=` 选项改为独立
  `\node[anchor=side反向]`，置于中点 + side 法向 × gap；缺省时保持 `l=` 写法不变。
  范围上限兼作安全阀（防 `bipoles/length=99999cm` 式尺寸注入）。
- `value_gap`：仅两端件，同 `label_gap` 的规则作用于 `value`（`a=` ↔ 独立节点）。

### 3.2 多端元件（node 类）

```json
{"id":"Q1","type":"npn","at":[5,4],"rotate":0,"mirror":false,
 "pins":[{"name":"B","net":"N_B","at":[4.3,4]},
         {"name":"C","net":"N_C","at":[5,4.7]},
         {"name":"E","net":"GND","at":[5,3.3]}],
 "label":"Q_1","label_side":"right"}
```

- **位姿是真相源**：引脚实际位置由 `(at, mirror, rotate)` + `templates/anchors.json`
  唯一决定。实测公式（circuitikz 1.8.5，probe07 机读锁定）：

  ```
  pin_pos = at + M^mirror · R(rotate) · offset
  ```

  其中 `offset` 查 anchors.json；`R(rotate)` 为逆时针旋转；`M` 为水平镜像（x→−x）。
  **注意合成顺序：offset 先被旋转、再被镜像**——与固定序列化写法
  `[xscale=-1, rotate=θ]` 的 TikZ 实际行为逐点核对一致。
  v1.1 带 `scale` 时 offset 先 ×scale 再进公式（均匀缩放与旋转/镜像可交换，见 §3.1a）。
- `pins[].at` 是**可选观测冗余**：感知端把原图里看到的引脚位置填进来；validate 会用
  位姿公式反推核对，偏差 >0.5 报 W103——这是"位姿看错"的自动探测器。强烈建议多端件必填。
- `rotate ∈ {0,90,180,270}`，`mirror ∈ {true,false}`。
- `variant`：型别内变体。v1 词表：`opamp` 可取 `"noinv_up"`（同相端在上）；
  `transformer` 可取 `"core"`（带铁芯）。其余类型不允许 variant（E006）。

### 3.3 单端元件

`ground` / `vcc` / `vee`，`pins` 恒一个 `{"name":"p","net":...}`；`at` 即接线点：
ground/vee 符号画在接线点下方，vcc 画在上方（circuitikz 原生行为）。

### 3.4 v1 类型词表

| 类 | type（IR） | 说明 |
|---|---|---|
| 两端 | resistor, potentiometer, capacitor, polar_capacitor, inductor, diode, zener, led, battery, vsource, isource, cvsource, cisource, switch_spst, ammeter, voltmeter | potentiometer 的**滑臂 v1 不可接线**（见 §9 边界） |
| 多端 | npn, pnp (B,C,E)；nmos, pmos (G,D,S)；opamp (inp,inn,out)；transformer (A1,A2,B1,B2)；spdt (in,out1,out2) | 引脚名固定，缺/多/错名报 E006 |
| 单端 | ground, vcc, vee | pin 名恒 "p" |

推荐 id 前缀：R/RP/C/L/D/V/I/SW/AM/VM（两端）、Q/M/OA/T/SW（多端）、GND/VCC/VEE（单端）、
W（wire）、UNK（unknown）。schema 只强制 `^[A-Z]{1,3}[0-9]+$`。

### 3.5 极性约定（Phase 0 实测锁定，probe03/03b/03c）

| type | IR 约定 | circuitikz 原生 | 序列化处理 |
|---|---|---|---|
| diode / zener / led | **from=阳极 → to=阴极** | 阳极在 from ✓ | 原样 |
| vsource / cvsource | **from=负 → to=正** | + 在 from ✗ | 加 `invert` |
| battery | **from=负 → to=正** | 长板(+)在 from ✗（像素机读） | 加 `invert` |
| isource / cisource | **电流箭头 from → to** | 箭头 from→to ✓ | 原样 |
| polar_capacitor | **from=正(直板) → to=负(弯板)** | 直板在 from ✓ | 原样 |

感知端录入口诀：看图定"哪端是阳极/+/箭头来向"，再按上表定 from/to 方向。

## 4. 导线（wires）

```json
{"id":"W1","points":[{"xy":[0,4]},{"xy":[2,4]},{"pin":"R1.1"}]}
```

- 点是 `{"xy":[x,y]}`、`{"pin":"R1.2"}` 或 `{"node":"N_B"}`。pin/node 是显式
  拓扑引用，xy 和 node.at 提供视觉几何；校验报告应优先说明 explicit / geometric 证据来源。
- **相邻点必须正交**（水平或垂直对齐，E004）。
- **离网 pin 接入**：若普通点与 `{"pin":"Q1.C"}` 不共 x/y，必须插入 L 形 waypoint，例如
  `[{"xy":[5,5]},{"xy":[5,4.55]},{"pin":"Q1.C"}]`。waypoint 可离开 0.5 网格；先忠实
  原图短桩方向，再避免符号和标注碰撞。任何 `dx!=0 且 dy!=0` 的近似正交线仍报 E004。
- **waypoints 显式携带原图转角**：原图先下后右，points 就写三个点。序列化端逐点 `--` 展开，
  **不做任何自动折线/自动布局**——这是布局保真的落点。
- **连接唯一语义**：电气连接只发生在"顶点重合"处（wire 端点/中间顶点、pin 位置、junction、
  terminal 坐标完全相等）。wire 中段**穿过**别人不算连接；中段恰好穿过其他 pin/顶点
  是模糊连接，报 E014（要求加顶点或错开）。

## 5. junction / crossing 消歧铁律

- **T 型交点（3 路）默认连通**；原图有实心点就录 `junctions:[{"at":[x,y]}]`（渲染保真），
  没点就不录（拓扑不变）。
- **四路十字必须显式声明**：`junction`（连）或 `crossing`（不连），二者皆无 → E008。
- junction/crossing 必须落在相关 wire 的顶点/线段上（E013）。
- crossing `style`:
  - `plain`：直接画过（序列化不产生任何标记，两线裸交叉）；
  - `jump`：半圆跳线。**v1 限水平线跳**（circuitikz `jump crossing` 原生：水平线拱起、
    垂直线连续）；原图是垂直线跳的记 plain + 遗留问题。

## 6. terminals / texts / regions

- `terminals`：端口圈。`style` ∈ `ocirc`（空心，常规端口）/ `circ`（实心）；`label` 为端口
  标号（如 `a`、`+`）。terminal 的 at 必须与某 wire 端点重合（悬空 pin + terminal 不报 W101）。
- `texts.kind` ∈ `annotation`（旁注，如 u_i 波形说明）| `port_label`（端口旁文字）|
  `net_label`（净名标注）。**归属元件的值/标签禁止放 texts**（必须进元件字段）——validate
  查不出来，但审读回路会当差异修掉。texts 允许中文（render 自动切 lualatex）。
- `regions` 以 `component_ids` 为准，供 ir2tikz 分区块注释与分区审读；未覆盖全部元件报 W107。

## 6.1 一等物理标注 `annotations`

`annotations` 是可选增量字段；省略或 `[]` 时与旧 IR 输出兼容。它表达“标注是什么、归属谁、
画在哪里”，不从元件类型或附近文字静默推断物理语义。每项 `id` 使用 `A1/A2/...`，在
`annotations` 数组内唯一；引用不存在、重复 id、无效电流目标或相同电压正负参考报 **E015**。

支持的 kind：

| kind | 核心字段 | 语义 |
|---|---|---|
| `component_id` | `target.component`, `label_at`, 可选 `label` | 元件编号；无 label 时取元件 label |
| `component_value` | `target.component`, `label_at`, 可选 `label` | 元件值；无 label 时取元件 value |
| `port_label` | `target.wire/net/node`, `label`, `label_at` | 端口文字及语义归属 |
| `rail_label` | `target.net/node`, `label`, `label_at` | 电源轨/网络文字 |
| `current_direction` | `target.component/wire`, `direction`, `marker_at` | 外部电流箭头；label 可独立放在 `label_at` |
| `voltage_measurement` | `positive_ref`, `negative_ref`, `label`, `label_at` | 带显式正负参考的电压量 |
| `node_polarity` | `target.net/node`, `polarity`, `marker_at` | 单个节点的 `+`/`-` 标记 |
| `free_text` | `label`, `label_at` | 无电气归属的自由文字 |

外部电流箭头示例：

```json
{"id":"A1","kind":"current_direction","target":{"wire":"W3"},
 "direction":"down","marker_at":[2.15,6.8],"label":"i_o","label_at":[1.8,7.2]}
```

`marker_at` 是箭头中心，不要求压在导线上；这允许箭头放在电流源符号及对应物理量文字旁边，
同时由 `target` 保留电气归属。序列化器不得把外部箭头强行移入电流源圆圈。

电压测量示例：

```json
{"id":"A2","kind":"voltage_measurement","label":"v_o",
 "positive_ref":{"net":"N_OUT","marker_at":[12,5]},
 "negative_ref":{"net":"GND","marker_at":[12,1.5]},"label_at":[12,3]}
```

`marker_at` 是视觉标记坐标，`net/node` 是语义引用；二者职责分离。正负引用必须不同。
旧 `texts[]`、元件 `label/value` 与 `arrows[]` 在迁移期继续支持。

## 7. nets 与 E007 双通道校验

几何通道：对全图做 union-find——顶点重合连通、T 型自动连通、四路十字按声明；
**同类单端件视为经隐式电源轨相连**（图上两个接地符号即同一 GND 网，无需画线，
vcc/vee 同理——这正是电源符号的语义）。
声明通道：每个 pin 的 `net` 字段 + `nets` 清单。
E007 = 两通道不一致（同一几何连通分量里出现两个 net 名 / 同一 net 名跨两个分量），
报告双侧证据（哪些 pin、哪条 wire、哪个坐标）。

## 8. UNKNOWN 协议

词表外符号**禁止就近顶替**。必须建 unknowns 条目：

```json
{"id":"UNK1","at":[6,4],"size":[1.5,1],"rect_px":[512,240,700,360],
 "pin_count":2,"pins":[{"name":"1","net":"N_X"},{"name":"2","net":"GND"}],
 "appearance":"圆圈内一横一竖交叠，像某种表头","guess":"功率表?"}
```

- `at`/`size` 为网格上的占位框中心与宽高（吸附 0.5）；`rect_px` 是原图像素框（取证用）。
- 序列化为虚线占位框 + id 标注；**unknowns 非空 → 任务状态强制 `needs_human`**。

## 9. v1 明确边界

- potentiometer 滑臂（wiper）**不可接线**：v1 只当两端件画（带箭头装饰）。原图滑臂有接线的，
  按 UNKNOWN 协议处理或交遗留问题。
- 垂直跳线（jump 在竖线上）不支持，见 §5。
- 手绘/拍照图、继电器-接触器电气控制符号、数字逻辑门：v2/v1.x 路线图，见 PLAN.md §十六。

## 10. 简单路径字段检查清单（感知协议 §8.1 引用）

一次写全 ir.json 时逐项过：

1. `meta.canvas` 装得下全图？坐标全部非负、吸附 0.5？y 翻转了吗？
2. 每个可见符号 → components 恰一条（或 unknowns 恰一条）？计数与预检一致？
3. 两端件：from/to 与原图方位一致？极性类元件对照 §3.5 表定向了？
4. 多端件：先看引脚朝向定 (rotate, mirror)，`pins[].at` 填了观测值？
5. 每个 pin 的 net 填了？nets 清单先写了拓扑意图？
6. 每条原图走线 → wires 恰一条，转角逐点录入？
7. 原图实心点 → junctions；四路十字逐个声明连/不连？
8. 原图端口圈 → terminals（含 label）？
9. 图上每段文字：元件 label/value / `annotations` / legacy texts 三选一归属？
10. 电流方向、电压正负参考、节点极性是否用一等 annotation 明确 target 与坐标？
11. regions 覆盖全部元件？unknowns 该建的建了？
