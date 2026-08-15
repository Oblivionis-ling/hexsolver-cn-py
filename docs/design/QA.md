# Design QA — 双栏种子解题台

**Source visual truth**

- 选定的方案 2 本地设计参考图；参考资产不在公开仓库中重复分发。
- Source pixels: `1487 × 1058`.

**Rendered implementation**

- [`../images/hard-seed1.png`](../images/hard-seed1.png)：Hard seed 1，已修正棋盘方向和左右斜向标签。
- [`../images/easy-seed1.png`](../images/easy-seed1.png)：Easy seed 1，226 格大盘与初始公开信息。
- [`ui-v073-onboarding.png`](ui-v073-onboarding.png)：0.7.3 在 `1440 × 1024` Windows Qt 窗口中的空盘启动状态，四组手绘箭头分别指向种子生成、手动同步、下一步推理和设置入口。
- [`ui-v074-settings-dropdown.png`](ui-v074-settings-dropdown.png)：0.7.4 设置页的启动窗口下拉菜单已展开，显示白底、深色文字、浅蓝当前项和三个完整选项。
- [`ui-v080-settings-progress-native.png`](ui-v080-settings-progress-native.png)：0.8.0 设置页局面与进度卡，显示自动恢复状态、手动保存/载入和清除进度入口。
- [`ui-light-confirmation.png`](ui-light-confirmation.png)：0.8.1 自绘浅色恢复确认框，显示白底高对比度表面和“继续局面 / 放弃并查看说明”中文按钮。
- [`ui-readable-global-reason.png`](ui-readable-global-reason.png)：0.8.1 Hard seed 3 的首个全局唯一性步骤，首屏先显示结论、试填反证与关键条件概览。
- Onboarding implementation pixels: `1440 × 1024` at device pixel ratio `1.0`.
- 0.7.4 settings evidence pixels: `1440 × 1200`; logical dialog viewport: `720 × 600` at device pixel ratio `2.0`.
- 仓库保留 0.7.3 启动说明、0.7.4 白底下拉菜单、0.8.0 局面进度卡以及 0.8.1 的确认框和全局理由作为当前应用界面证据；0.7.1 的分层联动高亮继续由自动回归、成品冒烟和下方历史记录验证。

**Normalized comparison**

- 旧的并排比较图已经在 `0.6.4` 仓库整理时移除；仓库保留两张生成结果证据和必要的当前应用界面证据。
- 早期方案对照曾把 source 与 implementation 归一化到 `1440 × 1024`；该并排图已按仓库整理规则移除，比较结论保留在下方历史中。
- 当前视觉证据由真实 Windows Qt 平台生成：启动说明继续使用 `1440 × 1024` 画面，下拉菜单使用 `720 × 600` 逻辑设置窗口并保留当前 Windows 的 `2.0` 设备像素比，不伪造缩放环境。

## Findings

No actionable P0, P1, or P2 differences remain for the selected information architecture.

- Fonts and typography: Chinese UI uses `Microsoft YaHei UI`; display numbers use `Bahnschrift`. Weight, hierarchy, line wrapping, and contrast remain legible at both tested window sizes. The pairing preserves the source's geometric-number and clean-Chinese-label treatment.
- Spacing and layout rhythm: the implementation keeps the source's narrow left solving rail, large right board stage, separated seed/manual/next-step groups, generous board whitespace, chamfered surfaces, thin borders, and light shadows. In `0.6.2`, the duplicate stats group is removed, the manual legend is compressed, and the next-step panel consumes the freed space; at `1120 × 760`, the reason area remains at least 300 px high while persistent controls stay visible.
- Colors and tokens: unknown, blue, clue, background, border, selected-step, and disabled states map consistently to the source orange/cyan/charcoal/light-gray palette. Text contrast remains usable.
- Image quality and asset fidelity: the selected design contains no photographic or illustrative raster assets. The board is implemented as interactive native geometry, not a placeholder image. General controls use the QtAwesome icon library; the numbered step marker is product data rendered in the same hexagonal grammar.
- Copy and content: seed, difficulty, remaining count, manual states, action, coordinate, reason, runtime generation state, and failure recovery are coherent in standalone use. The full Chinese reason remains available through a substantially larger scrollable area at both tested window sizes, while the fixed action bar never overlaps the text viewport.
- Icons and interaction states: copy, import, undo, reset, zoom, fit, settings, next, apply, selected difficulty, selected manual state, original-mouse toggle, and target-cell states are present and visually distinct.
- Accessibility: controls use native Qt semantics and keyboard focus behavior, retain high-contrast active states, and use practical click targets. 推理引用既支持点击也支持 Enter/空格；其悬停提示框已完全取消，棋盘预览只做一次有限淡入，系统禁用控件动画或设置 `HEXSOLVER_REDUCED_MOTION=1` 时直接显示静态结果，固定态仍以实线和字重表达。
- Onboarding and startup: the initial board is intentionally empty rather than a fake puzzle. Four text callouts use the existing orange/cyan tokens, double-stroke hand-drawn arrows and circled endpoints; the explanation can be closed, reopened from settings, and disappears automatically after a verified seed board loads. The startup selector is collapsed by default, uses a white surface and explicit chevron, and reveals windowed maximized, borderless full-screen and normal-window choices in a white popup with a light-cyan current/hover state.

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
- Post-fix evidence was later superseded by the then-current `0.6.5` captures; those captures were replaced by `0.7.0`, `0.7.1`, the still-current `0.7.3` onboarding, and the `0.7.4` startup-dropdown evidence.

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

