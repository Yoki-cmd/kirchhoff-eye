# circuitikz 序列化规范（Kirchhoff-eye v1）

> 实测环境：**circuitikz 1.8.5 (2026/02/04) @ TeX Live 2026 / pdflatex**。
> 本文档所有符号名、anchor 名、极性方向、标签落位均经 `tests/probes/` 渲染实测定稿
> （probe01–07），**不含任何凭记忆的名字**。升级 circuitikz 后重跑 probes 回归。
> ir2tikz.py 是本规范的机器实现；金样 golden.tex 是人手实现——两者输出必须同构。

## 1. 文档头模板

```latex
\documentclass[margin=5pt]{standalone}
\usepackage[american]{circuitikz}   % style.flavor=european 时换 [european]
\ctikzset{bipoles/length=1.0cm}     % 统一样式参数全部集中在此，正文禁止内联样式
\begin{document}
\begin{circuitikz}
...
\end{circuitikz}
\end{document}
```

- `texts` 含非 ASCII（中文）时 render.py `--engine auto` 自动切 lualatex，文档头换：
  `\documentclass[margin=5pt]{standalone}` + `\usepackage{ctex}` + 同上 circuitikz。
- `\ctikzset` 参数唯一合法位置是文档头；数值从 config.json 读。

## 2. 网格与坐标

规范正本见 `references/ir-schema.md` §1：1 网格单位 = 1 cm，TikZ 坐标=网格数，
y 向上，坐标吸附 0.5，两端件跨度推荐 2.0/最小 1.0，画布 ≤30×20。

## 3. 命名规则

- 元件 id 前缀：R 电阻 / RP 电位器 / C 电容 / L 电感 / D 二极管族 / V 电压源族 /
  I 电流源族 / SW 开关 / AM 电流表 / VM 电压表 / Q 三极管 / M MOS / OA 运放 /
  T 变压器 / GND、VCC、VEE 单端 / W 导线 / UNK 未知件。
- net 名：`N_` 前缀大写（N_IN、N_B…）；`GND`/`VCC`/`VEE` 是保留字。
- **named coordinate 名 = net 名**：`\coordinate (N_B) at (3,4);`，wire 中重合坐标一律
  引用该名——人可直读拓扑。每个 net 至多声明一个 coordinate（取该 net 的"汇合点"：
  junction 坐标优先，否则首个 wire 顶点）。

## 4. v1 符号词表映射总表（全部实测定稿）

### 4.1 两端件（IR type → to[] 名）

| IR type | circuitikz | 实测出处 | 备注 |
|---|---|---|---|
| resistor | `R` | probe01 | european flavor 下自动变矩形框 |
| potentiometer | `pR` | probe02 | 滑臂 v1 不接线（ir-schema §9） |
| capacitor | `C` | probe01 | |
| polar_capacitor | `cC` | probe02/03 | 直板(+)在 from；eC(电解框式)不入 v1 词表 |
| inductor | `L` | probe01 | |
| diode | `D` | probe01/03 | 阳极在 from |
| zener | `zD` | probe02 | 同 diode 方向 |
| led | `leD` | probe02 | 同 diode 方向 |
| battery | `battery1` | probe01/03b/03c | **加 invert**（见 §5.2）；多格 `battery`、粗短板 `battery2` 不入 v1 |
| vsource | `V` | probe01/03 | **加 invert** |
| isource | `I` | probe01/03 | 箭头 from→to，原样 |
| cvsource | `cV` | probe01/03 | **加 invert** |
| cisource | `cI` | probe01/03 | 原样 |
| switch_spst | `spst` | probe01 | |
| ammeter | `ammeter` | probe01 | |
| voltmeter | `voltmeter` | probe01 | |

### 4.2 多端件（IR type → node 名 + anchor）

anchor 偏移量以 `templates/anchors.json`（gen_anchor_table.py 机读产物）为准；下表为速查。

