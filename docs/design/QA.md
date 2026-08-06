# Design QA — 双栏种子解题台

**Source visual truth**

- 选定的方案 2 本地设计参考图；参考资产不在公开仓库中重复分发。
- Source pixels: `1487 × 1058`.

**Rendered implementation**

- [`../images/hard-seed1.png`](../images/hard-seed1.png)：Hard seed 1，已修正棋盘方向和左右斜向标签。
- [`../images/easy-seed1.png`](../images/easy-seed1.png)：Easy seed 1，226 格大盘与初始公开信息。
- [`ui-v071-reason-row-linked.png`](ui-v071-reason-row-linked.png)：0.7.1 在 `1440 × 1024` Windows Qt 窗口中固定“D1 / 横向 / 长度 7”，文字加粗、外侧行线索变色且整行格子显示柔光与实线组成的分层高亮。
- [`ui-v071-reason-array-linked.png`](ui-v071-reason-array-linked.png)：0.7.1 固定同一理由中的长坐标数组，整段文字与全部数组成员作为一个组显示静态分层高亮。
- Implementation pixels: `1440 × 1024`.
- Logical viewport: `1440 × 1024` at device pixel ratio `1.0`.
- 仓库保留 `0.7.1` 的应用界面截图作为当前 `0.7.2` 的视觉证据；0.7.2 只优化求解调度，没有修改 UI。

**Normalized comparison**

- 旧的并排比较图已经在 `0.6.4` 仓库整理时移除；仓库保留两张生成结果证据和两张当前应用界面截图。
- 早期方案对照曾把 source 与 implementation 归一化到 `1440 × 1024`；该并排图已按仓库整理规则移除，比较结论保留在下方历史中。
- 当前两张视觉证据直接使用 `1440 × 1024` 真实 Windows Qt 画面，展示演示盘、完整解释以及两类固定引用状态；0.7.2 的界面与之相同。

## Findings

No actionable P0, P1, or P2 differences remain for the selected information architecture.

- Fonts and typography: Chinese UI uses `Microsoft YaHei UI`; display numbers use `Bahnschrift`. Weight, hierarchy, line wrapping, and contrast remain legible at both tested window sizes. The pairing preserves the source's geometric-number and clean-Chinese-label treatment.
- Spacing and layout rhythm: the implementation keeps the source's narrow left solving rail, large right board stage, separated seed/manual/next-step groups, generous board whitespace, chamfered surfaces, thin borders, and light shadows. In `0.6.2`, the duplicate stats group is removed, the manual legend is compressed, and the next-step panel consumes the freed space; at `1120 × 760`, the reason area remains at least 300 px high while persistent controls stay visible.
- Colors and tokens: unknown, blue, clue, background, border, selected-step, and disabled states map consistently to the source orange/cyan/charcoal/light-gray palette. Text contrast remains usable.
- Image quality and asset fidelity: the selected design contains no photographic or illustrative raster assets. The board is implemented as interactive native geometry, not a placeholder image. General controls use the QtAwesome icon library; the numbered step marker is product data rendered in the same hexagonal grammar.
- Copy and content: seed, difficulty, remaining count, manual states, action, coordinate, reason, runtime generation state, and failure recovery are coherent in standalone use. The full Chinese reason remains available through a substantially larger scrollable area at both tested window sizes, while the fixed action bar never overlaps the text viewport.
- Icons and interaction states: copy, import, undo, reset, zoom, fit, settings, next, apply, selected difficulty, selected manual state, original-mouse toggle, and target-cell states are present and visually distinct.
- Accessibility: controls use native Qt semantics and keyboard focus behavior, retain high-contrast active states, and use practical click targets. 推理引用既支持点击也支持 Enter/空格；其悬停提示框已完全取消，棋盘预览只做一次有限淡入，系统禁用控件动画或设置 `HEXSOLVER_REDUCED_MOTION=1` 时直接显示静态结果，固定态仍以实线和字重表达。

The current Hard runtime capture now shows the same intended content class as the source: a wide irregular generated puzzle and `39` remaining. Easy was separately checked with a much denser 226-cell board; auto-fit keeps the complete puzzle and all line clues visible.

