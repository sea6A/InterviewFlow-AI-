"""
DashScope 文本模型客户端。

这个文件的价值在于把“HTTP 请求细节”藏起来，
让上层业务只关心一件事：

`给模型一组 messages，拿回一段文本`

这样做的好处是：
- 业务层更干净
- 以后如果换 base_url、换模型、改超时，只改这里
- 更容易加日志、重试、监控
"""

from typing import Literal

import httpx


# 这里限制 role 的可选值，可以减少拼写错误。
ChatRole = Literal["system", "user", "assistant"]


class DashScopeClient:
    """
    一个很薄的 DashScope 文本模型封装。

    当前只保留了一个最核心的方法：`chat()`
    原因很简单：
    - 当前项目的文本模型需求主要是 prompt -> text
    - 不需要在业务层到处手写 HTTP 细节
    """

    def __init__(self, api_key: str, base_url: str, chat_model: str) -> None:
        self.api_key = api_key

        # 去掉结尾的 `/`，避免后面拼 URL 时出现双斜杠。
        self.base_url = base_url.rstrip("/")
        self.chat_model = chat_model

    async def chat(self, messages: list[dict[str, ChatRole | str]]) -> str:
        """
        调用 DashScope 的兼容模式 Chat Completions 接口。

        参数 messages 沿用 OpenAI 兼容格式：
        - system：角色设定 / 规则
        - user：用户输入
        - assistant：历史助手回复

        返回值只取最常用的那一段文本内容，
        不把完整 HTTP 响应结构继续往上层传播。
        """

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.chat_model,
                    "messages": messages,
                    "temperature": 0.4,
                    "stream": False,
                },
            )

        # 如果不是 2xx，会直接抛异常。
        # 这样上层可以更早知道请求失败，而不是拿到一份半残缺数据。
        response.raise_for_status()
        data = response.json()

        # 这里按 OpenAI 兼容格式取出文本内容。
        # 如果字段缺失，则返回空字符串，避免直接 KeyError。
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")
