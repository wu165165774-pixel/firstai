from abc import ABC, abstractmethod
from typing import Any


class BaseMemoryStorage(ABC):
    """
    长期记忆存储后端的统一抽象接口。

    SQLite、内存存储或未来其他存储实现，
    都应该继承并实现这些方法。
    """

    @abstractmethod
    async def save(
        self,
        memory: Any,
    ) -> Any:
        """
        保存一条新记忆。
        """
        raise NotImplementedError

    @abstractmethod
    async def query(
        self,
        user_id: str,
        novel_id: str,
        memory_type: Any = None,
    ) -> list[Any]:
        """
        查询指定用户和小说下的记忆。
        """
        raise NotImplementedError

    @abstractmethod
    async def update(
        self,
        memory: Any,
    ) -> Any:
        """
        更新已有记忆。
        """
        raise NotImplementedError

    @abstractmethod
    async def delete(
        self,
        memory_id: str,
    ) -> Any:
        """
        根据 memory_id 删除记忆。
        """
        raise NotImplementedError

    @abstractmethod
    async def find_duplicate(
        self,
        user_id: str,
        novel_id: str,
        memory_type: Any,
        content: str,
    ) -> Any:
        """
        查找内容完全相同的记忆，用于精确去重。
        """
        raise NotImplementedError