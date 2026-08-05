import re

from .storage.sqlite import SQLiteMemoryStorage


class MemoryRetriever:

    def __init__(self, storage: SQLiteMemoryStorage):

        self.storage = storage

    def extract_keyword(self, query: str):

        words = re.findall(
            r"[\u4e00-\u9fa5]{2,}",
            query
        )

        if words:
            return words[0]

        return query

    async def retrieve(
        self,
        user_id,
        novel_id,
        query,
        top_k=10
    ):

        keyword = self.extract_keyword(query)

        return await self.storage.search(
            user_id,
            novel_id,
            keyword,
            top_k
        )