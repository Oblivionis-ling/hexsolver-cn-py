# HexInfinite 种子求解器

当前版本：`0.4.2`

这是一个面向 `Hexcells Infinite` 的 Windows 中文逐步求解器。输入种子号并选择 Easy/Hard 后，程序会在本地复刻原版地图，不再启动 `Hexcells Infinite.exe`；你可以手动同步当前进度，然后每次只获取一个必然步骤和中文理由。

## 已可用

- 方案 2 双栏界面：左侧六边形控制轨，右侧大棋盘。
- Easy：最小 `UnityEngine` 兼容层直接执行原版托管类 `OldLevelGenerator + MarvinHexcellsSolver`，不加载 Unity、不启动游戏。
- Hard：纯 Python 精确移植原版 `LevelGenerator + Solver/Set`。
- 原版最终格子、公开/隐藏状态、数字/连续/非连续提示、花格和三方向行线索导入。
- 可缩放、平移、点击的独立棋盘。
- 未知 / 蓝色 / 排除三态手动同步，支持撤销和重置。
- 用户确认揭开格子后，自动显示该格在原版中刚出现的数字、连续/非连续或花格提示；撤销时一并恢复覆盖状态。
- 局部规则、排列、子集差分、剩余数和 CP-SAT 全局兜底。
- 一次只高亮一个必然步骤，并显示中文理由。
- 公开盘面与私有答案隔离；答案只用于测试核对，不参与推理。
- 生成在后台线程中运行，期间有明确加载、禁用和失败重试状态。

## 精确性边界

Easy/Hard 默认后端都不会启动游戏，也不是近似算法：

- Easy 只读取原版托管程序集，使用项目内的无 Unity 宿主直接执行生成器与 Marvin 求解器。
- Hard 已将生成器、`Solver/Set`、原版排序与 Unity RNG 行为移植为纯 Python。

Easy 托管程序集固定检查以下基线：

- Steam Build ID：`5455383`
- Unity：`5.6.3f1`
- 原始 `Assembly-CSharp.dll` SHA-256：`835DEC694D7685809EDAC963E0F47306AD4300C7D7C9C555AD457F20EFAA8083`

原 Steam 安装和原存档不会被修改。逆向与原版差分工具只存在于：

```text
D:\Desktop\HexInfinite\reverse_harness\game
```

当前验证结果：Easy/Hard seed 1–50 的最终 TSV 均逐字段一致，并额外通过 `00000000`、`99999999` 两个边界种子；Hard 样本覆盖五种地图形状。`0.4.1` 修正了 Unity 世界坐标到 Qt 画布时 Y 轴方向相反造成的棋盘上下镜像；`0.4.2` 同步交换了镜像后的左右斜向标签，避免标签方向指向错误的条件线。seed 1/2 已与现有官方截图逐个核对轮廓和线索方位。`reverse_harness` 中的原版运行时桥只保留为显式差分校验工具，不在默认产品链路中。

性能边界：Easy 通常不到 1 秒；Hard 会忠实重放原版的多轮可解性验证与冗余线索裁剪，小图约数秒，少数复杂种子可能需要几十秒。生成始终在 UI 后台线程中执行。

## 启动

直接双击 `启动求解器.cmd`。首次启动会自动创建项目环境、安装依赖并构建 Easy 托管核心，之后会先完成离线诊断再打开界面。

也可以在 PowerShell 中运行：

```powershell
cd D:\Desktop\HexInfinite\hexsolver_cn_py
.\run.cmd
```

也可以直接运行：

```powershell
.\.conda_env\python.exe main.py
```

新环境安装：

```powershell
conda create -y -n hexsolver-cn python=3.11
conda run -n hexsolver-cn python -m pip install -r requirements.txt
conda run -n hexsolver-cn python main.py
```

## 使用流程

1. 输入十进制种子号。
2. 选择“简单”或“困难”，点击“生成地图”。
3. 等待状态从“正在离线生成”变为“离线精确生成”。
4. 选择“未知 / 蓝色 / 排除”，点击棋盘格同步你在游戏中的当前进度。
5. 点击“计算下一步”。
6. 查看高亮目标、动作和中文理由；右侧勾选按钮可把建议应用到本地盘面。

中键拖动棋盘，滚轮缩放。右下角按钮可导入截图、撤销、重置、缩放和适合窗口。

## 诊断与测试

只检查离线核心、程序集版本和默认后端，不启动游戏：

```powershell
.\.conda_env\python.exe tools\doctor.py
```

离线生成 Easy/Hard seed 1，并核对第一条建议（仍不启动游戏）：

```powershell
.\.conda_env\python.exe tools\doctor.py --smoke-seed 1
```

逐步解完整个 seed，并逐步与私有答案核对：

```powershell
.\.conda_env\python.exe tools\doctor.py --smoke-seed 1 --full-replay
```

只验证某个难度可添加 `--difficulty easy` 或 `--difficulty hard`。

只有显式添加下面的参数，诊断工具才会启动隔离原版一次并做逐字段差分：

```powershell
.\.conda_env\python.exe tools\doctor.py --smoke-seed 1 --compare-original
```

执行自动测试：

```powershell
.\test.cmd
```

当前自动测试覆盖 TSV 合约、两套交错坐标相位、官方 Y 轴方向、Easy/Hard 样本、Unity RNG 位模式、默认后端不启动游戏、揭示/撤销、完整逐步回放、后台生成和 Qt 主流程。Easy/Hard seed 1–50 及两个八位边界种子已做原版逐字段差分；代表种子还会完整解到零未知格并逐步核对私有答案。

## 架构

```text
seed + difficulty
        |
        +--> Easy: headless managed core
        |          (OldLevelGenerator + Marvin)
        |
        +--> Hard: pure Python port
                   (LevelGenerator + Solver/Set)
        |
        v
public board + private answer
        |
        v
InteractivePuzzleSession
        |
        v
HexReasoningSolver.next_step()
        |
        v
方案 2 UI：目标格 + 动作 + 中文理由
```

主要文件：

- `src/hexsolver_cn/app.py`：双栏桌面界面、后台生成与交互编排。
- `src/hexsolver_cn/managed_easy.py`：Easy 无 Unity 托管宿主后端，保证不启动游戏。
- `src/hexsolver_cn/hard_offline.py`：Hard 生成器与内置 `Solver/Set` 的纯 Python 精确移植。
- `src/hexsolver_cn/original_bridge.py`：TSV 解析、盘面转换，以及仅用于显式差分的原版隔离桥。
- `src/hexsolver_cn/board_view.py`：六边形 Qt 画布与行线索。
- `src/hexsolver_cn/solver.py`：确定性局部规则与 CP-SAT 兜底。
- `src/hexsolver_cn/session.py`：当前局面、剩余数、历史和撤销。
- `src/hexsolver_cn/unity_random.py`：Unity 5.6.3f1 RNG 位兼容实现。
- `src/hexsolver_cn/hard_generator.py`：Hard 初始形状、颜色与 Unity 随机序列。
- `managed_core/`：C# 最小 Unity API 兼容层、Easy 宿主和一键构建脚本。
- `tools/doctor.py`：离线后端诊断；原版启动差分必须显式启用。
