from abc import ABC, abstractmethod


class BaseMemoryStorage(ABC):

    @abstractmethod
    async def save(
        self,
        memory
    ):
        pass

    @abstractmethod
    async def query(
        self,
        user_id,
        novel_id,
        memory_type=None
    ):
        pass

    @abstractmethod
    async def update(
        self,
        memory
    ):
        pass

    @abstractmethod
    async def find_duplicate(
        self,
        user_id,
        novel_id,
        memory_type,
        content
    ):
        pass