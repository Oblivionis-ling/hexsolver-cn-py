# Design QA — 双栏种子解题台

**Source visual truth**

- 选定的方案 2 本地设计参考图；参考资产不在公开仓库中重复分发。
- Source pixels: `1487 × 1058`.

**Rendered implementation**

- [`../images/hard-seed1.png`](../images/hard-seed1.png)：Hard seed 1，已修正棋盘方向和左右斜向标签。
- [`../images/easy-seed1.png`](../images/easy-seed1.png)：Easy seed 1，226 格大盘与初始公开信息。
- [`ui-v065-fullscreen-reason-bottom.png`](ui-v065-fullscreen-reason-bottom.png)：0.6.5 全屏类宽屏布局中，Hard seed 3 第 55 步滚动到推理末尾；默认未知按钮使用黑色选中轮廓。
- [`ui-v065-settings-720x600.png`](ui-v065-settings-720x600.png)：0.6.5 鼠标操作与种子缓存设置页，逻辑尺寸 `720 × 600`；截图中原版式左右键操作已开启。
- Implementation pixels: `2880 × 2048`.
- Logical viewport: `1440 × 1024` at device pixel ratio `2.0`.
- 仓库只保留当前 `0.6.5` 的应用界面截图；旧版布局截图已移除，演进过程保留在下方文字记录和开发历史中。

**Normalized comparison**

- 旧的并排比较图已经在 `0.6.4` 仓库整理时移除；仓库保留两张生成结果证据和两张当前应用界面截图。
- The source was resampled to `1440 × 1024`; the implementation was downsampled from `2880 × 2048` to the same `1440 × 1024`. The two normalized frames were placed side by side in one `2880 × 1024` comparison image.
- State: seed `00000001`, Easy selected, visible next-step target and explanation.

## Findings

No actionable P0, P1, or P2 differences remain for the selected information architecture.

- Fonts and typography: Chinese UI uses `Microsoft YaHei UI`; display numbers use `Bahnschrift`. Weight, hierarchy, line wrapping, and contrast remain legible at both tested window sizes. The pairing preserves the source's geometric-number and clean-Chinese-label treatment.
- Spacing and layout rhythm: the implementation keeps the source's narrow left solving rail, large right board stage, separated seed/manual/next-step groups, generous board whitespace, chamfered surfaces, thin borders, and light shadows. In `0.6.2`, the duplicate stats group is removed, the manual legend is compressed, and the next-step panel consumes the freed space; at `1120 × 760`, the reason area remains at least 300 px high while persistent controls stay visible.
- Colors and tokens: unknown, blue, clue, background, border, selected-step, and disabled states map consistently to the source orange/cyan/charcoal/light-gray palette. Text contrast remains usable.
- Image quality and asset fidelity: the selected design contains no photographic or illustrative raster assets. The board is implemented as interactive native geometry, not a placeholder image. General controls use the QtAwesome icon library; the numbered step marker is product data rendered in the same hexagonal grammar.
- Copy and content: seed, difficulty, remaining count, manual states, action, coordinate, reason, runtime generation state, and failure recovery are coherent in standalone use. The full Chinese reason remains available through a substantially larger scrollable area at both tested window sizes, while the fixed action bar never overlaps the text viewport.
- Icons and interaction states: copy, import, undo, reset, zoom, fit, settings, next, apply, selected difficulty, selected manual state, original-mouse toggle, and target-cell states are present and visually distinct.
- Accessibility: controls use native Qt semantics and keyboard focus behavior, include tooltips, retain high-contrast active states, and use practical click targets. There is no continuous animation that requires reduced-motion handling.

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
- Post-fix evidence was superseded by the current `0.6.5` captures; the obsolete intermediate screenshot is no longer retained.

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

## Implementation checklist

- [x] Selected direction 2 reproduced as a functional two-column desktop UI.
- [x] Primary seed-to-manual-state-to-next-step path is interactive.
- [x] `1440 × 1024` source comparison completed.
- [x] `1120 × 760` layout-resilience capture completed.
- [x] Hard seed 1 at `1440 × 1024` and `1120 × 760` passed visual inspection.
- [x] Easy seed 1 dense-board capture passed visual inspection.
- [x] Hard seed 3 step 55 long global proof passed top/bottom scroll inspection at both supported window sizes.
- [x] Fifty-six automated core, cache, bridge, solver and Qt workflow tests pass.
- [x] Full-screen long-reason bottom capture and end-cursor visibility check pass.
- [x] Hidden, blue and excluded buttons render black, orange and blue active outlines respectively.
- [x] Original-style mouse controls persist, map real left/right clicks, toggle back to unknown, and restore manual tools when disabled.
- [x] No actionable P0/P1/P2 visual findings remain.

final result: passed
