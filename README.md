# Snap Solve

面向 Windows 的截图转 Markdown 与解题工具。可选择持续监测固定区域，画面变化并稳定约 1.5 秒后自动处理；关闭「持续监测」则每次框选只处理那一张截图。「转写题目」和「解题」可分别开启，也可同时开启；仅解题时直接读取截图，仅显示题解框。结果框均可编辑和复制源码。

## 使用

安装 Release 中的 Windows 安装包。首次启动点击「设置」填写 [DeepSeek API Key](https://platform.deepseek.com/)，也可在源码目录的 `.env` 中填写 `DEEPSEEK_API_KEY`。应用内填写的 Key 保存在 Windows 凭据管理器中；`.env` 不提交到 Git。

点击「选择屏幕区域」后，在任意一块显示器上拖动选区；按 Esc 取消。选区会保持显示，可拖动四角和边缘调整大小，拖动顶部短横移动位置。开启「持续监测」时，选区画面变化并稳定约 1.5 秒后更新 Markdown；关闭「持续监测」时，选完或调整选区后识别一次。默认全局快捷键为 `Ctrl+Alt+S`，可以在「设置」中修改；如果快捷键已被其他程序占用，应用会在状态栏提示并仅在窗口中响应。

Windows 10 2004 及更新版本中，应用窗口会从系统截图中排除，因此即使它盖在题目上，读取到的仍是下面的画面。旧版 Windows 会在可行时自动把窗口移出选区。

所选截图会发送至 DeepSeek API。转写关闭思考模式并通过流式响应边生成边显示；解题时可拖动强度条选择低、高、最高三个等级，同时开启转写时会结合转写结果和原截图解答。勾选「只输出答案」会要求模型省略解析和推导，关闭后恢复关键步骤；选项会自动保存。首次使用的默认强度可在 `.env` 中通过 `DEEPSEEK_SOLVE_EFFORT` 设置，应用中选过的强度会记住并优先使用。题目和题解中的公式都要求使用行内 `$...$` 或独立 `$$...$$` 格式。识别与解题依赖网络和 API 余额，复杂图形及模糊文字请人工核对。

「设置」中可选择跟随系统、浅色或深色外观，也可开启「选区完成后将主窗口显示在最前」；该选项默认关闭。Windows 11 上，原生窗口标题栏会与应用背景使用相同的颜色。

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

