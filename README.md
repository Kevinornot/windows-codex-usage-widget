# Codex 中文玻璃监控器

一个面向 Windows 10/11 的轻量桌面悬浮组件，用于实时查看 Codex 会话、Token、上下文、账户限额和本机资源占用。界面采用中文液态玻璃风格，首次启动默认只显示官方额度；点击底部箭头即可展开完整面板，并在“上下文”卡右上角选择最近的 Codex 会话。

## 主要功能

- **当前模型**：模型名称、套餐、模型提供方、会话来源和最近活跃状态。
- **官方限额**：显示各限额窗口的已用比例、剩余比例和重置倒计时。
- **Token 用量**：输入、缓存输入、输出、推理、当前上下文和会话累计 Token。
- **可切换上下文**：在“上下文”卡右上角点击“会话 x/y”，从最近会话列表中选择目标会话；切换后模型、Token、工作目录和上下文用量同步更新。
- **系统资源**：CPU、内存、GPU 和显存实时占用。
- **账户活动**：今日 Token、累计 Token、连续使用天数和可用重置次数（服务返回时）。
- **默认额度模式**：平时仅显示额度窗口；需要时展开模型、Token、系统资源和上下文详情。
- **桌面交互**：无边框、置顶、拖动、透明度调整、托盘隐藏和开机启动。
- **本地只读**：不需要填写 API key，不读取认证文件，不显示或上传提示词与回答正文。

## 快速启动

### 使用便携包

从 GitHub Releases 下载 `windows-codex-usage-widget-portable.zip`，解压后双击 `run_widget.vbs`。便携包不包含账户、会话、设置、日志或设备信息。

### 运行源码版

1. 安装 **Python 3.11 或更高版本**。Windows 官方 Python 安装器通常自带 Tkinter。
2. 安装并登录 Codex CLI，在 CMD 中确认：

   ```bat
   codex --version
   ```

3. 解压本项目，双击：

   ```text
   run_widget.vbs
   ```

   它会静默启动，不保留命令行窗口。首次启动显示额度精简模式。

也可以从 CMD 启动：

```bat
run_widget.bat
```

演示模式使用内置数据，不读取本机 Codex 会话：

```bat
run_widget.bat --demo
```

仅查看本地会话和系统资源，不启动 Codex App Server：

```bat
run_widget.bat --no-app-server
```

## 界面操作

- **移动组件**：按住顶部标题栏拖动。
- **选择上下文会话**：在“上下文”卡右上角点击 `会话 x/y ▾`，选择最近会话。菜单同时显示会话时间、简短 ID、模型和项目目录。
- **滚动完整面板**：鼠标滚轮浏览较低位置的卡片；在高分辨率屏幕上通常可完整显示。
- **完整/简洁模式**：点击窗口底部的 `⌃/⌄`，或双击标题栏。简洁模式仅保留官方限额，便于长期悬浮。
- **隐藏到托盘**：点击右上角 `—`。点击托盘图标可恢复；右键可展开/收起或退出。
- **右键菜单**：立即刷新、切换较新/较旧会话、设置置顶、透明度和开机启动。
- **快捷键**：`Ctrl+R` 刷新；`Esc` 隐藏组件。

首次启动默认使用额度精简模式，每 2 秒刷新本地会话和系统资源，每 3 分钟刷新官方账户限额。收起态约为 `308x167`，展开宽度为 `462`，并会自动保持在屏幕可见区域内。之后会沿用用户上次保存的模式、所选会话和窗口位置。

## 给其他 Codex 用户

仓库的 `share` 目录提供：

