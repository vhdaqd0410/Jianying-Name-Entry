# 海外人名条批量生成（Jianying Name Entry）

在剪映专业版（Windows）中批量生成"海外人名条"竖版短视频的小工具。
带 Tkinter 界面，逐条替换字幕文字、导出、并把生成的 MP4 归置到指定目录。

## 功能

- **批量替换字幕文字**：在剪映编辑页中，对选中的字幕条逐条替换为英文名（真实键盘输入，剪映会真正提交到时间线素材）
- **自动导出**：Ctrl+M 触发导出，UIA 等待完成并自动关闭成功弹窗
- **文件归置**：导出文件按名字命名，移动到指定输出目录（默认桌面 `海外人名条\`）
- **强验证**：替换后读回确认文字真的被替换才导出，绝不带旧名字导出
- **名字来源**：手动输入 / CSV 导入（自动识别英文名列）/ TXT 导入 / 粘贴
- **断点续跑**：单个名字失败自动跳到下一个，结束汇总成功/失败名单

## 快速使用（单文件 exe）

> 不想装 Python 环境的话，直接下载打包好的**单文件 exe** 即可运行，双击即用、自带图标。

1. 到本仓库的 [Releases](https://github.com/vhdaqd0410/Jianying-Name-Entry/releases) 页面下载最新版本的 `海外人名条批量生成.exe`
2. 双击运行
3. 打开剪映专业版，进入你的草稿项目，选中字幕条
4. 输入/导入名字 → 设置输出目录 → 点"开始批量"

## 运行环境（源码运行）

- Windows + 剪映专业版
- Python 3.9+（仅需 `uiautomation` 依赖）

## 安装

```bash
pip install -r requirements.txt
```

## 使用（源码运行）

1. 打开剪映专业版，进入你的草稿项目
2. **选中字幕条**（时间轴上点一下字幕）
3. 启动程序：

```bash
pythonw gui_batch.pyw
```

或双击 `启动海外人名条.bat`。

4. 按界面提示：输入/导入名字 → 设置输出目录 → 点"开始批量"

## 从源码打包 exe

需要先安装打包依赖：

```bash
pip install pyinstaller
```

然后运行：

```bash
python -m PyInstaller gui_batch.spec --noconfirm
```

生成物在 `dist/海外人名条批量生成.exe`（单文件、嵌入图标、带版本信息）。

## 目录结构

```
Jianying-Name-Entry/
├── gui_batch.pyw              # 主界面程序
├── gui_batch.spec             # PyInstaller 打包配置（onefile + 图标）
├── 启动海外人名条.bat          # 双击启动
├── icon.ico / icon.png        # 程序图标
├── make_icon.py               # 图标生成脚本
├── version_info.txt           # exe 版本信息
├── requirements.txt
└── src/pyJianYingDraft/       # 剪映控制库（精简自包含版）
    ├── __init__.py
    ├── exceptions.py
    └── jianying_controller.py # 窗口查找 / 导出完成等待
```

## 说明

- 文字替换使用真实键盘输入（点击 → Ctrl+A → Delete → 粘贴），而非 UIA SetValue（那只是显示层假替换，剪映导出时会回退）。
- 导出完成后默认**不最小化**剪映窗口。
- 控制器精简自 [capcut-mate](https://github.com/Hommy-master/capcut-mate)，仅保留导出所需能力，独立运行。

## License

Apache-2.0
