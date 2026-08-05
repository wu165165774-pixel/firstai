from abc import ABC, abstractmethod

from .models import MemoryItem


class BaseMemoryBackend(ABC):


    @abstractmethod
    async def save(
        self,
        memory: MemoryItem
    ):
        pass



    @abstractmethod
    async def search(
        self,
        query:str,
        limit:int=5
    ):
        pass