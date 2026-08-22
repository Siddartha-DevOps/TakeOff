# `ai/inference` — production inference stack

Replaces the old single-file mock engine (`ai/inference_api.py`) with a real,
device-aware, multi-model, tiled detector. **No fabricated output**: when no
trained model is installed, `analyze()` raises `ModelUnavailableError` instead of
returning fake rooms/doors. The real no-model path is vector-PDF geometry
(`geometry/vector_pdf.py`), reached via the `/autodetect` endpoint.

Backward compatibility is total — `server.py` and `routes/takeoff_routes.py`
import the same names (`TakeoffAIInference`, `TakeoffAnalysis`, `CLASSES`) from
`ai.inference_api`, which now just re-exports this package.

## Modules

| Module | Mission item | What it does | Heavy deps |
|--------|--------------|--------------|------------|
| `engine.py` | #1 (mock removal), multi-model | `InferenceEngine` + `ModelRegistry` (task→model), `ModelUnavailableError`, result partitioning/quantities | ultralytics/torch/cv2 (lazy) |
| `device.py` | #8 GPU/CPU | `resolve_device("auto"\|"cpu"\|"cuda:N"\|"mps")` with injectable probe | torch (lazy) |
| `confidence.py` | #9 confidence | per-class thresholds, NMS, temperature calibration, ECE | none |
| `tiling.py` | large drawings | overlapping tile grid + cross-seam NMS merge | none |
| `benchmark.py` | #7 benchmarking | latency percentiles + throughput, injectable clock | none |
| `remote_space.py` | hosted inference | private Gradio/ZeroGPU adapter preserving `TakeoffAnalysis` | gradio_client (lightweight) |

Every logic core is pure NumPy/stdlib and unit-tested
(`tests/test_inference_*.py`, 31 tests). torch/ultralytics/cv2 are imported
lazily inside the methods that actually run a model, so the package imports and
tests on a CPU-only CI box.

## Usage

```python
from ai.inference import InferenceEngine, ModelUnavailableError

engine = InferenceEngine.get_instance("models/best.pt", device="auto")
try:
    result = engine.analyze("sheet.png", drawing_id=42)   # auto-tiles large sheets
    print(result.summary, result.confidence_avg, result.device)
except ModelUnavailableError:
    ...  # fall back to vector AUTODETECT or report "model not installed"
```

### Multi-model registry

```python
from ai.inference import ModelSpec
engine.registry.register(ModelSpec(task="symbols", name="sym-v1",
                                   weights_path="ai/models/symbol_counts/yolov8-seg.pt"))
```

### Large drawings

`analyze()` auto-tiles any page whose longest side exceeds
`DEFAULT_TILE_THRESHOLD` (2000 px): an overlapping `tile_grid` is run per-tile,
detections are offset back to page coordinates, and a global per-class NMS
(`merge_tiled_detections`) removes seam duplicates. Force it with
`analyze(..., tile=True/False)`.

### Benchmarking (GPU box)

```python
from ai.inference.benchmark import benchmark
res = benchmark(lambda p: engine.analyze(p, 0), inputs=sheet_paths,
                warmup=2, repeats=5, device=engine.device)
print(res.as_dict())   # {p50_ms, p90_ms, p99_ms, throughput_ips, ...}
```

### Confidence calibration (from CorrectionEvents)

```python
from ai.inference.confidence import fit_temperature, expected_calibration_error
T = fit_temperature(scores, accepted_flags)      # accepted=correct, rejected=incorrect
ece = expected_calibration_error(scores, accepted_flags)
```

## Where the real model runs

The lightweight Render API uses `RemoteSpaceInference` when
`AI_INFERENCE_SPACE_ID` is set. It calls the named endpoint on a private Gradio
Space with `HF_TOKEN`; the token stays server-side. The returned stable JSON is
translated into the same `TakeoffAnalysis` consumed by persistence and spatial
reasoning, so routes and the frontend do not branch on deployment topology.

```bash
AI_INFERENCE_SPACE_ID=Siddartha96/takeoff-spaces-inference
AI_INFERENCE_API_NAME=/predict_spaces
AI_INFERENCE_TIMEOUT_SECONDS=90
HF_TOKEN=<read-token-with-access-to-the-private-space>
```

GPU deployments can continue using a local checkpoint produced by `ml/` and
loaded from `models/best.pt`. This repo/CI never needs to run torch: it tests
the pure logic and both adapters' transport contracts.
