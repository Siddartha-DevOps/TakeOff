import ast
from pathlib import Path


BACKEND = Path(__file__).parents[1]


def test_annotation_migration_is_on_current_head():
    migration = BACKEND / "alembic" / "versions" / "i7d8e9f0a1b2_add_drawing_annotation_state.py"
    source = migration.read_text(encoding="utf-8")
    assert 'down_revision: Union[str, Sequence[str], None] = "h6c7d8e9f0a1"' in source
    assert 'op.add_column("drawings"' in source
    assert '"annotations_data"' in source


def test_takeoff_router_exposes_tenant_scoped_annotation_read_and_write():
    source = (BACKEND / "routes" / "takeoff_routes.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {
        node.name: ast.get_source_segment(source, node) or ""
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for name in ("get_annotation_state", "save_annotation_state"):
        body = functions[name]
        assert "models.Project.organization_id == current_user.organization_id" in body
        assert "Drawing not found" in body


def test_annotation_write_has_a_document_size_limit():
    source = (BACKEND / "routes" / "takeoff_routes.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "save_annotation_state"
    )
    body = ast.get_source_segment(source, function) or ""
    assert "5 * 1024 * 1024" in body
    assert "status_code=413" in body
