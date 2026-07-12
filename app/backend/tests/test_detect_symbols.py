"""Raster symbol-detection tests (pure inference core, no model required)."""

import pytest

from ai.detect_symbols import (
    SYMBOL_CLASS_NAMES,
    detect_symbols_raster,
    summarize_counts,
    symbol_weights_available,
)


def test_summarize_counts_maps_ids_to_names():
    # 2 standard doors (0), 1 toilet (10), 1 sink (11).
    counts = summarize_counts([0, 0, 10, 11])
    assert counts == {"standard_door": 2, "toilet": 1, "sink": 1}


def test_summarize_counts_handles_unknown_ids():
    counts = summarize_counts([999])
    assert counts == {"class_999": 1}


def test_summarize_counts_empty():
    assert summarize_counts([]) == {}


def test_class_map_covers_doors_windows_fixtures():
    names = set(SYMBOL_CLASS_NAMES.values())
    assert "standard_door" in names
    assert "fixed_window" in names
    assert {"toilet", "sink", "outlet", "light_fixture"} <= names
    assert len(SYMBOL_CLASS_NAMES) == 18  # ~18 object types, Togal parity


def test_raster_detection_degrades_without_weights(tmp_path):
    # No weights installed in CI -> graceful needs_weights, never raises.
    assert not symbol_weights_available()
    result = detect_symbols_raster(tmp_path / "does_not_matter.pdf")
    assert result["status"] == "needs_weights"
    assert result["symbol_counts"] == {}
    assert "train" in result["message"].lower()