## Comparison history

### Pass 1

- Earlier P1: the first offscreen Qt capture did not load Windows Chinese fonts, so labels appeared blank.
- Fix: capture with the Windows Qt platform and verify the rendered font families in the real desktop surface.
- Post-fix evidence: intermediate capture archived locally.
- Earlier P1: primary button backgrounds were not painted by the inherited stylesheet, leaving white text on pale buttons.
- Fix: give difficulty, generate, next, and apply buttons explicit state styles.
- Post-fix evidence: intermediate capture archived locally.

### Pass 2

- Earlier P2: generated line-clue anchors overlapped the center of the board.
- Fix: use the original runtime-exported line anchor and apply family-specific rotation.
- Post-fix evidence: intermediate capture archived locally.
- Earlier P2: the implementation capture was constrained by desktop work area and did not match the source aspect ratio.
- Fix: capture a fixed `1440 × 1024` logical client area and normalize density before comparison.
- Post-fix evidence: intermediate capture and normalized comparison archived locally.

### Pass 3

- Earlier P2: the history trail used generic hex icons without step numbers and the rail was wider than the selected source.
- Fix: add numbered hex step markers, center the manual-marking header, set the rail to `300` logical pixels, and tighten board-stage padding.
- Post-fix evidence was later superseded by the then-current `0.6.5` captures; those captures were replaced by `0.7.0`, then by the current `0.7.1` evidence.

## Follow-up polish

- P3: the orange generate control is rectangular with chamfered surroundings rather than using the source mock's deeper downward point.

### Pass 4

- Regression found after the board Y-axis correction: diagonal clue labels retained their pre-mirror left/right family.
- Fix: swap only the rendered diagonal label families during original-export conversion while preserving the original constraint rays.
- Verification: [`../images/hard-seed1.png`](../images/hard-seed1.png) and a dedicated bridge regression test.

### Pass 5 (`0.6.1`)

- The left-side step history was removed and the next-step panel now fills the available vertical space.
- The reason text view has no maximum height, uses a 220 px minimum and 13 px text, and remains scrollable for extreme explanations.
- Every row-clue item is tracked, forced visible and opaque during board synchronization, and rendered above board cells.
- Viewport safety margins keep outer clues clear of the mode chip, remaining counter and bottom-right tool rail.

### Pass 6 (`0.6.2`)

- Removed the duplicate remaining/conflict card; the board counter remains the single remaining-value display.
- Reduced manual state controls to `60 × 56`, removed text drawn below each hex, and retained tooltip plus accessible name/description.
- Split the reason text viewport and the 46 px action bar into separate opaque layout regions; the text region has a bottom inset and cannot render under the buttons.
- Replayed Hard seed `00000003` through 54 applied moves and captured its 1709-character global proof at `1440 × 1024` and `1120 × 760`.
- Verified the minimum window at both the top and bottom of the reason scroll range; the final sentence remains fully visible above the action bar.

### Pass 7 (`0.6.3`)

- Added one gear icon to the existing bottom-right tool rail without changing the board, sidebar or solving workflow.
- Added a `720 × 480` settings surface using the same orange/cyan/charcoal/light-gray tokens, chamfered card geometry and native Qt controls.
- The settings content is placed in a scrollable section container so future options can be appended without redesigning the dialog.
- The cache card exposes purpose, enabled state, entry count, storage size and selectable path; deletion uses a red outlined action, explicit confirmation and inline success/error feedback.
- Cache hits change only the generation source label to “本地缓存”; board rendering, manual states, long reasoning layout and permanent row clues remain unchanged.

### Pass 8 (`0.6.4`)