- `windows-codex-usage-widget/`：可复制到 `%USERPROFILE%\.codex\skills\` 的 Skill；
- `INSTALL_PROMPT.md`：使用通用占位符的安装与定制提示词。

这些文件不包含私人姓名、设备昵称、本机路径、账户标识或真实使用数据。

## 生成单文件 EXE

在 Windows 中双击：

```text
build_exe.bat
```

脚本会建立独立的 `.venv-build` 环境，安装 PyInstaller，并生成：

```text
dist\CodexUsageWidget.exe
```

运行组件本身没有第三方 Python 依赖；只有打包 EXE 时需要联网安装 PyInstaller。生成的 EXE 可通过组件右键菜单直接加入开机启动。

## 数据来源

### 1. 本地 Codex 会话日志

组件只读扫描：

```text
%CODEX_HOME%\sessions\**\rollout-*.jsonl
```

未设置 `CODEX_HOME` 时使用：

```text
%USERPROFILE%\.codex\sessions
```

组件仅提取会话 ID、模型、模型提供方、工作目录、Token 统计、上下文窗口、时间戳和限额元数据。为避免读取大型会话正文，解析器只读取文件头部和尾部的有限区段。

### 2. Codex App Server

组件在后台调用本机已有的：

```text
codex app-server
```

并通过本地 JSON-RPC 请求账户信息、限额窗口和账户使用摘要。它复用 Codex 已登录身份，不要求输入或保存 API key。App Server 暂时不可用时，本地会话、上下文和系统资源仍可继续显示。

### 3. 本机系统资源

- **CPU 与内存**：Windows 系统 API；在 Linux 开发环境下使用 `/proc`。
- **NVIDIA GPU/显存**：优先调用本机 `nvidia-smi`。
- **AMD/Intel/其他 Windows GPU**：在 NVIDIA 工具不可用时尝试 Windows 性能计数器和显卡信息。
- 驱动或系统不提供某项数据时，该项显示 `—`，不会阻止其他指标更新。

为了降低额外开销，GPU/显存默认每约 5 秒采样一次；CPU、内存和会话数据按本地刷新周期更新。

## Token 与上下文口径

| 字段 | 含义 |
|---|---|
| **输入** | 最近一次模型调用的输入 Token。 |
| **缓存** | 最近一次调用中的缓存输入 Token。 |
| **输出** | 最近一次模型调用的输出 Token。 |
| **推理** | 最近一次调用中的推理输出 Token。 |
| **上下文** | 最近一次模型调用中进入上下文窗口的总 Token。 |
| **会话累计** | 当前会话多轮调用累计的 Token，可高于模型上下文窗口。 |

上下文卡显示两种比例：

- **Codex 调整后用量**：按 Codex 的显示口径，扣除固定系统提示、工具和压缩预留区后计算用户可控制部分的占用；
- **原始用量**：直接使用 `最近一次总 Token ÷ 模型上下文窗口`。

## 关于“限额”

账户接口提供的是限额窗口的**已用百分比、窗口时长和重置时间**，并不总是提供可换算的绝对 Token 总额度。因此组件准确显示“已用/剩余百分比和重置时间”，但不会虚构一个绝对 Token 上限。

仅 API key 或部分第三方模型提供方可能不返回 ChatGPT/Codex 账户活动摘要，此时“今日、累计、连续、重置”显示 `—`；官方限额和本地 Token 是否可用取决于当前身份模式和 Codex 版本。

## 隐私与安全

- 不请求、显示或保存 API key；
- 不读取 `auth.json` 等认证文件；
- 不修改 Codex 配置、会话文件或账户限额；
- 不显示、保存或上传提示词、回答和工具输出；
- 不把本地会话内容发送给第三方；
- 只保存窗口位置、透明度、显示模式、刷新开关和会话序号等 UI 设置。

设置文件位于：

```text
%APPDATA%\CodexUsageWidget\settings.json
```

## 常见问题

### 找不到 Codex CLI

在 CMD 中运行：

```bat
where codex
codex --version
```

Codex 位于自定义目录时，可在启动前指定：

```bat
set CODEX_BIN=C:\path\to\codex.cmd
run_widget.bat
```

### 模型或上下文为空

先在目标 Codex 会话中完成至少一次模型调用。刚创建但尚未运行的会话可能还没有 `turn_context` 或 `token_count` 数据。

### 上下文会话列表中找不到较早会话

下拉菜单优先展示最近的会话，以避免高频扫描大量历史文件。仍可通过右键菜单的“较新会话/较旧会话”切换当前可发现的会话。

### GPU 或显存显示 `—`

确认显卡驱动正常。NVIDIA 用户可先在 CMD 中运行：

```bat
nvidia-smi
```

部分集成显卡或远程桌面环境不会暴露实时 GPU/显存计数，这属于系统数据源限制。

### 关闭按钮为什么没有退出

右上角 `—` 默认隐藏到系统托盘，便于持续监控。需要完全退出时，使用右键菜单或托盘菜单中的“退出”。

## 开发与验证

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests run_widget.pyw
```

在 Linux 无桌面环境中验证 Tk 界面：

```bash
xvfb-run -a python -m unittest discover -s tests -v
```

项目结构：

```text
src/codex_usage_widget/
  models.py             数据模型与上下文计算
  rollout.py            本地 JSONL 只读解析与会话目录
  app_server.py         Codex App Server JSON-RPC 客户端
  system_resources.py   CPU、内存、GPU、显存采样
  coordinator.py        后台轮询、缓存与数据合并
  windows_effects.py    Windows 玻璃与圆角效果
  tray.py               Windows 原生托盘图标
  config.py             设置、配置回退和开机启动
  ui.py                 中文白色玻璃 Tkinter 界面
  main.py               程序入口与演示数据
```

## 兼容性

- 目标系统：Windows 10 / Windows 11
- Python：3.11+
- Codex：需要支持 `codex app-server` 才能读取官方账户限额；旧版仍可使用本地会话与系统资源监控

本项目是独立的本地辅助工具，不是 OpenAI 官方产品。
