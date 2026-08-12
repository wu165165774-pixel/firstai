from fastapi import APIRouter

from app.retrieval.schemas import DualRetrievalRequest, DualRetrievalResult
from app.retrieval.service import dual_path_retriever


router = APIRouter(prefix="/retrieval")


@router.post("/fused", response_model=DualRetrievalResult)
async def retrieve_fused_evidence(
    payload: DualRetrievalRequest,
) -> DualRetrievalResult:
    return await dual_path_retriever.retrieve(payload)

