# 怎么给我反馈（请照这样说）

打开交付物里的 **circuit.debug.png**：上面有浅灰网格（1 格 = 1 单位，刻度在左/下边缘）、
每个元件内部锚点上的红色十字，以及红色编号（R1、C1、Q1…）。红色十字坐标是元件
锚点，不是文字外框。**对着网格坐标和元件编号说话**，我就能精确改：

| 你这样说 | 我会这样改 |
|---|---|
| "X 和 Y 之间应该是电容不是电阻" | 换元件类型（CHANGE_TYPE） |
| "R3 往右/上移一格" | 移位（MOVE） |
| "(4,2) 那两条线是相连的 / 只是跨过" | 加连接点 / 加跨线（ADD_JUNCTION / ADD_CROSSING） |
| "R1 上端应该接到 C2 左端，不是接地" | 改接线（REWIRE） |
| "10k 这个标注应该在元件下面" | 挪标注侧（SET_LABEL_SIDE） |
| "Q1 编号放到 (6.25,5.75)" | 设置绝对编号坐标（SET_LABEL_AT） |
| "少画了一个接地 / 多画了一个电阻" | 增删元件（ADD/REMOVE_COMPONENT） |
| "三极管方向反了 / 发射极应该朝左" | 镜像/旋转（MIRROR / ROTATE） |
| "这段线原图是先下后右" | 改走线转角（SET_WAYPOINTS） |
| "UNK1 那个虚线框其实是稳压管" | 人工确认后生成无 unknown 的新 IR，并重新 build |

说明：
- 所有修改都改在结构化数据（ir.json）上再重新出图，不会手补图面——所以改动永远
  全图一致、可复现。
- 一次可以提多条；我按"先接线对不对、再位置、再标注"的顺序处理。
- 位置尽量给 debug 图上的网格坐标（如 "(3,4) 那个点"），比"左上角那个"准得多。
- 多个编号坐标可保存为 `component_label_positions.json`，再运行：
  `kirchhoff-eye labels apply circuit.ir.json component_label_positions.json -o circuit.labelled.ir.json`。
- positions 文件里的 `null` 表示保持当前自动或人工位置不变；未知元件 ID 会报错且不产出文件。
