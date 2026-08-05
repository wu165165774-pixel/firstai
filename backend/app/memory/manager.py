from .storage.sqlite import SQLiteMemoryStorage
from .retriever import MemoryRetriever

class MemoryManager:

    def __init__(self):

        self.storage = {
            "sqlite": SQLiteMemoryStorage()
        }
        
        self.retriever = MemoryRetriever(

            self.storage["sqlite"]

        )   


    async def get_memory(
        self,
        user_id,
        novel_id,
        memory_type=None
    ):

        return await self.storage["sqlite"].query(
            user_id,
            novel_id,
            memory_type
        )

    async def delete_memory(
        self,
        memory_id
    ):

        return await self.storage["sqlite"].delete(
            memory_id
        )

    async def add_memory(
        self,
        memory
    ):

        duplicate = await self.storage["sqlite"].find_duplicate(
            memory.user_id,
            memory.novel_id,
            memory.memory_type,
            memory.content
        )

        if duplicate:

            from datetime import datetime

            print("\n========== DUPLICATE ==========")
            print("Existing:", duplicate.id)
            print("===============================\n")

            duplicate.hit_count += 1

            duplicate.importance = max(
                duplicate.importance,
                memory.importance
            )

            duplicate.updated_at = datetime.utcnow()

            duplicate.last_accessed_at = datetime.utcnow()

            if memory.metadata:
                duplicate.metadata.update(memory.metadata)

            return await self.storage["sqlite"].update(
                duplicate
            )
  

        return await self.storage["sqlite"].save(
            memory
        )


    async def update_memory(
        self,
        memory
    ):

        return await self.storage["sqlite"].update(
            memory
        )


    async def find_duplicate(
        self,
        user_id,
        novel_id,
        memory_type,
        content
    ):

        return await self.storage["sqlite"].find_duplicate(
            user_id,
            novel_id,
            memory_type,
            content
        )

    async def retrieve_memory(
    
        self,
    
        user_id,
    
        novel_id,
    
        query,
    
        top_k=10
    
    ):
    
        return await self.retriever.retrieve(
        
            user_id,
    
            novel_id,
    
            query,
    
            top_k
    
        )



memory_manager = MemoryManager()