# 本地开发空间说明

## 推荐结构

```text
D:\Desktop\HexInfinite\
├─ .vscode\                 # 打开整个工作区时使用的本地 Python 配置
├─ hexsolver_cn_py\         # 唯一 Git 仓库和可公开源码
├─ reverse_harness\         # 本地专有差分环境，不进入 Git
└─ _archive\                # 可恢复的日期归档，不进入 Git
```

原版游戏安装在：

```text
F:\SteamLibrary\steamapps\common\Hexcells Infinite
```

安装目录和原存档只读。本项目不会清理、覆盖或补丁该目录。

## 主仓库

`hexsolver_cn_py` 保存所有可公开、可复现的内容：

- Python 应用、Hard 纯 Python 生成器和 Easy 无 Unity 托管宿主源码；
- 一键启动、依赖、诊断和测试；
- `tests/fixtures/` 中两个小型结构化 TSV 回归夹具；
- `docs/images/` 中三张最终界面证据；
- 开发历史、算法、路线、设计验收和研究资料。

以下内容有用但只保留在本地，并由 `.gitignore` 排除：

- `.conda_env/`：当前一键启动环境，可由 `run.ps1` 重建；
- `managed_core/bin/`：Easy 托管核心构建产物，可由 `managed_core/build.ps1` 重建；
- `tests/images/`、`tests/labels/`：含原版游戏截图的 OCR 本地数据；
- `tests/reports/`：临时视觉 QA 输出；
- `.vscode/`：打开仓库自身时使用的个人编辑器设置。

## `reverse_harness`

该目录不是产品运行所必需的普通依赖，而是显式差分验证环境：

- `game/`：经过隔离的原版副本和补丁运行时；
- `tools/`：Mono.Cecil 补丁源代码和本地构建依赖；
- `exports/`：原版运行时导出的比较数据。

这里含有原游戏二进制、DLL 和存档，不能上传 GitHub。默认求解流程不会启动其中的 `Hexcells Infinite.exe`；只有显式运行 `tools/doctor.py --compare-original` 才会使用它。

## 测试的可移植性

标准测试从仓库内 `tests/fixtures/` 读取 Easy/Hard seed 1 数据，不再依赖工作区外部导出目录。

Easy 托管核心的真实集成校验仍需要合法安装中的 `Assembly-CSharp.dll`：

1. 优先读取环境变量 `HEXCELLS_ASSEMBLY`；
2. 其次读取本地 `reverse_harness` 的只读原始程序集；
3. 最后读取已知 Steam 安装路径。

找不到程序集时，只有这一项集成测试会明确跳过；其余单元测试和 Hard 离线测试仍可执行。

## 2026-08-05 整理记录

- 根目录两份早期研究文档迁入 `docs/research/`，修正绝对路径链接。
- 两个精确 TSV 样本迁入 `tests/fixtures/`，测试不再依赖 `reverse_harness/exports`。
- 三张最终 UI 证据迁入 `docs/images/`；中间比较图转入本地归档。
- 根目录旧 `test/` 截图、旧 GitHub 同步脚本和自动推送钩子转入日期归档。
- `reverse_harness` 的中间导出、可重建 EXE/DLL 和 Mono.Cecil 下载展开缓存转入日期归档。
- Python `__pycache__` 与其他旧文件一并移入日期归档；它们可由运行测试自动重建，确认无回滚需要后可直接删除。
- `.conda_env`、OCR 本地数据、托管核心输出和隔离游戏副本保留。

## 清理原则

- 原游戏安装和存档永不作为清理目标。
- 游戏二进制、私有运行时、OCR 截图和本地环境永不上传。
- 不确定是否有价值的内容先移动到 `_archive/YYYY-MM-DD-*`，验证稳定后再由人工决定是否彻底删除。
- 只有缓存、日志和可完全重建的临时文件允许直接删除。
