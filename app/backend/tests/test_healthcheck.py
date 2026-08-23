from pathlib import Path

from healthcheck import database_ready


class _Connection:
    def __init__(self):
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement):
        self.statements.append(str(statement))


class _Engine:
    def __init__(self, connection=None, error=None):
        self.connection = connection
        self.error = error

    def connect(self):
        if self.error:
            raise self.error
        return self.connection


def test_database_readiness_executes_a_real_query():
    connection = _Connection()
    assert database_ready(_Engine(connection=connection)) is True
    assert connection.statements == ["SELECT 1"]


def test_database_readiness_fails_closed_without_leaking_exception():
    assert database_ready(_Engine(error=RuntimeError("secret hostname"))) is False


def test_http_health_returns_503_when_database_is_unavailable():
    server = (Path(__file__).parents[1] / "server.py").read_text(encoding="utf-8")
    assert '"database": "ready" if db_available else "unavailable"' in server
    assert "JSONResponse(status_code=503" in server
    assert '@app.get("/api/live")' in server
