from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from app.novel_exports.service import (
    NovelExportConflictError,
    NovelExportIntegrityError,
    NovelExportNotFoundError,
    NovelExportService,
)


router = APIRouter(prefix="/novels")
service = NovelExportService()


@router.get(
    "/{novel_id}/export",
    response_class=Response,
    responses={
        200: {
            "content": {"application/zip": {}},
            "description": "Verifiable NovelForge novel export archive.",
        },
        404: {"description": "Novel Project not found."},
        409: {"description": "Novel changed during export."},
    },
)
async def export_novel(novel_id: str) -> Response:
    try:
        bundle = service.export(novel_id)
    except NovelExportNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except NovelExportConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except NovelExportIntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Novel export integrity validation failed.",
        ) from exc

    return Response(
        content=bundle.content,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{bundle.filename}"'
            ),
            "X-NovelForge-Manifest-SHA256": bundle.manifest_sha256,
            "X-NovelForge-Export-Files": str(bundle.file_count),
            "X-NovelForge-Accepted-Chapters": str(
                bundle.accepted_chapter_count
            ),
        },
    )
