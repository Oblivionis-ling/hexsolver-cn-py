# Hexsolver CN

当前版本：`0.1.0`

这是一个面向 `Hexcells Infinite` 的中文截图求解工作台。项目先导入截图，再识别棋盘、OCR 读取线索、允许人工校对，最后给出当前可以安全操作的格子和中文理由。

## 主要能力

- 导入 `Hexcells` / `Hexcells Infinite` 截图。
- 自动识别六边形棋盘、未知格、蓝格、黑格和不可用格。
- 自动尝试识别格内线索、外侧行线索和顶部 `REMAINING`。
- 在 OCR 不确定时保留候选框，方便人工检查和补录。
- 使用约束求解器给出“可开蓝格”和“应标黑格”。
- 在原截图上叠加求解建议，便于对照游戏操作。

## 安装与运行

建议使用 Python 3.11。

```powershell
python -m pip install -r requirements.txt
python main.py
```

如果使用 Conda，可以先创建独立环境：

```powershell
conda create -y -n hexsolver-cn python=3.11
conda activate hexsolver-cn
python -m pip install -r requirements.txt
python main.py
```

## 使用流程

1. 点击“导入截图”。
2. 点击“自动识别 + OCR”。
3. 检查自动识别出的格内线索、行线索和 `REMAINING`。
4. 对 OCR 没有把握的项目进行人工补录。
5. 点击“开始求解”。
6. 在右侧截图叠图中查看可开格子、应标黑格和对应理由。

## 项目目录

```text
hexsolver_cn_py/
  main.py                         程序入口
  README.md                       项目说明
  ROADMAP.md                      项目技术路线
  OCR_PLAN.md                     OCR 优化计划
  SOLVER_ALGORITHM.md             求解算法说明
  VERSION                         当前版本号
  pyproject.toml                  Python 项目配置
  requirements.txt                运行依赖
  src/
    __init__.py
    hexsolver_cn/
      __init__.py                 包版本信息
      app.py                      中文桌面界面、截图叠图、人工校对入口
      detector.py                 截图分析、棋盘几何识别、线索候选匹配
      models.py                   棋盘、格子、线索等数据模型
      ocr.py                      模板 OCR、RapidOCR 封装和线索文本解析
      solver.py                   Hexcells 规则约束建模与求解
      assets/
        ocr_patterns/             游戏字体数字和符号模板
```

## 仓库规则

GitHub 仓库只保留项目源码、文档、配置和必要资源。

不会上传的内容包括：

- 本地 Conda 环境和虚拟环境。
- `__pycache__`、缓存、日志和构建产物。
- 本机调试截图、导出叠图和临时 OCR 调试结果。
- 本地使用的 `.cmd` 文件、同步脚本和仓库管理脚本。

这样做的目标是让 GitHub 仓库保持简单、可读、可复现，本机自动化工具则只服务于当前开发电脑。
