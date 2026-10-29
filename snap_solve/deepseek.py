"""Small, dependency-free DeepSeek Chat Completions client."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
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


class StreamCancelled(Exception):
    pass


def _request_stream(api_key: str, prompt: str, image_png: bytes,
                    on_update: Callable[[str], None], max_tokens: int = 6144,
                    cancelled: Callable[[], bool] = lambda: False,
                    thinking: str = "disabled", reasoning_effort: str | None = None) -> str:
    base_url = setting("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    if not base_url.startswith("https://"):
        raise DeepSeekError("API 地址必须使用 HTTPS")
    if not image_png:
        raise DeepSeekError("截图为空，请重新选择区域")
    encoded = base64.b64encode(image_png).decode("ascii")
    request_body = {
        "model": setting("DEEPSEEK_MODEL", "deepseek-flash"),
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}", "detail": "original"}},
        ]}],
        "stream": True,
        "thinking": {"type": thinking},
        "max_tokens": max_tokens,
    }
    if reasoning_effort:
        request_body["reasoning_effort"] = reasoning_effort
    payload = json.dumps(request_body).encode("utf-8")
    req = Request(
        f"{base_url}/chat/completions", data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    answer = ""
    completed = False
    try:
        with urlopen(req, timeout=90) as response:
            for raw in response:
                if cancelled():
                    raise StreamCancelled()
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    completed = True
                    break
                try:
                    chunk = json.loads(data)
                    choice = chunk.get("choices", [{}])[0]
                    if choice.get("finish_reason") == "length":
                        raise DeepSeekError("输出达到长度上限，请缩小截图范围后重试")
                    delta = choice.get("delta", {}).get("content") or ""
                except (ValueError, TypeError, IndexError, AttributeError) as exc:
                    raise DeepSeekError("API 流式响应格式异常") from exc
                if delta:
                    answer += delta
                    on_update(answer)
    except HTTPError as exc:
        try:
            message = json.load(exc).get("error", {}).get("message", "请求失败")
        except (ValueError, AttributeError):
            message = "请求失败"
        raise DeepSeekError(f"DeepSeek API 返回 {exc.code}：{message}") from exc
    except URLError as exc:
        raise DeepSeekError(f"网络连接失败：{exc.reason}") from exc
    except TimeoutError as exc:
        raise DeepSeekError("请求超时，请稍后重试") from exc
    if not completed or not answer.strip():
        raise DeepSeekError("API 未返回完整内容，请稍后重试")
    return answer.strip()


def transcribe_stream(api_key: str, image_png: bytes, on_update: Callable[[str], None],
                      cancelled: Callable[[], bool] = lambda: False) -> str:
    return _request_stream(api_key, TRANSCRIBE_PROMPT, image_png, on_update,
                           max_tokens=4096, cancelled=cancelled, thinking="disabled")


def solve_stream(api_key: str, markdown: str, image_png: bytes,
                 on_update: Callable[[str], None],
                 cancelled: Callable[[], bool] = lambda: False) -> str:
    effort = setting("DEEPSEEK_SOLVE_EFFORT", "high")
    if effort not in ("low", "high", "max"):
        raise DeepSeekError("DEEPSEEK_SOLVE_EFFORT 只能是 low、high 或 max")
    return _request_stream(api_key, SOLVE_PROMPT + markdown, image_png, on_update,
                           max_tokens=16384, cancelled=cancelled,
                           thinking="enabled", reasoning_effort=effort)

