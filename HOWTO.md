# Kirchhoff-eye 上手（写给用户）

## 这是什么

给我一张**印刷体/软件导出**的电子电路图图片（jpg/png），我会用 AI 辅助读图并经人工可审阅的
结构化 IR 回路，还你：
1. 一份可直接编译的 circuitikz 代码（`circuit.tex`，布局和原图一致，带分区注释）；
2. 渲染好的图（`circuit.png`）；
3. 一张带网格、元件锚点红色十字和元件编号的调试图（`circuit.debug.png`），方便你指着提修改。

## 怎么用

把图片给我，说一句"把这张电路图转成 circuitikz / LaTeX"即可。可选补充：
- "用国标画法"（电阻画矩形框 → european 风格）；
- 元件值如果图上模糊，直接告诉我（如"R2 是 4.7k"）。

我会走"读图/审阅 → 编写 IR → 机器校验 → 出码 → 渲染 → 和原图并排对比 → 修正"的
回路（最多 3 轮），交付时附上并排对比图。公开工具保证 IR 之后的步骤可重复；当前不承诺
任意图片都能全自动生成正确拓扑。

默认目标是语义重画：拓扑、元件身份、相对位置、分组、母线和重要转角应保持可辨认；
尺寸、间距、画布和次要对齐可为清晰度调整。只有明确要求摹图时才追求像素级一致。

## 交付状态

- **valid**：IR、拓扑、布局与渲染均有效；没有原图时不代表做过忠实度审批。
- **needs_review**：已生成原图对比，但逐区审读或显式批准尚未完成。
- **needs_human**：有我拿不准的地方（如词表外的符号会画成虚线占位框 UNK1），
  或达到最大轮次仍有差异；交付单里列了遗留问题，等你拍板。
- **approved**：每个 region 都已明确核对且差异为空，并执行了显式批准。

普通画布、间距、粗略重叠等 W 级建议只进入诊断报告，不会单独把任务升级成 `needs_human`。

如果你直接操作 CLI，审读和批准是两个步骤：

```bash
kirchhoff-eye review out/job round-review.json
kirchhoff-eye approve out/job --note "逐区确认通过"
```

有差异时先让 Agent 修改 IR，再用 `repair` 记录 patch 并开启下一轮：

```bash
kirchhoff-eye repair out/job repaired.ir.json --patches patches.json
```

差异记录必须注明所属 region；每个 `difference_id` 每轮只能对应一个 patch。字段修改使用精确
JSON Pointer，例如元件值 `/components/1/value`、走线转角 `/wires/0/points`。

还可以用统一任务入口处理图片重画、自然语言简述、netlist、IR 编辑和直接渲染；这些入口都要求 Agent 先产出/审阅 canonical IR，不宣称自动理解任意输入：

```bash
kirchhoff-eye task redraw-image source.png reviewed.ir.json --out out/redraw
kirchhoff-eye task draw-from-description brief.txt authored.ir.json --out out/brief
kirchhoff-eye task draw-from-netlist input.cir authored.ir.json --out out/netlist
kirchhoff-eye task edit-ir request.txt edited.ir.json --out out/edit
kirchhoff-eye task render circuit.ir.json --out out/render
```

## 怎么提修改

看 `DELIVERY.md` 附的反馈话术表（FEEDBACK.md）：对照 `circuit.debug.png` 上的
网格坐标和红色元件编号说话，例如：

> "(3,4) 那个点其实不相连，是跨线" / "R2 往下移一格" / "Q1 发射极应该朝左"

编号位置可直接说：`Q1 编号放到 (6.25,5.75)`。多个编号可写入
`templates/component_label_positions.json` 同格式文件并批量应用：

```bash
kirchhoff-eye labels apply circuit.ir.json positions.json -o circuit.labelled.ir.json
```

其中 `null` 表示保持当前自动或人工位置不变。

所有修改落在结构化数据上重新出图，不手补图面，改完再给你新的四件套。

## v1 边界（提前说清）

不支持：手绘/拍照图、继电器-接触器电气控制图、数字逻辑门、电位器滑臂接线。
遇到会明说，不会硬画。