| IR type (variant) | node 样式 | IR pin → anchor | 默认姿态（rotate=0, mirror=false） |
|---|---|---|---|
| npn | `npn` | B→B, C→C, E→E | B 朝左(−0.84,0)，C 正上(0,0.77)，E 正下(0,−0.77) |
| pnp | `pnp` | 同上 | B 朝左，**E 正上，C 正下**（与 npn 上下互换） |
| nmos | `nmos` | G→G, D→D, S→S | G 朝左(−0.98,0)，D 正上，S 正下 |
| pmos | `pmos` | 同上 | G 朝左，**S 正上，D 正下** |
| opamp | `op amp` | inp→`+`, inn→`-`, out→`out` | **inn(−) 在上** (−1.19,0.49)，inp(+) 在下，out 朝右(1.19,0) |
| opamp (noinv_up) | `op amp, noinv input up` | 同上 | inp(+) 在上，inn(−) 在下 |
| transformer | `transformer` | A1/A2/B1/B2 | A 初级在左(A1 上 A2 下)，B 次级在右 |
| transformer (core) | `transformer core` | 同上 | 同上，带铁芯双线 |
| spdt | `spdt` | in→`in`, out1→`out 1`, out2→`out 2` | in 朝左，out1 右上，out2 右下 |

**运放极性翻转禁用 yscale**（±号会跟着镜像成镜像字）；同相端在上一律用
variant `noinv_up` → `noinv input up` 样式（probe05 实测有效）。

### 4.3 单端件

| IR type | 写法 | 符号相对接线点 |
|---|---|---|
| ground | `\node[ground] at (x,y) {};` | 画在下方 |
| vcc | `\node[vcc] at (x,y) {};` | 箭头朝上，画在上方 |
| vee | `\node[vee] at (x,y) {};` | 箭头朝下，画在下方 |

单端件带 label 时（如 vcc 的 `+12\mathrm{V}`）：沿 label_side 方向自 at 外扩 **0.5**
落独立文字（`\node[anchor=south] at (x,y+0.5) {$+12\mathrm{V}$};`）。

## 5. 两端件写法规则

### 5.1 模板

```latex
\draw (x1,y1) to[R, l=$R_1$, a=$10\mathrm{k}\Omega$, name=R1] (x2,y2);
```

- `(x1,y1)`=IR from，`(x2,y2)`=IR to，**永不交换**（几何顺序承载布局语义）。
- `name=<id>` 必加（调试/anchor 引用）。
- label/value 内容包进 `$...$`（IR 里存的是不带 $ 的数学内容）。

### 5.2 极性实现

vsource / cvsource / battery 一律追加 `invert`：
`to[V, invert, ...]`、`to[battery1, invert, ...]`——使正极落在 IR `to` 端
（probe03 实测：这三个符号原生 +/长板在 from 端，与 IR 约定相反）。
diode/zener/led/isource/cisource/polar_capacitor 原样不加。

### 5.3 `l=/l_=/a=/a^=` 四方向查表（probe04 实测定稿）

**定则：`l=` 恒落在行进方向左手侧，`a=` 恒右手侧；加 `_`/`^` 取反。**

| 元件走向（from→to） | 期望侧 | label 用 | value 用 |
|---|---|---|---|
| → 向右 | above | `l=` | `a^=` |
| → 向右 | below | `l_=` | `a=` |
| ← 向左 | above | `l_=` | `a=` |
| ← 向左 | below | `l=` | `a^=` |
| ↑ 向上 | left | `l=` | `a^=` |
| ↑ 向上 | right | `l_=` | `a=` |
| ↓ 向下 | left | `l_=` | `a=` |
| ↓ 向下 | right | `l=` | `a^=` |

水平元件的 side 只允许 above/below，垂直元件只允许 left/right（validate 不查，
序列化端遇到非法组合按"就近合法侧"处理并在头注释记一行 WARN）。
label 与 value 同侧会重叠——感知端按原图如实录，审读回路负责发现。

## 6. 多端件写法规则

```latex
\node[npn, xscale=-1, rotate=90] (Q1) at (x,y) {};
```

- 选项顺序**固定**：`<node名>[, 变体样式][, xscale=-1][, rotate=θ]`；
  mirror=false 省略 xscale，rotate=0 省略 rotate。
