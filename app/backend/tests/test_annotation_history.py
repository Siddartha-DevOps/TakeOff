import ast
from pathlib import Path


BACKEND = Path(__file__).parents[1]


def _function_source(name: str) -> str:
    source = (BACKEND / "routes" / "takeoff_routes.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(item for item in tree.body if isinstance(item, ast.AsyncFunctionDef) and item.name == name)
    return ast.get_source_segment(source, node) or ""


def test_annotation_save_is_versioned_and_deduplicated():
    body = _function_source("save_annotation_state")
    assert "drawing.annotations_data == encoded" in body
    assert "models.AnnotationRevision(" in body
    assert "created_by_id=current_user.id" in body
    assert ".offset(50).all()" in body
    assert "db.delete(stale_revision)" in body


def test_history_and_restore_are_tenant_scoped():
    for name in ("list_annotation_history", "restore_annotation_history"):
        body = _function_source(name)
        assert "models.Project.organization_id == current_user.organization_id" in body


def test_restore_cannot_cross_drawings():
    body = _function_source("restore_annotation_history")
    assert "models.AnnotationRevision.drawing_id == drawing_id" in body
