from __future__ import annotations

import re

from .interfaces import QueryRoute


class QueryRouter:
    """Minimal Phase 1.5 query router.

    This deliberately uses simple deterministic rules. Phase 2 can replace the
    internals with policy-aware routing without changing the kernel contract.
    """

    _CHAT_PATTERNS = (
        "你好",
        "您好",
        "hello",
        "hi",
        "谢谢",
        "多谢",
        "thanks",
        "thank you",
    )
    _ENTERPRISE_HINTS = (
        "文档",
        "资料",
        "招标",
        "投标",
        "合同",
        "项目",
        "客户",
        "公司",
        "公众号",
        "制度",
        "方案",
        "版本",
        "依据",
        "引用",
        "文件",
        "知识库",
    )

    def route(self, query: str) -> QueryRoute:
        normalized = (query or "").strip()
        if not normalized:
            return QueryRoute("ordinary_chat", False, "empty query")

        lowered = normalized.lower()
        if len(normalized) <= 12 and lowered in self._CHAT_PATTERNS:
            return QueryRoute("ordinary_chat", False, "short greeting or acknowledgement")

        if any(hint in normalized for hint in self._ENTERPRISE_HINTS):
            return QueryRoute(
                "enterprise_retrieval",
                True,
                "query contains enterprise knowledge hints",
                "hybrid",
            )

        if re.search(r"[?？]|(什么|哪些|如何|怎么|多少|是否|有没有|请查|查一下|总结|对比)", normalized):
            return QueryRoute(
                "enterprise_retrieval",
                True,
                "question-like query; retrieve enterprise context when kernel is enabled",
                "hybrid",
            )

        return QueryRoute("ordinary_chat", False, "no enterprise retrieval signal")
