import ast
from pathlib import Path

from auth_identity import normalize_email


BACKEND = Path(__file__).parents[1]


def _function_source(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(
        item for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
    )
    return ast.get_source_segment(source, node) or ""


def test_email_normalization_is_stable():
    assert normalize_email("  Alex@Acme.COM ") == "alex@acme.com"


def test_signup_commits_org_and_user_atomically():
    body = _function_source(BACKEND / "routes" / "auth_routes.py", "signup")
    assert "db.flush()" in body
    assert body.count("db.commit()") == 1
    assert "db.rollback()" in body


def test_login_rejects_inactive_accounts_and_normalizes_email():
    body = _function_source(BACKEND / "routes" / "auth_routes.py", "login")
    assert "normalize_email(credentials.email)" in body
    assert "if not user.is_active" in body
    assert "status.HTTP_403_FORBIDDEN" in body


def test_seed_is_idempotent_per_record_not_suppressed_by_any_org():
    body = _function_source(BACKEND / "seed.py", "seed_database")
    assert "models.Organization).count()" not in body
    assert "func.lower(models.User.email)" in body
    assert "models.Project.name == project_data" in body
    assert body.count("db.commit()") == 1
