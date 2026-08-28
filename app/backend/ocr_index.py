"""Full-sheet OCR/text extraction and project search."""

from __future__ import annotations

import json
import re


def _kind(filename: str, text: str) -> str:
    name = (filename or "").lower()
    if any(word in name for word in ("spec", "manual", "submittal", "schedule")) or len(text) > 5000:
        return "specification"
    return "drawing"


def extract_text_blocks(file_path: str, page_number: int = 0) -> list[dict]:
    import storage
    from PIL import Image

    blocks: list[dict] = []
    with storage.resolve_local_path(file_path) as local_path:
        if str(local_path).lower().endswith(".pdf"):
            import fitz
            doc = fitz.open(local_path)
            try:
                page = doc.load_page(max(0, min(page_number, doc.page_count - 1)))
                for x1, y1, x2, y2, text, *_ in page.get_text("blocks"):
                    clean = " ".join(str(text).split())
                    if clean:
                        blocks.append({"text": clean, "bbox": [x1, y1, x2, y2], "engine": "pdf"})
                if sum(len(item["text"]) for item in blocks) >= 80:
                    return blocks
                pix = page.get_pixmap(matrix=fitz.Matrix(200 / 72, 200 / 72), alpha=False)
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            finally:
                doc.close()
        else:
            image = Image.open(local_path).convert("RGB")

        try:
            import pytesseract
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
            lines: dict[tuple, list] = {}
            for index, raw in enumerate(data.get("text", [])):
                text = str(raw).strip()
                if not text:
                    continue
                key = (data["block_num"][index], data["par_num"][index], data["line_num"][index])
                lines.setdefault(key, []).append(index)
            for indexes in lines.values():
                text = " ".join(data["text"][index].strip() for index in indexes)
                left = min(data["left"][index] for index in indexes)
                top = min(data["top"][index] for index in indexes)
                right = max(data["left"][index] + data["width"][index] for index in indexes)
                bottom = max(data["top"][index] + data["height"][index] for index in indexes)
                blocks.append({"text": text, "bbox": [left, top, right, bottom], "engine": "tesseract"})
        except Exception:
            pass
    return blocks


def index_drawing_text(db, drawing) -> int:
    import models
    blocks = extract_text_blocks(drawing.file_path, drawing.page_number or 0)
    combined = " ".join(item["text"] for item in blocks)
    source_kind = _kind(drawing.original_filename, combined)
    db.query(models.DrawingTextChunk).filter(models.DrawingTextChunk.drawing_id == drawing.id).delete()
    for item in blocks:
        db.add(models.DrawingTextChunk(
            project_id=drawing.project_id, drawing_id=drawing.id,
            page_number=drawing.page_number or 0, source_kind=source_kind,
            text=item["text"], bbox_json=json.dumps(item.get("bbox")),
        ))
    db.commit()
    return len(blocks)


def search_drawing_text(db, project_id: int, query: str, limit: int = 50) -> list[dict]:
    import models
    from sqlalchemy import or_
    stopwords = {"find", "all", "the", "a", "an", "show", "me", "in", "on", "of", "for"}
    terms = [term for term in re.findall(r"[a-z0-9]+", query.lower()) if len(term) > 1 and term not in stopwords]
    if not terms:
        return []
    rows = db.query(models.DrawingTextChunk).filter(
        models.DrawingTextChunk.project_id == project_id,
        or_(*(models.DrawingTextChunk.text.ilike(f"%{term}%") for term in terms)),
    ).limit(max(limit * 4, 100)).all()
    ranked = []
    for row in rows:
        lowered = row.text.lower()
        score = sum(lowered.count(term) for term in terms) / len(terms)
        if score <= 0:
            continue
        ranked.append({
            "chunk_id": row.id, "drawing_id": row.drawing_id,
            "page_number": row.page_number, "source_kind": row.source_kind,
            "text": row.text, "bbox": json.loads(row.bbox_json) if row.bbox_json else None,
            "score": round(score, 4),
        })
    return sorted(ranked, key=lambda item: item["score"], reverse=True)[:limit]
