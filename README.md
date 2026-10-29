# Snap Solve

面向 Windows 的截图转 Markdown 与解题工具。可选择持续监测固定区域，画面变化并稳定约 1.5 秒后自动转写；关闭「持续监测」则每次框选只识别那一张截图。勾选「同时解题」时，题解显示在第二个文本框中；关闭时仅显示题目框。两个文本框均可编辑和复制源码。

## 使用

安装 Release 中的 Windows 安装包。首次启动点击「设置」填写 [DeepSeek API Key](https://platform.deepseek.com/)，也可在源码目录的 `.env` 中填写 `DEEPSEEK_API_KEY`。应用内填写的 Key 保存在 Windows 凭据管理器中；`.env` 不提交到 Git。

点击「选择屏幕区域」后，在任意一块显示器上拖动选区；按 Esc 取消。开启「持续监测」时，选区保持在屏幕上，每次画面变化并稳定约 1.5 秒会更新 Markdown。关闭「持续监测」时，选区立即识别一次；再次点击可读取另一张截图。默认全局快捷键为 `Ctrl+Alt+S`，可以在「设置」中修改；如果快捷键已被其他程序占用，应用会在状态栏提示并仅在窗口中响应。

Windows 10 2004 及更新版本中，应用窗口会从系统截图中排除，因此即使它盖在题目上，读取到的仍是下面的画面。旧版 Windows 会在可行时自动把窗口移出选区。

所选截图会发送至 DeepSeek API。题目转写关闭思考模式并通过流式响应边生成边显示；开启解题时，再将题目和原截图交给高强度推理单独解答。可在 `.env` 中把 `DEEPSEEK_SOLVE_EFFORT` 改为 `max`，用于更难的题目。识别与解题依赖网络和 API 余额，复杂图形及模糊文字请人工核对。

## 源码运行

需要 Windows 和 Python 3.10 或更高版本。

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m snap_solve
```

`.env.example` 展示可配置项：`DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`、`DEEPSEEK_SOLVE_EFFORT`。默认模型为支持图片输入的 `deepseek-flash`。

## 构建安装包

安装 [Inno Setup 6](https://jrsoftware.org/isinfo.php)，然后执行 `powershell -ExecutionPolicy Bypass -File .\build.ps1`。生成的安装包位于 `release` 目录。

