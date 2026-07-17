# 交付单：<任务名>

- 日期：<YYYY-MM-DD>
- 状态：**<valid | needs_review | needs_human | approved>**
- 输入：`source.png`（<像素尺寸>，<来源说明>）
- 收敛：第 <N> 轮差异清单为空（上限 <max_rounds> 轮）

## 产物

| 文件 | 说明 |
|---|---|
| `circuit.tex` | circuitikz 源码（分区块注释；要改请反馈，勿手改） |
| `circuit.png` | 渲染图（300dpi） |
| `circuit.debug.png` | 网格+元件编号版（反馈时指着说话用） |
| `cmp_round<N>.png` | 第 N 轮 原图 vs 渲染 并排对比 |
| `circuit.ir.json` | 结构化真相源（网表+几何） |
| `review.json` | 状态、逐区结论、差异与 patch 轮次历史 |
| `rounds/round-<NN>/` | 每轮不可变快照 |
| `FEEDBACK.md` | 用户反馈话术 |

## 逐区核对结论

| 区 | 结论 |
|---|---|
| <region 名> | 无差异 / <差异摘要> |

## 遗留问题（needs_human 时必填）

| # | 位置(网格+原图rect) | 类别 | 描述 | 取证图 |
|---|---|---|---|---|
| | | | | |

## 反馈方式

见附带的 FEEDBACK.md——对照 `circuit.debug.png` 的网格坐标和元件编号描述改动即可。
