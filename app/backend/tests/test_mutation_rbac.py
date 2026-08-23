import ast
from pathlib import Path
from request_authorization import request_method_allowed


def test_viewer_is_allowed_to_read():
    for method in ("GET", "HEAD", "OPTIONS"):
        assert request_method_allowed("viewer", method)


def test_viewer_is_denied_every_unsafe_http_method():
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert not request_method_allowed("viewer", method)


def test_member_is_allowed_to_write():
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert request_method_allowed("member", method)


def test_authentication_boundary_applies_request_role_policy():
    auth_source = (Path(__file__).parents[1] / "auth.py").read_text(encoding="utf-8")
    tree = ast.parse(auth_source)
    get_current_user = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "get_current_user"
    )
    function_source = ast.get_source_segment(auth_source, get_current_user) or ""

    assert "enforce_request_role(user, request.method)" in function_source


def test_sensitive_org_mutations_require_admin_role():
    """Protect the few writes that change organization-wide configuration."""
    expected = {
        "sso_routes.py": {"upsert_sso"},
        "integrations_routes.py": {"connect", "disconnect"},
        "eval_routes.py": {"create_model_version", "evaluate", "promote"},
        "classification_routes.py": {
            "create_template", "seed_default", "update_template", "delete_template",
        },
        "assemblies_routes.py": {
            "seed_assemblies", "create_assembly", "update_assembly", "delete_assembly",
            "create_cost_book", "update_cost_book", "delete_cost_book",
        },
    }
    routes_dir = Path(__file__).parents[1] / "routes"
    required = "Depends(permissions.require_role(models.UserRole.ADMIN))"

    for filename, function_names in expected.items():
        source = (routes_dir / filename).read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {
            node.name: ast.get_source_segment(source, node) or ""
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for function_name in function_names:
            assert required in functions[function_name], (
                f"{filename}:{function_name} must require an admin role"
            )
