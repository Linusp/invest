"""Wind 的「能力型」接口：结构化数据工具与 Alice 分析工作流。

- 数据工具（``get_stock_*`` / ``search_stocks``）都接收自然语言 ``question``，
  返回结构化 JSON；单次调用计一次 Wind 额度，因此由调用方套缓存。
- Alice 走 A2A ``message/stream``，返回 Markdown 分析文本，属于非结构化产物。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from .base import ProviderError
from .wind import WindMcpClient


class WindSkillError(ProviderError):
    """Wind 能力型接口调用失败。"""


@dataclass(frozen=True)
class AliceSkill:
    zh: str
    en: str


ALICE_SKILLS: tuple[AliceSkill, ...] = (
    AliceSkill("通胀情景债券轮动策略", "Inflation Bond Strategy"),
    AliceSkill("宏观数据解读", "Macro Data Interpretation"),
    AliceSkill("按主题选股", "Thematic Stock Screening"),
    AliceSkill("债券利率走势研判", "Bond Rate Outlook"),
    AliceSkill("信用分析", "Credit Analysis"),
    AliceSkill("基金对比分析", "Fund Compare"),
    AliceSkill("基金筛选与投资建议", "Fund Screening & Investment Advisory"),
    AliceSkill("投资标的创意与筛选", "Investment Idea Generation"),
    AliceSkill("公司一页纸", "Company One-Page Investment Memo"),
    AliceSkill("上市公司调研问题清单", "Stock DD List"),
    AliceSkill("全球上市公司季报点评", "Global Share Quarterly Earnings Review"),
    AliceSkill("市场规模测算与战略建模", "Market Sizing & Strategic Modeling"),
    AliceSkill("可比公司分析", "Comps Analysis"),
    AliceSkill("事实核验", "Fact Check"),
)

# Wind 股票域里可用的能力型数据工具。
DATA_TOOLS = {
    "get_stock_summary",
    "get_stock_fundamentals",
    "get_stock_equity_holders",
    "get_risk_metrics",
    "get_stock_events",
    "get_stock_technicals",
    "search_stocks",
}


def resolve_alice_skill(value: str | None) -> AliceSkill | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip().lower().replace(" ", "")
    for skill in ALICE_SKILLS:
        if normalized in {
            skill.zh.lower().replace(" ", ""),
            skill.en.lower().replace(" ", ""),
        }:
            return skill
    raise WindSkillError(
        f"未知的 Alice 技能: {value}；可选: {', '.join(s.zh for s in ALICE_SKILLS)}"
    )


class WindDataTools:
    """调用 Wind 股票域的结构化数据工具。"""

    def __init__(self, api_key: str, client: WindMcpClient | None = None):
        self.api_key = api_key
        self._client = client or WindMcpClient(api_key, timeout=90)

    def call(self, tool: str, question: str) -> dict[str, Any]:
        if tool not in DATA_TOOLS:
            raise WindSkillError(f"不支持的数据工具: {tool}")
        if not question.strip():
            raise WindSkillError("question 不能为空")
        payload = self._client.call("stock", tool, {"question": question})
        return {"tool": tool, "question": question, "result": payload}


class WindAliceClient:
    """Wind Alice 分析工作流（A2A message/stream）。"""

    ENDPOINT = "https://mcp.wind.com.cn/skills/alice"

    def __init__(
        self,
        api_key: str,
        client: httpx.Client | None = None,
        timeout: float = 240.0,
    ):
        self.api_key = api_key
        self.timeout = timeout
        self.client = client or httpx.Client(timeout=timeout, trust_env=False)

    def run(self, prompt: str, skill: AliceSkill | None = None) -> str:
        prefix = f"使用「{skill.zh}」技能：" if skill is not None else ""
        message_id = str(uuid.uuid4())
        body = {
            "jsonrpc": "2.0",
            "method": "message/stream",
            "params": {
                "message": {
                    "messageId": message_id,
                    "role": "user",
                    "kind": "message",
                    "parts": [
                        {"kind": "text", "text": f"{prefix}{prompt}"},
                        {
                            "kind": "data",
                            "data": {
                                "chatMode": "12",
                                "originalChatMode": "4",
                                "switchMode": "auto",
                                "timezone": "Asia/Shanghai",
                            },
                            "metadata": {
                                "key": "Wind.WindSearch.ChatService.A2A",
                                "version": "1.0.0",
                            },
                        },
                    ],
                    "contextId": str(uuid.uuid4()),
                    "taskId": str(uuid.uuid4()),
                }
            },
            "id": message_id,
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "InvestService/0.1",
        }
        try:
            response = self.client.post(
                self.ENDPOINT, json=body, headers=headers, timeout=self.timeout
            )
        except httpx.HTTPError as exc:
            raise WindSkillError(f"Wind Alice 请求失败: {exc}") from exc
        if response.status_code == 401:
            raise WindSkillError("Wind Alice 鉴权失败（401）")
        if response.status_code == 429:
            raise WindSkillError("Wind Alice 触发限流（429）")
        response.raise_for_status()

        text = extract_alice_result(response.text)
        if not text:
            raise WindSkillError("Wind Alice 未返回分析结果")
        return text


def _event_blocks(payload: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in payload.replace("\r\n", "\n").split("\n\n"):
        data_lines = [
            line[5:].strip()
            for line in block.split("\n")
            if line.startswith("data:")
        ]
        if not data_lines:
            continue
        raw = "\n".join(data_lines)
        try:
            events.append(json.loads(raw))
        except ValueError:
            continue
    return events


def _collect_markdown(node: Any) -> str | None:
    """从 A2A 的 UI 组件树里收集 A2A.Markdown 的文本。"""
    chunks: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("componentName") == "A2A.Markdown":
                text = (value.get("properties") or {}).get("text")
                if isinstance(text, str):
                    chunks.append(text)
                elif isinstance(text, list):
                    chunks.extend(str(item) for item in text if isinstance(item, str))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(node)
    return "\n".join(chunk for chunk in chunks if chunk).strip() or None


def extract_alice_result(payload: str) -> str | None:
    """从 SSE 事件流里取 Alice 的结果。

    兼容两种形态：官方的 ``agentResult`` 数据块，以及 UI 组件树里的
    ``A2A.Markdown``。任务失败（state=failed）时抛出带服务端文案的错误。
    """
    value: Any = None
    failed = False
    failure_text: str | None = None

    for event in _event_blocks(payload):
        if event.get("error") is not None:
            raise WindSkillError(str(event["error"].get("message") or event["error"]))
        result = event.get("result") or {}
        if result.get("isError") is True:
            message = "\n".join(
                part.get("text", "")
                for part in result.get("content") or []
                if isinstance(part, dict)
            )
            raise WindSkillError(message or "Wind Alice 返回错误")

        kind = result.get("kind")
        if kind == "status-update":
            state = (result.get("status") or {}).get("state")
            if state == "failed":
                failed = True
                failure_text = _collect_markdown(result.get("status")) or failure_text
            continue
        if kind != "artifact-update":
            continue

        artifact = result.get("artifact") or {}
        if artifact.get("name") == "agentResult":
            for part in artifact.get("parts") or []:
                if isinstance(part, dict) and part.get("kind") == "data":
                    data = part.get("data") or {}
                    if data.get("data") is not None:
                        value = data["data"]
            continue
        text = _collect_markdown(artifact)
        if text:
            value = text

    if failed:
        detail = failure_text or (value if isinstance(value, str) else None)
        raise WindSkillError(detail or "Wind Alice 任务失败")
    if value is None:
        return None
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
