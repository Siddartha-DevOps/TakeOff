from pathlib import Path

import startup


def test_auto_migrate_defaults_to_enabled(monkeypatch):
    monkeypatch.delenv("AUTO_MIGRATE", raising=False)
    assert startup.auto_migrate_enabled() is True


def test_auto_migrate_can_be_disabled(monkeypatch):
    for value in ("0", "false", "FALSE", "no", "off"):
        monkeypatch.setenv("AUTO_MIGRATE", value)
        assert startup.auto_migrate_enabled() is False


def test_run_database_migrations_uses_absolute_repository_paths(monkeypatch):
    captured = {}

    class FakeConfig:
        def __init__(self, path):
            captured["config_path"] = path

        def set_main_option(self, key, value):
            captured[key] = value

    startup.run_database_migrations(
        config_factory=FakeConfig,
        upgrade=lambda config, revision: captured.update(config=config, revision=revision),
    )

    assert Path(captured["config_path"]).is_absolute()
    assert Path(captured["script_location"]).is_absolute()
    assert captured["revision"] == "head"
