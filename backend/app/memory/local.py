from .base import BaseMemory
from .schemas import MemoryItem



class LocalMemory(BaseMemory):


    def __init__(self):

        self.items = []



    async def add(
        self,
        memory: MemoryItem
    ):

        self.items.append(
            memory
        )

        return memory



    async def search(
        self,
        query:str,
        limit:int=5
    ):

        result = []


        for item in self.items:

            if query.lower() in item.content.lower():

                result.append(item)



        return result[:limit]



    async def delete(
        self,
        memory_id:str
    ):

        self.items = [

            item
            for item in self.items
            if item.id != memory_id

        ]

        return True