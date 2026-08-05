import json
import re
from typing import Any

from loguru import logger

from app.llm.bootstrap import registry
from app.llm.manager import LLMManager
from app.llm.schemas import ChatMessage, ChatRequest

from app.memory.manager import memory_manager
from app.memory.schemas import MemoryItem, MemoryType


EXTRACTION_SYSTEM_PROMPT = """
你是 NovelForge 的长期记忆提取器。

你的任务是从用户本轮输入中提取值得长期保存的小说设定。

只允许提取用户明确提供的信息，禁止根据常识推测，禁止从模型回答中编造新设定。

可用的 memory_type：

- character：人物身份、性格、能力、关系、物品、经历
- world：地点、宗门、势力、世界规则、历史、功法体系
- plot：已经发生或明确计划发生的剧情事件
- short_term：临时状态、短期任务、当前场景信息

要求：

1. 没有值得保存的信息时，返回空数组 []。
2. 每条记忆只表达一个清晰事实。
3. importance 必须在 0 到 1 之间。
4. 核心人物身份、重要关系、重大世界规则可设为 0.8 到 1.0。
5. 普通设定可设为 0.5 到 0.8。
6. 临时信息可设为 0.2 到 0.5。
7. 只能返回合法 JSON 数组。
8. 不要输出 Markdown，不要解释。

返回格式：

[
  {
    "memory_type": "character",
    "content": "林凡随身携带一枚黑色玉佩。",
    "importance": 0.8,
    "metadata": {
      "source": "chat"
    }
  }
]

示例一：

用户输入：
林凡性格谨慎，是青云宗的外门弟子。

返回：
[
  {
    "memory_type": "character",
    "content": "林凡性格谨慎。",
    "importance": 0.8,
    "metadata": {
      "source": "chat"
    }
  },
  {
    "memory_type": "character",
    "content": "林凡是青云宗的外门弟子。",
    "importance": 0.9,
    "metadata": {
      "source": "chat"
    }
  }
]

示例二：

用户输入：
帮我续写这一章。

返回：
[]
""".strip()


class MemoryExtractor:

    def __init__(self):

        self.llm_manager = LLMManager(
            registry
        )

    @staticmethod
    def _get_result_content(
        result: Any
    ) -> str:

        if isinstance(result, dict):

            return str(
                result.get("content", "")
                or ""
            )

        if hasattr(result, "content"):

            return str(
                result.content
                or ""
            )

        return ""

    @staticmethod
    def _clean_json_text(
        text: str
    ) -> str:

        text = text.strip()

        # 去除 ```json ... ``` 或 ``` ... ```
        text = re.sub(
            r"^```(?:json)?\s*",
            "",
            text,
            flags=re.IGNORECASE
        )

        text = re.sub(
            r"\s*```$",
            "",
            text
        )

        text = text.strip()

        # 模型偶尔会在 JSON 前后添加说明，
        # 这里截取最外层数组。
        start = text.find("[")
        end = text.rfind("]")

        if start >= 0 and end >= start:

            return text[start:end + 1]

        return text

    @staticmethod
    def _parse_items(
        text: str
    ) -> list[dict]:

        cleaned = MemoryExtractor._clean_json_text(
            text
        )

        try:

            data = json.loads(
                cleaned
            )

        except json.JSONDecodeError as exc:

            logger.warning(
                "MemoryExtractor JSON parse failed: "
                f"{exc}; raw={text!r}"
            )

            return []

        if isinstance(data, dict):

            data = data.get(
                "memories",
                []
            )

        if not isinstance(data, list):

            logger.warning(
                "MemoryExtractor result is not a list: "
                f"{type(data).__name__}"
            )

            return []

        return [
            item
            for item in data
            if isinstance(item, dict)
        ]

    async def extract(
        self,
        user_id: str,
        novel_id: str,
        query: str,
        answer: str = "",
        provider: str = "qwen_local",
        model: str = "qwen3:8b"
    ):

        query = (
            query
            or ""
        ).strip()

        if len(query) < 2:

            logger.info(
                "MemoryExtractor skipped: query too short"
            )

            return []

        logger.info(
            "MemoryExtractor started: "
            f"user_id={user_id}, "
            f"novel_id={novel_id}, "
            f"provider={provider}, "
            f"query={query!r}"
        )

        extraction_request = ChatRequest(

            provider=provider,

            model=model,

            metadata={
                "user_id": user_id,
                "novel_id": novel_id,
                "task": "memory_extraction"
            },

            messages=[

                ChatMessage(
                    role="system",
                    content=EXTRACTION_SYSTEM_PROMPT
                ),

                ChatMessage(
                    role="user",
                    content=(
                        "请从下面的用户输入中提取长期记忆。\n\n"
                        f"用户输入：\n{query}"
                    )
                )

            ]

        )

        try:

            result = await self.llm_manager.chat(
                provider,
                extraction_request
            )

        except Exception:

            logger.exception(
                "MemoryExtractor LLM request failed"
            )

            return []

        raw_content = self._get_result_content(
            result
        )

        logger.info(
            "MemoryExtractor raw result: "
            f"{raw_content!r}"
        )

        items = self._parse_items(
            raw_content
        )

        saved_memories = []

        for item in items:

            memory_type_value = str(
                item.get(
                    "memory_type",
                    ""
                )
            ).strip()

            content = str(
                item.get(
                    "content",
                    ""
                )
            ).strip()

            if not content:

                continue

            try:

                memory_type = MemoryType(
                    memory_type_value
                )

            except ValueError:

                logger.warning(
                    "MemoryExtractor skipped invalid "
                    f"memory_type={memory_type_value!r}"
                )

                continue

            try:

                importance = float(
                    item.get(
                        "importance",
                        0.5
                    )
                )

            except (TypeError, ValueError):

                importance = 0.5

            importance = max(
                0.0,
                min(
                    importance,
                    1.0
                )
            )

            metadata = item.get(
                "metadata",
                {}
            )

            if not isinstance(metadata, dict):

                metadata = {}

            metadata.update({
                "source": "chat",
                "extractor": "llm",
                "provider": provider,
                "model": model
            })

            memory = MemoryItem(

                user_id=user_id,

                novel_id=novel_id,

                memory_type=memory_type,

                content=content,

                importance=importance,

                metadata=metadata

            )

            try:
                saved = await memory_manager.add_memory(
                    memory
                )

                saved_memories.append(
                    saved
                )

                logger.info(
                    "MemoryExtractor saved: "
                    f"id={saved.id}, "
                    f"type={saved.memory_type}, "
                    f"importance={saved.importance}, "
                    f"content={saved.content!r}"
                )

                # SQLite 保存成功后，同步写入或更新 FAISS。
                #
                # FAISS 失败不能影响 SQLite 主存储，
                # 因此单独捕获异常。索引可以后续通过 rebuild 恢复。

                saved = await memory_manager.add_memory(
                    memory
                )
                
                saved_memories.append(
                    saved
                )
                
                logger.info(
                    "MemoryExtractor saved: "
                    f"id={saved.id}, "
                    f"type={saved.memory_type}, "
                    f"importance={saved.importance}, "
                    f"content={saved.content!r}"
                )



            except Exception:

                logger.exception(
                    "MemoryExtractor failed to save: "
                    f"{content!r}"
                )

        logger.info(
            "MemoryExtractor finished: "
            f"extracted={len(items)}, "
            f"saved={len(saved_memories)}"
        )

        return saved_memories


memory_extractor = MemoryExtractor()