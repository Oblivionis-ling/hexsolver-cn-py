# Windows 单文件打包与发布

## 目标

`0.6.5` 将现有 PySide6 求解器封装为一个 Windows x64 EXE。打包层不重写生成器或求解器；源码版与成品版都从 `MainWindow`、`HexReasoningSolver` 和同一组 Easy/Hard 后端启动，并共享同一套版本化种子缓存实现。本版调整三个手动标记按钮的选中外轮廓颜色，并增加可持久化的原版式左右键操作设置。

发布资产：

```text
HexInfiniteSolver-0.6.5-windows-x64.exe
HexInfiniteSolver-0.6.5-windows-x64.exe.sha256
```

2026-08-06 已验证 `0.6.5` 发布成品：96,486,810 字节（92.02 MiB），SHA-256 为 `c7043d7c5ada00d7915a912f2025fb8cf653064cf81919ecc07944e85604b45a`。Windows 版本资源中的 FileVersion 和 ProductVersion 均为 `0.6.5`。

## 成品包含什么

- Python 3.11 运行时。
- PySide6、QtAwesome、OR-Tools、NumPy/Pandas 等当前功能所需依赖。
- Hard 纯 Python 生成器。
- 项目自有的 `HexcellsHeadless.exe`、`UnityEngine.dll` 和 `TextMeshPro-5.6-Runtime.dll` 最小兼容宿主。
- Qt 插件、字体图标、应用图标和 Windows 版本资源。
- 种子缓存、用户体验偏好与设置页；缓存数据和 Qt 用户设置在运行时写入用户目录，不会预置在 EXE 中。

截图入口当前关闭，因此 0.6.5 成品排除 OpenCV、ONNX Runtime 和 RapidOCR，以减少体积；这不改变当前可用 UI 或种子求解流程。

## 成品不包含什么

- 原版 `Assembly-CSharp.dll`。
- `Hexcells Infinite.exe` 或其他游戏文件。
- 游戏存档、Steam 凭据、隔离逆向环境或 OCR 原始截图。
- Conda 环境和项目源码工作区。

Easy 会按顺序查找 `HEXCELLS_ASSEMBLY`、EXE 同目录、本地验证工作区和已知 Steam 安装目录，并在使用前核对 Steam Build `5455383` 的 SHA-256。Hard 完全不依赖原游戏文件。

## 构建

在仓库根目录运行：

```powershell
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\packaging\build_app.ps1
```

脚本会：

1. 检查或安装 `requirements-build.txt` 中固定版本的 PyInstaller。
2. 重建 Easy 托管宿主。
3. 运行完整源码测试。
4. 生成 EXE 图标和 Windows 版本资源。
5. 生成单文件 `windowed` 应用。
6. 检查归档包含三个可再分发托管文件，且不含原版 `Assembly-CSharp.dll`。
7. 用真实 EXE 执行 `--package-smoke-test`。
8. 输出 SHA-256 文件。

## 成品级验证

`--package-smoke-test` 不是“能启动进程就算通过”，而是由冻结后的应用自身：

- 创建真实 `QApplication` 和 `MainWindow`；
- 核对窗口标题、最小尺寸、默认尺寸、300 px 侧栏和截图入口关闭状态；
- 核对步骤历史和重复统计控件已移除、推理原因区域获得预期高度；
- 核对推理正文严格位于固定按钮栏上方，并且手动标记图例采用紧凑尺寸；
- 依次点击未知、蓝格、排除按钮，核对互斥选中状态以及黑、橘、蓝三种轮廓的实际渲染像素；
- 在设置页开启原版式鼠标操作，核对左键排除、右键蓝色、重复同键恢复未知，以及开启/关闭时手动工具的禁用与恢复；
- 写入 80 行合成长解释、滚动到末尾，并直接检查末尾光标完整位于文本视口内且具有 28 px 根帧安全尾距；
- 核对全部行线索存在、可见并位于棋盘格上层；
- 核对右下角设置入口可访问，设置页显示真实缓存目录和鼠标操作开关；
- 核对单文件内的三个 Easy 托管宿主文件；
- 生成 Easy seed 1，并核对第一条建议与私有答案，再次请求并确认命中缓存；
- 生成 Hard seed 1，并核对第一条建议与私有答案，再次请求并确认命中缓存；
- 全部完成后以退出码 0 结束。

构建命令返回成功、EXE 文件存在或窗口短暂出现，都不能替代这项验证。

## 已知边界

- 成品目标为 Windows 10/11 x64。
- 单文件程序首次启动需要解压运行时到系统临时目录，可能比后续源码环境启动稍慢。
- 当前没有商业代码签名，SmartScreen 可能提示未知发布者；应核对 Release 中的 SHA-256。
- Easy 依赖合法安装的特定原版程序集；找不到或哈希不匹配时会明确拒绝生成，不会退化为近似地图。
- 缓存采用版本化 JSON，键包含 schema、Steam Build、难度、种子、后端 ID 和精确性；损坏或不匹配时直接重算。打包冒烟使用独立临时缓存目录，结束后只删除该已验证的临时目录。