- A real maximized-window screenshot showed that the scroll bar could reach its maximum while the final reasoning line remained partially clipped. The footer and text widget did not geometrically overlap; the missing protection was inside the text document's own scroll extent.
- Removed duplicate bottom padding from the `QTextEdit` viewport and stylesheet, then added a 28 px bottom margin to the document root frame whenever reasoning text changes.
- The root-frame margin increases the true scrollable document height without appending blank characters, so copying or testing `toPlainText()` still returns the exact original explanation.
- Replayed Hard seed `00000003` through 54 applied moves and scrolled step 55 to the bottom in a full-screen-class wide layout. The final sentence is fully visible with clear space above the fixed action bar.
- Source and packaged regressions now inspect the end cursor rectangle directly and require at least 16 px of visible clearance, rather than only comparing the outer widget geometries.

### Pass 9 (`0.6.5`)

- Replaced the shared cyan checked outline with state-specific active outlines: hidden uses charcoal-black, blue uses orange, and excluded uses cyan-blue.
- Kept the existing orange/blue/charcoal fills, `60 × 56` button size, white unchecked outline, shadow, tooltip and accessibility metadata.
- Captured all three checked states on the real Windows Qt platform; the committed full-screen frame shows the default hidden button with its black outline.
- Source and packaged regressions click each button, verify exclusive selection and count exact target-color pixels in the rendered button image.
- Added a settings card with an explicit checked button and status badge for the optional original-game mouse mapping: left-click excludes, right-click marks blue, and repeating the same button restores hidden.
- The option persists through `QSettings`, defaults off for compatibility, disables the manual-state buttons while active, and is tested with real left/right viewport clicks.

### Pass 10 (`0.7.0`)

- 将 `QTextEdit` 封装为只读富文本浏览器，解释的 `toPlainText()`、换行、滚动和 28 px 文档尾距保持不变。
- 坐标数组优先于单坐标解析，因此截图中的七个坐标只形成一个文字状态和一组棋盘状态；不存在于棋盘的坐标不会创建无效覆盖层。
- 悬停引用使用青蓝虚线低幅呼吸，固定引用使用青蓝实线；覆盖层位于基础格子和目标/手动描边之外，不改填充含义。
- 行引用除格子外同时强调外侧行线索；文字固定后用加粗和浅青底色表达，不只依赖颜色。
- 两张截图均由真实 Windows Qt 平台抓取并人工检查；65 项源码回归和冻结成品冒烟覆盖解析、联动、固定、减少动态、清理及原文保持。

### Pass 11 (`0.7.1`)

- 删除富文本字符格式中的提示内容，同时拦截推理正文视口的 `ToolTip` 事件；悬停引用不再产生任何原生提示框。
- 单层粗描边拆成外层低透明青色柔光和内层精细状态线；柔光在连续格之间自然连接，但不覆盖格子填充、数字或白色基础边缘。
- 悬停态使用细虚线并只做一次约 240 ms 缓出淡入；固定态使用深青实线且完全静止，减少动态模式直接显示最终静态层。
- 两张 `1440 × 1024` 截图由原生 Windows Qt 平台抓取并人工检查；自动回归和成品冒烟检查无提示框、双层几何、虚实线状态及原有键盘路径。

## Implementation checklist

- [x] Selected direction 2 reproduced as a functional two-column desktop UI.
- [x] Primary seed-to-manual-state-to-next-step path is interactive.
- [x] `1440 × 1024` source comparison completed.
- [x] `1120 × 760` layout-resilience capture completed.
- [x] Hard seed 1 at `1440 × 1024` and `1120 × 760` passed visual inspection.
- [x] Easy seed 1 dense-board capture passed visual inspection.
- [x] Hard seed 3 step 55 long global proof passed top/bottom scroll inspection at both supported window sizes.
- [x] 0.7.1 layered row/array reference highlights passed native Windows Qt visual inspection.
- [x] Sixty-nine automated core, cache, bridge, solver and Qt workflow tests pass.
- [x] Full-screen long-reason bottom capture and end-cursor visibility check pass.
- [x] Hidden, blue and excluded buttons render black, orange and blue active outlines respectively.
- [x] Original-style mouse controls persist, map real left/right clicks, toggle back to unknown, and restore manual tools when disabled.
- [x] Row names, individual coordinates and long coordinate arrays link to the correct board elements; hover, pin, keyboard activation and state cleanup pass.
- [x] No actionable P0/P1/P2 visual findings remain.

final result: passed
