# 金样 B 渲染核对记录

- 日期：2026-07-07；环境：TeX Live 2026 pdflatex + circuitikz 1.8.5；pdftoppm 300dpi
- 输入：`ir.json`（PLAN.md §6.6 原样落盘，jsonschema 校验 PASS）；`golden.tex`（人手序列化）

## 逐项核对（对照 ir.json 目视 golden.png）

| 项 | 期望（IR） | 渲染 | 判定 |
|---|---|---|---|
| R1 (1,4)→(3,4) | 横放，R_1 上、10kΩ 下 | 一致 | ✓ |
| C1 (3,4)→(3,2) | 竖放，C_1 右、100nF 左 | 一致 | ✓ |
| GND1 (3,2) | 接地符 | 一致 | ✓ |
| Q1 npn at(5,4) r0 m0 | B 朝左、C 正上、E 正下、发射极箭头朝外 | 一致 | ✓ |
| Q1 标签 | Q_1 右侧 | 一致 | ✓ |
| R2 (5,6)→(5,7.5) ↑ | R_C 右（l_=）、2kΩ 左（a^=） | 一致 | ✓ |
| VCC1 (5,7.5) | 上箭头 + 上方 +12V | 一致 | ✓ |
| GND2 (5,2) | 接地符 | 一致 | ✓ |
| junction (3,4) | 实心点（唯一） | 一致 | ✓ |
| terminal (0,4) | 空心圈 + 标号 a 在左 | 一致 | ✓ |
| text u_i (0.2,4.6) | 端口斜上方 | 一致 | ✓ |
| 引脚走线 | W2 (N_B)–(Q1.B) 水平；W3 (Q1.C)–(5,6) 垂直；W4 (Q1.E)–(5,2) 垂直 | 全部严格正交（anchors.json：npn B 恰水平、C/E 恰垂直于中心） | ✓ |

## 拓扑走读

端口 a → R1 → N_B(junction, 3,4) → {C1→GND, Q1.B}；Q1.C → R2 → VCC；Q1.E → GND。
与 nets 声明（N_IN/N_B/N_C/VCC/GND）一致。

## 结论

**PASS**。金样 B 同时验证了：多端件 anchor 布线不产生斜线（依赖 npn C/E 与中心垂直
对齐的实测事实）、`l_=`/`a^=` 在 ↑ 走向下的落位、vcc/ground 单端件画向。
