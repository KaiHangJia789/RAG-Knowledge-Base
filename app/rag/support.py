"""受校验的技术支持输出与有界查询改写。"""
import asyncio
import json
import logging
import re
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.llm.client import LLMUsage
from app.llm.support_prompts import REWRITE_SYSTEM
from app.rag.models import AnswerStatus

logger = logging.getLogger("rag_api.rag.support")
SUPPORT_PARSER_VERSION = "support_reply_v2"
REWRITE_TIMEOUT_SECONDS = 8
INSUFFICIENT_MESSAGE = "当前资料不足以给出可靠的处理方案，请补充相关产品文档或脱敏后的错误信息。"
# 字面保护针对常见诊断标识，不代替语义评测；不跨中文标点吞并问题。
_LITERAL = re.compile(
    r"`[^`]+`"
    r"|https?://[A-Za-z0-9_~.@%+:/?=&\\#-]+"
    r"|(?:[A-Za-z]:[\\/]|\.\.?/|/)[A-Za-z0-9_~.@%+:/\\-]+"
    r"|[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+(?:=[A-Za-z0-9_.:/\\-]+)?"
    r"|(?<![A-Za-z0-9])v?\d+\.\d+(?:\.\d+)*(?:-[A-Za-z0-9]+(?:[.-][A-Za-z0-9]+)*)?(?:\+[A-Za-z0-9.-]+)?"
    r"|[A-Z][A-Z0-9]*(?:[-_][A-Z0-9]+)+"
    r"|[A-Z][A-Z0-9_]{2,}"
    r"|(?<![A-Za-z0-9])\d{3,5}(?![A-Za-z0-9])"
    r"|[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+"
)


_DIAGNOSTIC_TOKEN = re.compile(r"`[^`]+`|[A-Za-z0-9_~.@%+:/\\?=&\#-]+")


def diagnostic_literals(text: str) -> set[str]:
    # 用完整词元比较，避免 1.2.3 匹配 1.2.30，或 E-1001 匹配 E-1001x。
    tokens = (m.group(0).rstrip(".,;!?") for m in _DIAGNOSTIC_TOKEN.finditer(text))
    return {token for token in tokens if _LITERAL.search(token)}


class SupportReply(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    status: AnswerStatus
    answer: str = Field(min_length=1, max_length=12000)
    clarifying_questions: list[str] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def consistent_questions(self):
        if self.status == "needs_clarification":
            if not self.clarifying_questions or any(not q.strip() or len(q) > 300 for q in self.clarifying_questions):
                raise ValueError("澄清必须提供 1～2 个非空问题")
        elif self.clarifying_questions:
            raise ValueError("其他状态不应附带澄清问题")
        return self


def parse_support_answer(text: str) -> SupportReply:
    return SupportReply.model_validate_json(text)


@dataclass
class RewriteOutcome:
    query: str
    attempted: bool = False
    failed: bool = False
    usage: LLMUsage | None = None


async def rewrite_query(llm, question: str, history: list[dict] | None) -> RewriteOutcome:
    outcome = RewriteOutcome(query=question)
    if not history:
        return outcome
    # 白名单角色与长度预算；不把原始历史写入日志。
    bounded = []
    remaining = 12000
    for message in reversed(history[-10:]):
        if message.get("role") not in ("user", "assistant"):
            continue
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        clipped = content[:min(3000, remaining)]
        bounded.append({"role": message["role"], "content": clipped})
        remaining -= len(clipped)
        if remaining <= 0:
            break
    if not bounded:
        return outcome
    outcome.attempted = True
    try:
        response = await asyncio.wait_for(llm.generate(
            system=REWRITE_SYSTEM,
            user_message=json.dumps({"history": list(reversed(bounded)), "question": question}, ensure_ascii=False),
            max_tokens=600, thinking_enabled=False, temperature=0.0, json_mode=True,
        ), timeout=REWRITE_TIMEOUT_SECONDS)
        outcome.usage = response.usage
        payload = json.loads(response.text)
        query = payload.get("query") if isinstance(payload, dict) else None
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 2000:
            raise ValueError("invalid rewrite")
        query = query.strip()
        if not diagnostic_literals(question).issubset(diagnostic_literals(query)):
            raise ValueError("rewrite lost a literal")
        outcome.query = query
    except Exception as exc:
        # 只记录错误类型，SDK 错误消息也可能包含请求内容。
        logger.warning("查询改写回退: %s", type(exc).__name__)
        outcome.failed = True
    return outcome
