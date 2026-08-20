"""Tests for the ML readiness preflight doctor."""

from ml.preflight import (
    build_readiness,
    check_dataset,
    check_path,
    dependency_present,
    parse_data_yaml,
    run_preflight,
)


# --- dependency probing (injected spec finder) ----------------------------
def test_dependency_present_uses_injected_finder():
    installed = {"torch", "numpy"}
    finder = lambda n: object() if n in installed else None
    assert dependency_present("torch", find_spec=finder) is True
    assert dependency_present("ultralytics", find_spec=finder) is False


def test_dependency_present_swallows_finder_errors():
    def boom(_):
        raise ValueError("namespace weirdness")
    assert dependency_present("torch", find_spec=boom) is False


def test_stdlib_dep_is_detected_for_real():
    # 'json' is always importable — exercises the real importlib path.
    assert dependency_present("json") is True
    assert dependency_present("no_such_module_xyz") is False


# --- data.yaml parsing (both forms) ---------------------------------------
def test_parse_data_yaml_block_form():
    text = "path: /d\ntrain: images/train\nval: images/val\nnc: 3\nnames:\n  0: living\n  1: bedroom\n  2: kitchen\n"
    meta = parse_data_yaml(text)
    assert meta["nc"] == 3
    assert meta["names"] == ["living", "bedroom", "kitchen"]


def test_parse_data_yaml_inline_list_form():
    meta = parse_data_yaml("nc: 2\nnames: [door, window]\n")
    assert meta["nc"] == 2
    assert meta["names"] == ["door", "window"]


# --- filesystem checks -----------------------------------------------------
def test_check_path_reports_size(tmp_path):
    f = tmp_path / "best.pt"
    f.write_bytes(b"12345")
    r = check_path(f)
    assert r["exists"] is True and r["bytes"] == 5
    assert check_path(tmp_path / "missing.pt")["exists"] is False


def test_check_dataset_counts_labels(tmp_path):
    (tmp_path / "labels" / "train").mkdir(parents=True)
    (tmp_path / "labels" / "train" / "a.txt").write_text("0 0 0 1 0 1 1")
    (tmp_path / "data.yaml").write_text("nc: 1\nnames:\n  0: living\n")
    r = check_dataset(tmp_path / "data.yaml")
    assert r["exists"] is True and r["nc"] == 1 and r["n_label_files"] == 1


def test_check_dataset_missing():
    assert check_dataset("/nope/data.yaml")["exists"] is False


# --- readiness aggregation (pure) -----------------------------------------
def _all_deps(present):
    from ml.preflight import TRAIN_DEPS, SERVE_DEPS
    return {d: present for d in set(TRAIN_DEPS) | set(SERVE_DEPS)}


def test_not_ready_when_deps_missing():
    r = build_readiness(_all_deps(False), {}, {"exists": True, "path": "models/best.pt"},
                        {"exists": True, "n_label_files": 5})
    assert r.can_train is False and r.can_serve is False
    assert any("missing dependency" in b for b in r.blockers)


def test_can_serve_needs_weights():
    deps = _all_deps(True)
    no_w = build_readiness(deps, {}, {"exists": False, "path": "models/best.pt"}, {"exists": False})
    assert no_w.can_serve is False
    assert any("no trained weights" in b for b in no_w.blockers)

    with_w = build_readiness(deps, {}, {"exists": True, "path": "models/best.pt"}, {"exists": False})
    assert with_w.can_serve is True


def test_can_train_needs_dataset_with_labels():
    deps = _all_deps(True)
    no_ds = build_readiness(deps, {}, {"exists": True}, {"exists": False, "n_label_files": 0})
    assert no_ds.can_train is False

    empty_ds = build_readiness(deps, {}, {"exists": True}, {"exists": True, "n_label_files": 0})
    assert empty_ds.can_train is False
    assert any("no label files" in b for b in empty_ds.blockers)

    good_ds = build_readiness(deps, {}, {"exists": True}, {"exists": True, "n_label_files": 12})
    assert good_ds.can_train is True


# --- end-to-end (this repo, no ML deps installed) -------------------------
def test_run_preflight_in_ci_reports_not_ready():
    # CI has no torch/ultralytics and no weights -> honest "not ready".
    r = run_preflight()
    assert r.can_train is False and r.can_serve is False
    assert r.blockers  # non-empty, actionable