### Pass 12 (`0.7.3`)

- 移除启动模拟盘面，改用空棋盘和四步说明，避免用户把开发样例误认为已经生成的种子结果。
- 引导覆盖层只淡化右侧棋盘区；种子控件与设置入口仍可操作。四张说明卡使用真实 `QLabel`，具有可读文本和无障碍名称，箭头由 Qt 原生几何绘制，不依赖额外图片。
- “关闭说明”是独立可聚焦按钮；生成真实盘面后自动收起，设置页“重新查看使用说明”可恢复说明并暂时停用棋盘交互。
- 启动窗口设置把有窗口最大化作为默认值，同时明确提供无边框全屏和普通窗口；选择通过 `QSettings` 持久化，并在下一次启动时应用。
- 两张 `1440 × 1024` 截图由原生 Windows Qt 平台抓取并人工检查；中文、箭头落点、按钮、首屏滚动位置和现有橙/青/炭灰视觉语言均正常。

### Pass 13 (`0.7.4`)

- 根据用户真实全屏截图定位，原启动窗口弹出列表未指定完整调色板，在 Windows/Fusion 样式下继承了深色表面与低对比文字。
- 折叠控件改为独立白底表面，只显示当前选项和明确箭头；键盘聚焦时使用蓝色轮廓，不依赖鼠标悬停。
- 弹出列表通过 QSS、`QPalette` 和专用 item delegate 共同约束为白底深色文字，当前/悬停项使用浅蓝底与深青文字，并去除系统深色大块和粗重焦点框。
- 原生 Windows Qt 截图人工检查了白底、三项文字、浅蓝当前项、首屏层级和原有橙/青/炭灰风格；回归测试另外核对默认折叠、展开/收起、调色板与实际像素比例。

### Pass 14 (`0.8.0`)

- 设置页在启动窗口下方增加“局面与进度”卡片；自动恢复使用青色按钮与浅青状态徽标，手动保存/载入使用蓝色轮廓，清除进度使用红色轮廓。
- 无活动局面时保存与清除按钮具有明确灰色禁用态，载入入口保持可用；滚动结构和固定“完成”按钮不变。
- 原生 Windows Qt 截图确认文字对比度、按钮层级、卡片间距和 1440 × 1024 首屏滚动位置正常。

### Pass 15 (`0.8.1`)

- 将系统消息框替换为完全自绘的浅色确认框，因此 Windows 深色应用主题不会再把确认操作渲染成突兀的深灰表面；白底、深色文字、橙色品牌图形和浅蓝信息图标与主界面一致。
- 恢复确认使用“继续局面 / 放弃并查看说明”直接描述结果；清除进度和删除缓存复用相同组件，并保留危险操作的明确措辞和安全默认项。
- 全局唯一性正文在首屏先显示目标格结论和三步试填反证，把完整条件、坐标与候选格移入仍可滚动查看的详细核查区；解释数据没有删减。
- 正文调整为 14 px、145% 行高和更深文字，分区标题加粗并增加留白；Hard seed 3 的原生 Windows Qt 截图确认结论与反证摘要无需先阅读长坐标列表即可理解。
- 85 项源码回归检查弹窗表面与按钮、恢复分支、新全局说明结构、“合法填法 = 0”、详细核查保留以及原推理引用联动。

## Implementation checklist

- [x] Selected direction 2 reproduced as a functional two-column desktop UI.
- [x] Primary seed-to-manual-state-to-next-step path is interactive.
- [x] `1440 × 1024` source comparison completed.
- [x] `1120 × 760` layout-resilience capture completed.
- [x] Hard seed 1 at `1440 × 1024` and `1120 × 760` passed visual inspection.
- [x] Easy seed 1 dense-board capture passed visual inspection.
- [x] Hard seed 3 step 55 long global proof passed top/bottom scroll inspection at both supported window sizes.
- [x] 0.7.3 onboarding and 0.7.4 white startup dropdown passed native Windows Qt visual inspection at their recorded logical sizes and device pixel ratios.
- [x] Ninety automated core, cache, bridge, solver, session-store and Qt workflow tests pass.
- [x] Full-screen long-reason bottom capture and end-cursor visibility check pass.
- [x] Hidden, blue and excluded buttons render black, orange and blue active outlines respectively.
- [x] Original-style mouse controls persist, map real left/right clicks, toggle back to unknown, and restore manual tools when disabled.
- [x] Row names, individual coordinates and long coordinate arrays link to the correct board elements; hover, pin, keyboard activation and state cleanup pass.
- [x] Startup is empty and maximized by default; all three window modes persist, the guide can close/reopen, and a verified seed board automatically dismisses it.
- [x] The apply-suggestion button has no tooltip and retains an accessible name and description.
- [x] Progress settings, save/load/clear actions and the restore-state badge remain legible on native Windows Qt.
- [x] Confirmation dialogs remain light under the native Windows theme and use explicit Chinese outcomes.
- [x] Global uniqueness reasons show the conclusion and trial-elimination summary before optional detailed coordinates.
- [x] No actionable P0/P1/P2 visual findings remain.

final result: passed
