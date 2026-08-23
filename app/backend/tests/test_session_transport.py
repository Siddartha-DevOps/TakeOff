from pathlib import Path


ROOT = Path(__file__).parents[2]
FRONTEND = ROOT / "frontend" / "src"


def test_frontend_never_persists_bearer_credentials_in_local_storage():
    offenders = []
    for path in FRONTEND.rglob("*"):
        if path.suffix not in {".js", ".jsx"}:
            continue
        source = path.read_text(encoding="utf-8", errors="ignore")
        if "localStorage.getItem('auth_token')" in source or "localStorage.setItem('auth_token'" in source:
            offenders.append(str(path.relative_to(FRONTEND)))
    assert offenders == []


def test_websocket_url_does_not_contain_a_bearer_query_parameter():
    source = (FRONTEND / "services" / "api.js").read_text(encoding="utf-8")
    assert "?token=" not in source
    assert "protocols: token ? ['takeoff-auth', token]" in source
