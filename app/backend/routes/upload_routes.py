"""
upload_routes_patched.py
Patches the original upload_routes.py to auto-trigger AI analysis
immediately after a drawing is successfully uploaded.

Change from original: adds background_tasks parameter and calls
POST /takeoff/drawings/{id}/analyze after saving the drawing record.
"""
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
import schemas
import models
from auth import get_current_user
from database import get_db
import aiofiles
import logging
import os
from pathlib import Path
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/uploads", tags=["Uploads"])

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "tiff", "tif"}


def _tiles_dir(project_id: int, drawing_id: int) -> Path:
    return UPLOAD_DIR / str(project_id) / "tiles" / str(drawing_id)


def _generate_tiles(drawing_id: int, project_id: int, file_path: str):
    """
    Background task: build the Deep Zoom tile pyramid (tiling.py) so
    DrawingRenderer can view this sheet without OOM-ing on a full-resolution
    canvas. Best-effort — a failure here shouldn't affect the upload or AI
    analysis, and is a clean 503 to the tile-status endpoint until it
    succeeds (or forever, if PIL isn't installed — see tiling.py).
    """
    from tiling import generate_tile_pyramid, tiling_available

    if not tiling_available():
        return
    try:
        output_dir = _tiles_dir(project_id, drawing_id)
        meta = generate_tile_pyramid(file_path, str(output_dir))
        logger.info(f"[Tiling] Generated {meta['max_level']+1} levels for drawing_id={drawing_id}")
    except Exception as tile_err:
        logger.warning(f"[Tiling] Failed for drawing_id={drawing_id}: {tile_err}")

def get_file_extension(filename: str) -> str:
    return filename.rsplit(".", 1)[1].lower() if "." in filename else ""

def is_allowed_file(filename: str) -> bool:
    return get_file_extension(filename) in ALLOWED_EXTENSIONS


@router.post("/project/{project_id}/drawings", response_model=schemas.Drawing)
async def upload_drawing(
    project_id: int,
    background_tasks: BackgroundTasks,          # ← NEW
    file: UploadFile = File(...),
    sheet_name: Optional[str] = Form(None),
    scale: Optional[str] = Form(None),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    project = db.query(models.Project).filter(
        models.Project.id == project_id,
        models.Project.organization_id == current_user.organization_id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not is_allowed_file(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    file_ext = get_file_extension(file.filename)
    unique_filename = f"{uuid.uuid4()}.{file_ext}"
    file_path = UPLOAD_DIR / str(project_id)
    file_path.mkdir(exist_ok=True)
    full_path = file_path / unique_filename

    try:
        async with aiofiles.open(full_path, 'wb') as f:
            content = await file.read()
            await f.write(content)
        file_size = len(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    db_drawing = models.Drawing(
        project_id=project_id,
        filename=unique_filename,
        original_filename=file.filename,
        file_path=str(full_path),
        file_size=file_size,
        file_type=file_ext.upper(),
        sheet_name=sheet_name,
        scale=scale,
        processing_status=models.ProcessingStatus.PROCESSING  # ← start as PROCESSING
    )
    db.add(db_drawing)
    db.commit()
    db.refresh(db_drawing)

    # ── NEW: Auto-trigger AI analysis in background ───────────────
    # Imports inline to avoid circular imports
    from routes.takeoff_routes import _run_ai_analysis
    background_tasks.add_task(_run_ai_analysis, db_drawing.id, str(full_path), db)
    # ─────────────────────────────────────────────────────────────

    # Tiled pyramid rendering (memory/TOGAL_PARITY_REAUDIT.md #11) — also
    # kicked off in the background so the upload response stays fast.
    background_tasks.add_task(_generate_tiles, db_drawing.id, project_id, str(full_path))

    return db_drawing


@router.get("/project/{project_id}/drawings", response_model=List[schemas.Drawing])
async def list_project_drawings(
    project_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    project = db.query(models.Project).filter(
        models.Project.id == project_id,
        models.Project.organization_id == current_user.organization_id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return db.query(models.Drawing).filter(
        models.Drawing.project_id == project_id
    ).all()


@router.get("/drawings/{drawing_id}", response_model=schemas.Drawing)
async def get_drawing(
    drawing_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")
    return drawing


@router.get("/drawings/{drawing_id}/file")
async def download_drawing_file(
    drawing_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")
    if not os.path.exists(drawing.file_path):
        raise HTTPException(status_code=404, detail="File not found on server")

    media_type = 'application/pdf' if drawing.file_type == 'PDF' \
                 else f'image/{drawing.file_type.lower()}'
    return FileResponse(
        path=drawing.file_path,
        media_type=media_type,
        filename=drawing.original_filename
    )


def _get_drawing_for_tiles(drawing_id: int, current_user: models.User, db: Session) -> models.Drawing:
    drawing = db.query(models.Drawing).join(models.Project).filter(
        models.Drawing.id == drawing_id,
        models.Project.organization_id == current_user.organization_id
    ).first()
    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")
    return drawing


@router.get("/drawings/{drawing_id}/tiles/status")
async def get_tile_status(
    drawing_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Tile pyramid metadata for OpenSeadragon's custom tileSource (width,
    height, tile_size, overlap, max_level) — {"ready": false} until
    generation finishes, so DrawingRenderer knows whether to fall back to
    direct (non-tiled) rendering.
    """
    from tiling import tiling_available, read_tile_meta

    drawing = _get_drawing_for_tiles(drawing_id, current_user, db)
    if not tiling_available():
        return {"ready": False, "reason": "Tiling isn't available on the server (Pillow isn't installed)."}

    meta = read_tile_meta(str(_tiles_dir(drawing.project_id, drawing_id)))
    if meta is None:
        return {"ready": False}
    return {"ready": True, **meta}


@router.post("/drawings/{drawing_id}/tiles/generate")
async def trigger_tile_generation(
    drawing_id: int,
    background_tasks: BackgroundTasks,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Manual (re)generate — e.g. a retry after the auto-triggered build failed."""
    drawing = _get_drawing_for_tiles(drawing_id, current_user, db)
    if not os.path.exists(drawing.file_path):
        raise HTTPException(status_code=404, detail="File not found on server")
    background_tasks.add_task(_generate_tiles, drawing.id, drawing.project_id, drawing.file_path)
    return {"status": "generating", "drawing_id": drawing_id}


@router.get("/drawings/{drawing_id}/tiles/{level}/{tile_filename}")
async def get_tile(
    drawing_id: int,
    level: int,
    tile_filename: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Serves one {col}_{row}.jpg tile — OpenSeadragon's getTileUrl target."""
    drawing = _get_drawing_for_tiles(drawing_id, current_user, db)
    # tile_filename is user-controlled (path param) — constrain it to the
    # exact "{int}_{int}.jpg" shape tiling.py produces before touching disk,
    # so it can't be used to escape the tiles directory.
    import re
    if not re.fullmatch(r"\d+_\d+\.jpg", tile_filename):
        raise HTTPException(status_code=400, detail="Invalid tile filename")

    path = _tiles_dir(drawing.project_id, drawing_id) / str(level) / tile_filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Tile not found")
    return FileResponse(path=str(path), media_type="image/jpeg")
