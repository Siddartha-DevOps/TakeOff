from pathlib import Path

import pytest

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


def _baseline_schema():
    return set(startup._BASELINE_TABLES), {
        "conditions": set(), "drawings": set(), "correction_events": set(), "users": set(),
    }


def test_fresh_and_versioned_databases_do_not_need_bootstrap():
    assert startup.infer_legacy_revision(set(), {}) is None
    assert startup.infer_legacy_revision({"alembic_version", "users"}, {}) is None


def test_unversioned_baseline_is_stamped_at_baseline():
    tables, columns = _baseline_schema()
    assert startup.infer_legacy_revision(tables, columns) == startup._BASELINE_REVISION


def test_unversioned_current_schema_is_stamped_at_head():
    tables, columns = _baseline_schema()
    for _revision, required_tables, required_columns in startup._REVISION_MARKERS:
        tables.update(required_tables)
        for table, names in required_columns.items():
            columns.setdefault(table, set()).update(names)
    assert startup.infer_legacy_revision(tables, columns) == "i7d8e9f0a1b2"


def test_partial_baseline_fails_closed():
    with pytest.raises(RuntimeError, match="partial pre-Alembic"):
        startup.infer_legacy_revision({"users", "organizations"}, {})


def test_schema_with_revision_gap_fails_closed():
    tables, columns = _baseline_schema()
    # drawing_embeddings is the second post-baseline marker, but unit_cost from
    # the first marker is absent. Stamping either revision would be unsafe.
    tables.add("drawing_embeddings")
    with pytest.raises(RuntimeError, match="inconsistent"):
        startup.infer_legacy_revision(tables, columns)
