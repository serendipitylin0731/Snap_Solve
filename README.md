# Snap Solve

面向 Windows 的截图转 Markdown 与解题工具。拖动框选屏幕上的题目，应用使用 DeepSeek 视觉模型转写 Markdown；勾选「同时解题」时，题解显示在第二个文本框中。两个文本框均可编辑和复制源码。

## 使用

安装 Release 中的 Windows 安装包。首次启动点击「API 设置」填写 [DeepSeek API Key](https://platform.deepseek.com/)，也可在源码目录的 `.env` 中填写 `DEEPSEEK_API_KEY`。应用内填写的 Key 保存在 Windows 凭据管理器中；`.env` 不提交到 Git。

点击「选择屏幕区域」后，在任意一块显示器上拖动选区；按 Esc 取消。快捷键 `Ctrl+Shift+A` 仅在应用窗口处于焦点时可用。所选截图会发送至 DeepSeek API，解题模式会再次发送截图和题目文本。识别与解题依赖网络和 API 余额，复杂图形及模糊文字请人工核对。

## 源码运行

需要 Windows 和 Python 3.10 或更高版本。

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m snap_solve
```

`.env.example` 展示可配置项：`DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`DEEPSEEK_MODEL`。默认模型为支持图片输入的 `deepseek-flash`。

## 构建安装包

安装 [Inno Setup 6](https://jrsoftware.org/isinfo.php)，然后执行 `powershell -ExecutionPolicy Bypass -File .\build.ps1`。生成的安装包位于 `release` 目录。

