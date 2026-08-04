# Design QA — 双栏种子解题台

**Source visual truth**

- `C:\Users\Ling\.codex\generated_images\019fc1c3-12c4-7343-a741-cd7c57b92569\exec-c653b146-7ca2-432c-a6cd-e791dcef66f2.png`
- Source pixels: `1487 × 1058`.

**Rendered implementation**

- `D:\Desktop\HexInfinite\hexsolver_cn_py\tests\reports\ui-hard-seed1-runtime.png`：Hard seed 1，原版最终盘面，下一步及完整中文理由。
- `D:\Desktop\HexInfinite\hexsolver_cn_py\tests\reports\ui-easy-seed1-runtime.png`：Easy seed 1，226 格大盘与初始公开信息。
- `D:\Desktop\HexInfinite\hexsolver_cn_py\tests\reports\ui-hard-seed1-runtime-small.png`：Hard seed 1，`1120 × 760` 窄窗口。
- `D:\Desktop\HexInfinite\hexsolver_cn_py\tests\reports\ui-hard-seed1-progress15.png`：应用 15 步后的动态数字提示、历史和下一步理由。
- `D:\Desktop\HexInfinite\hexsolver_cn_py\tests\reports\ui-option-2-pass5@2x.png`
- Implementation pixels: `2880 × 2048`.
- Logical viewport: `1440 × 1024` at device pixel ratio `2.0`.
- Narrow-window evidence: `D:\Desktop\HexInfinite\hexsolver_cn_py\tests\reports\ui-small-1120x760@2x.png`, logical viewport `1120 × 760` at device pixel ratio `2.0`.

**Normalized comparison**

- `D:\Desktop\HexInfinite\hexsolver_cn_py\tests\reports\ui-option-2-comparison-pass5.png`
- The source was resampled to `1440 × 1024`; the implementation was downsampled from `2880 × 2048` to the same `1440 × 1024`. The two normalized frames were placed side by side in one `2880 × 1024` comparison image.
- State: seed `00000001`, Easy selected, visible next-step target and explanation.

## Findings

No actionable P0, P1, or P2 differences remain for the selected information architecture.

- Fonts and typography: Chinese UI uses `Microsoft YaHei UI`; display numbers use `Bahnschrift`. Weight, hierarchy, line wrapping, and contrast remain legible at both tested window sizes. The pairing preserves the source's geometric-number and clean-Chinese-label treatment.
- Spacing and layout rhythm: the implementation keeps the source's narrow left solving rail, large right board stage, separated seed/stat/manual/history/next-step groups, generous board whitespace, chamfered surfaces, thin borders, and light shadows. At `1120 × 760`, the history region contracts and scrolls while persistent controls remain visible.
- Colors and tokens: unknown, blue, clue, background, border, selected-step, and disabled states map consistently to the source orange/cyan/charcoal/light-gray palette. Text contrast remains usable.
- Image quality and asset fidelity: the selected design contains no photographic or illustrative raster assets. The board is implemented as interactive native geometry, not a placeholder image. General controls use the QtAwesome icon library; the numbered step marker is product data rendered in the same hexagonal grammar.
- Copy and content: seed, difficulty, remaining count, manual states, step history, action, coordinate, reason, runtime generation state, and failure recovery are coherent in standalone use. The full Chinese reason remains visible at both tested window sizes.
- Icons and interaction states: copy, import, undo, reset, zoom, fit, next, apply, selected difficulty, selected manual state, selected history row, and target-cell states are present and visually distinct.
- Accessibility: controls use native Qt semantics and keyboard focus behavior, include tooltips, retain high-contrast active states, and use practical click targets. There is no continuous animation that requires reduced-motion handling.

The current Hard runtime capture now shows the same intended content class as the source: a wide irregular generated puzzle and `39` remaining. Easy was separately checked with a much denser 226-cell board; auto-fit keeps the complete puzzle and all line clues visible.

## Comparison history

### Pass 1

- Earlier P1: the first offscreen Qt capture did not load Windows Chinese fonts, so labels appeared blank.
- Fix: capture with the Windows Qt platform and verify the rendered font families in the real desktop surface.
- Post-fix evidence: `tests/reports/ui-option-2-pass1-windows.png`.
- Earlier P1: primary button backgrounds were not painted by the inherited stylesheet, leaving white text on pale buttons.
- Fix: give difficulty, generate, next, and apply buttons explicit state styles.
- Post-fix evidence: `tests/reports/ui-option-2-pass3.png`.

### Pass 2

- Earlier P2: generated line-clue anchors overlapped the center of the board.
- Fix: use the original runtime-exported line anchor and apply family-specific rotation.
- Post-fix evidence: `tests/reports/ui-option-2-pass3.png`.
- Earlier P2: the implementation capture was constrained by desktop work area and did not match the source aspect ratio.
- Fix: capture a fixed `1440 × 1024` logical client area and normalize density before comparison.
- Post-fix evidence: `tests/reports/ui-option-2-pass4@2x.png` and the pass-4 comparison.

### Pass 3

- Earlier P2: the history trail used generic hex icons without step numbers and the rail was wider than the selected source.
- Fix: add numbered hex step markers, center the manual-marking header, set the rail to `300` logical pixels, and tighten board-stage padding.
- Post-fix evidence: `tests/reports/ui-option-2-pass5@2x.png` and `tests/reports/ui-option-2-comparison-pass5.png`.

## Follow-up polish

- P3: the orange generate control is rectangular with chamfered surroundings rather than using the source mock's deeper downward point.

### Pass 4

- Regression found after the board Y-axis correction: diagonal clue labels retained their pre-mirror left/right family.
- Fix: swap only the rendered diagonal label families during original-export conversion while preserving the original constraint rays.
- Verification: Hard seed 1 now matches the official diagonal label slopes, with a dedicated bridge regression test.

## Implementation checklist

- [x] Selected direction 2 reproduced as a functional two-column desktop UI.
- [x] Primary seed-to-manual-state-to-next-step path is interactive.
- [x] `1440 × 1024` source comparison completed.
- [x] `1120 × 760` layout-resilience capture completed.
- [x] Hard seed 1 at `1440 × 1024` and `1120 × 760` passed visual inspection.
- [x] Easy seed 1 dense-board capture passed visual inspection.
- [x] Thirty automated core, bridge, solver and Qt workflow tests pass.
- [x] No actionable P0/P1/P2 visual findings remain.

final result: passed
