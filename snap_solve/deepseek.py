"""Small, dependency-free DeepSeek Chat Completions client."""

from __future__ import annotations

import base64
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import setting


TRANSCRIBE_PROMPT = """请准确读取截图内容，并只输出 Markdown 源码。
保留题号、段落、列表、表格和代码；数学公式用 LaTeX（行内 $...$，独立 $$...$$）。
截图若包含图形、坐标轴或几何图，请简洁描述与题意相关的信息。
不添加解答，不编造看不清的内容；无法辨认处标记为 [无法辨认]。
不要使用包住整份结果的 Markdown 代码围栏。"""

SOLVE_PROMPT = """请解答下面从截图转写的题目。截图也会附上供你核对图形与符号。
只输出 Markdown 格式题解，说明关键步骤，公式使用 LaTeX。若存在多道题，请依题号分别解答。
如题意不完整，请明确指出缺失信息并给出可确定的部分，不要猜测。
不要再次抄写完整题目，也不要用代码围栏包住整份结果。\n\n题目：\n"""


class DeepSeekError(Exception):
    pass


def _request(api_key: str, prompt: str, image_png: bytes | None = None) -> str:
    base_url = setting("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    if not base_url.startswith("https://"):
        raise DeepSeekError("API 地址必须使用 HTTPS")
    model = setting("DEEPSEEK_MODEL", "deepseek-flash")
    content: str | list[dict] = prompt
    if image_png is not None:
        if not image_png:
            raise DeepSeekError("截图为空，请重新选择区域")
        encoded = base64.b64encode(image_png).decode("ascii")
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}", "detail": "original"}},
        ]
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "stream": False,
        "max_tokens": 8192,
    }).encode("utf-8")
    req = Request(
        f"{base_url}/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=120) as response:
            data = json.load(response)
    except HTTPError as exc:
        try:
            details = json.load(exc)
            message = details.get("error", {}).get("message", "请求失败")
        except (ValueError, AttributeError):
            message = "请求失败"
        raise DeepSeekError(f"DeepSeek API 返回 {exc.code}：{message}") from exc
    except URLError as exc:
        raise DeepSeekError(f"网络连接失败：{exc.reason}") from exc
    except TimeoutError as exc:
        raise DeepSeekError("请求超时，请稍后重试") from exc
    try:
        choice = data["choices"][0]
        answer = choice["message"]["content"]
        if choice.get("finish_reason") == "length":
            raise DeepSeekError("输出达到长度上限，请缩小截图范围后重试")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("empty content")
        return answer.strip()
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise DeepSeekError("API 响应格式异常，请稍后重试") from exc


def transcribe(api_key: str, image_png: bytes) -> str:
    return _request(api_key, TRANSCRIBE_PROMPT, image_png)


def solve(api_key: str, markdown: str, image_png: bytes) -> str:
    return _request(api_key, SOLVE_PROMPT + markdown, image_png)