- 位姿语义（probe07 机读锁定）：`pin = at + M^mirror · R(θ) · offset`——
  offset **先旋转后镜像**，与上述写法的 TikZ 行为逐点一致。感知口诀：先按 rotate 转
  基准姿态，再水平翻。
- **引脚布线一律用 anchor**：`(Q1.B)`、`(OA1.out)`、`(SW1.out 1)`（spdt 的 anchor
  名含空格，ir2tikz 从 anchors.json 查映射），**禁止裸坐标**连引脚。
- label 定稿写法：**不用** TikZ label 机制、不用 calc 库；按 label_side 与
  anchors.json 的 bbox 外扩 0.2 算出具体坐标，落一条独立文字
  `\node[anchor=<对侧>] at (x,y) {$Q_1$};`（坐标由序列化端算死，代码↔图直读；
  对侧 = label_side 的反向 anchor：right→west, left→east, above→south, below→north）。

## 7. junction / crossing / terminal 约定

- junction（实心点）：`\node[circ] at (x,y) {};`
- T 型三路交点默认连通，不需要 junction 也不报错；原图有点才画点。
- 四路十字：IR 必须声明（E008）。`plain` crossing → **什么都不画**，两条 wire 裸交叉；
  `jump` crossing → `\node[jump crossing] (X1) at (x,y) {};` 然后四条邻接 wire 用
  `(X1.west)/(X1.east)/(X1.south)/(X1.north)` 接入（probe06/03b 实测：水平线拱起跳过，
  垂直线连续；v1 只支持水平跳）。
- terminal：`\node[ocirc] at (x,y) {};` + 标号按 label_side 外扩 0.3 落独立文字
  `\node[anchor=<对侧>] at (x±0.3,y) {$a$};`。

## 8. 导线规则

- wire 逐点 `--` 展开：`\draw (N_B) -- (4,2) -- (Q1.B);`
- **禁用 `|-`、`-|`、`++` 相对坐标、to[short]**——保证 IR↔代码↔图一一对应。
- 顶点坐标与某 net 的 named coordinate 重合时引用其名（§3）。
- 每条 `\draw` 只画一个对象（一条 wire / 一个元件）。

## 9. 标签与文字

- 全部数学模式；单位写法统一 `10\mathrm{k}\Omega`、`100\mathrm{nF}`、`+12\mathrm{V}`。
- 元件 label/value 限 ASCII+TeX；`texts` 允许中文（render.py 自动切 lualatex+ctex）。
- texts 序列化：`\node[anchor=<anchor>] at (x,y) {$content$};`（kind=annotation 数学体；
  port_label/net_label 同样数学体）。anchor 缺省 `center`。

## 10. 分区块注释格式

```latex
%% ==== [region] input-coupling ====
```

顺序：文档头 → 头注释（来源 + net 清单表，如 `% N_B: R1.2, C1.1, Q1.B`）→
逐 region 块（coordinate 声明 → 多端件 node → 两端件 to[] → 单端件）→
**jump crossing 节点块**（必须先于 wires——TikZ 不允许前向引用 node）→
wires 块（按 net 分组注释）→ junctions/terminals/texts 块。

## 11. 样式参数集中管理

`\ctikzset{bipoles/length=1.0cm}`（config.json `style.ctikzset`）。正文禁止任何
内联样式（scale、color、线宽等）；需要整体调观感只改文档头这一处。

## 12. 禁止事项

1. 禁词表外符号名（词表=本文档 §4，全部实测过；新符号先加探针再入表）。
2. 禁非吸附坐标（texts/pins[].at 豁免）。
3. 禁自动布局语法（`|-`、`-|`、`++`、to[short]、edge、graph）。
4. 禁 scope 嵌套变换；变换只出现在多端件 node 选项里。
5. 每条 `\draw` 只画一个对象。
6. 禁在生成物 .tex 上手工修改——要改就改 IR 再重序列化。
7. 运放禁用 yscale=-1（±号镜像成错字），用 `noinv input up`。
8. v1 不画：battery2/多格 battery/eC/`crossing` gap 式 node/电位器滑臂接线/垂直跳线。
