import pytest

from ml.eval.runner import evaluate_samples, polygon_dice


SQUARE = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
HALF = [[0, 0], [5, 0], [5, 10], [0, 10], [0, 0]]


def test_evaluation_runner_reports_per_image_and_aggregate_metrics():
    report = evaluate_samples([{
        "image_id": "A-101",
        "ground_truth": [{"class": "room", "geometry": SQUARE}],
        "predictions": [{"class": "room", "confidence": 0.9, "geometry": SQUARE}],
    }])
    assert report["evaluation_status"] == "EVALUATED"
    assert report["aggregate"]["precision"] == 1
    assert report["aggregate"]["recall"] == 1
    assert report["aggregate"]["mean_iou"] == 1
    assert report["aggregate"]["mean_dice"] == 1
    assert report["aggregate"]["room_count_accuracy"] == 1
    assert report["per_image"][0]["area_error_pct"] == 0
    assert report["per_image"][0]["perimeter_error_pct"] == 0


def test_evaluation_runner_counts_false_positive_and_negative_by_class():
    report = evaluate_samples([{
        "image_id": "A-102",
        "ground_truth": [{"class": "room", "geometry": SQUARE}],
        "predictions": [{"class": "other", "confidence": 0.8, "geometry": SQUARE}],
    }])
    assert report["aggregate"]["per_class"]["room"]["fn"] == 1
    assert report["aggregate"]["per_class"]["other"]["fp"] == 1
    assert report["aggregate"]["room_count_accuracy"] == 1
    assert report["aggregate"]["precision"] == 0
    assert report["aggregate"]["recall"] == 0


def test_polygon_dice_is_geometric_not_a_placeholder():
    assert polygon_dice(SQUARE, HALF) == pytest.approx(2 / 3)


def test_empty_benchmark_is_not_evaluated():
    report = evaluate_samples([])
    assert report["evaluation_status"] == "NOT_EVALUATED"
    assert report["aggregate"]["sample_count"] == 0
