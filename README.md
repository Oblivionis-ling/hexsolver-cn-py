# Hexcells 中文求解助手（Python 版）

当前版本：`0.1.0`

这是一个仿照 `HexSolver` 技术路线重写的 Python 原型，核心目标是：

- 不直接抓游戏窗口，而是先导入一张截图
- 自动识别六边形棋盘位置
- 自动识别棋盘中的蓝格/黑格提示
- 自动填充外侧行线索 OCR 和顶部 `REMAINING`
- 提供中文界面和更适合补录线索的工作台
- 在求解时给出“哪些格子当前可以安全判蓝/判黑”以及对应理由
- 直接在截图上叠加“可开（蓝）/应标黑”的解题建议

其中：
- `可开（蓝）` 表示这个格子当前可以安全点开
- `应标黑` 表示这个格子当前必须标成黑格，不能点开

## 当前版本已经完成的能力

- 使用工作区本地 `conda` 环境运行
- 导入 `Hexcells` / `Hexcells Infinite` 截图
- 自动识别橙色未知格，并推断整个六边形网格
- 支持不同分辨率截图，已经适配工作区里的 `test/3-1.png` 和 `test/31.png`
- 自动把格子分成：橙色未知、蓝色已知、黑色已知、浅灰不可用
- 自动识别蓝格和黑格里的数字提示
- 自动识别并预填一批高可信外侧行线索 OCR
- 自动识别并预填顶部 `REMAINING`
- 提供更大的中文界面、线索补录表和截图叠图
- 提供“检查台”：
  - 选中行线索 / 格内线索 / OCR 框后显示局部放大图
  - 支持把选中的 OCR 框一键绑定到行线索
  - 支持把选中的 OCR 框一键绑定到格内线索
  - 支持把选中的 OCR 框直接设为 `REMAINING`
- 支持导出当前画面上的叠图结果
- 求解时输出：
  - 必须判蓝的格子
  - 必须判黑的格子
  - 每一步对应的中文理由

## 目前的现实限制

- 外侧行线索 OCR 仍然不是百分之百准确，所以仍然建议人工检查
- 当前策略会优先“少错”而不是“强行把每一条都填满”
  - 也就是说，没有把握的行线索会宁可留空，交给你在检查台里快速补
- 对截图的要求是：
  - 游戏画面尽量完整
  - 不要有缩放模糊
  - 最好和原版风格接近
- 这是一版“可运行的中文原型”，优先保证流程通、自动预填和理由正确，不追求一步到位的 OCR 完美率

## 运行方式

如果环境已经创建好，直接运行：

```cmd
启动程序.cmd
```

如果你想从头重建这个独立环境，可以直接运行：

```cmd
重建环境.cmd
```

或者手工运行：

```cmd
conda activate D:\Desktop\HexInfinite\hexsolver_cn_py\.conda_env
python D:\Desktop\HexInfinite\hexsolver_cn_py\main.py
```

## 建议操作顺序

1. 点击“导入截图”
2. 点击“自动识别 + OCR”
3. 先到“检查台”确认当前选中的对象和局部放大图
4. 在“行线索”页先检查自动识别出的外侧行线索
5. 如果 OCR 框和线索对得上，先分别选中它们，再用“将所选 OCR 用于行 / 格 / REMAINING”
6. 如有需要，双击右侧已知蓝格/黑格，修正格内线索
7. 检查 `REMAINING` 是否正确
8. 点击“开始求解”，右侧截图会直接叠加结果

## 主要文件

- `main.py`
- `VERSION`
- `PROJECT_ROUTE.md`
- `requirements.txt`
- `pyproject.toml`
- `重建环境.cmd`
- `启动程序.cmd`
- `创建GitHub仓库.cmd`
- `同步到GitHub.cmd`
- `安装自动同步Hook.cmd`
- `升级版本.cmd`
- `src/hexsolver_cn/app.py`
- `src/hexsolver_cn/detector.py`
- `src/hexsolver_cn/ocr.py`
- `src/hexsolver_cn/solver.py`
- `src/hexsolver_cn/models.py`

## GitHub 同步

项目建议使用 `main` 分支，并通过 `post-commit` hook 做提交后自动同步。

如果本机没有 GitHub CLI，可以用 GitHub Token 创建私有仓库：

```powershell
$env:GITHUB_TOKEN="ghp_xxx"
.\创建GitHub仓库.cmd
```

首次配置远端仓库后运行：

```cmd
安装自动同步Hook.cmd
```

手动提交并推送可以运行：

```cmd
同步到GitHub.cmd -Message "Update project"
```

如果 `git push` 被网络连接挡住，脚本会自动改用 GitHub API 备用同步。

升级版本号可以运行：

```cmd
升级版本.cmd -Version 0.1.1 -Commit
```
