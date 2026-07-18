"""Tests for the Label Studio config generator + accuracy report (WS1A/1C)."""

import pytest

from ml.annotation.label_studio import build_labeling_config
from ml.eval.report import accuracy_report_dict, build_accuracy_report


# --- Label Studio config ---------------------------------------------------
def test_labeling_config_has_polygon_and_rectangle_labels():
    xml = build_labeling_config(["living", "bedroom"], ["door", "window"])
    assert "<PolygonLabels" in xml and "<RectangleLabels" in xml
    for cls in ("living", "bedroom", "door", "window"):
        assert f'value="{cls}"' in xml
    assert xml.strip().startswith("<View>") and xml.strip().endswith("</View>")


def test_labeling_config_symbols_optional():
    xml = build_labeling_config(["living"])
    assert "<PolygonLabels" in xml
    assert "<RectangleLabels" not in xml


def test_labeling_config_requires_a_space_class():
    with pytest.raises(ValueError):
        build_labeling_config([])


# --- accuracy report -------------------------------------------------------
def _passing_report():
    return {
        "gate_passed": True,
        "metrics": {"miou": 0.82, "map": 0.61, "measurement_error_pct": 3.4, "n_samples": 30},
        "thresholds": {"min_miou": 0.70, "min_map": 0.50, "max_measurement_error_pct": 5.0},
        "reasons": [],
    }


def _failing_report():
    return {
        "gate_passed": False,
        "metrics": {"miou": 0.55, "map": 0.40, "measurement_error_pct": 8.0, "n_samples": 12},
        "thresholds": {"min_miou": 0.70, "min_map": 0.50, "max_measurement_error_pct": 5.0},
        "reasons": ["miou 0.55 < 0.70", "map 0.40 < 0.50"],
    }


def test_report_dict_marks_each_metric_ok():
    card = accuracy_report_dict(_passing_report())
    assert card["gate_passed"] is True and card["n_samples"] == 30
    assert all(r["ok"] for r in card["rows"])


def test_report_dict_flags_failures():
    card = accuracy_report_dict(_failing_report())
    by_key = {r["key"]: r for r in card["rows"]}
    assert by_key["miou"]["ok"] is False
    assert by_key["measurement_error_pct"]["ok"] is False   # 8% > 5%


def test_report_dict_none_metric_is_not_ok():
    rep = {"gate_passed": False, "metrics": {"miou": None}, "thresholds": {"min_miou": 0.7}}
    card = accuracy_report_dict(rep)
    assert next(r for r in card["rows"] if r["key"] == "miou")["ok"] is False


def test_markdown_passed_and_failed():
    md_pass = build_accuracy_report(_passing_report())
    assert "PASSED" in md_pass and "30" in md_pass and "✅" in md_pass

    md_fail = build_accuracy_report(_failing_report())
    assert "FAILED" in md_fail
    assert "Why it failed" in md_fail and "miou 0.55 < 0.70" in md_fail
    assert "active-learning" in md_fail   # actionable next step
