# Kaggle Mask R-CNN GPU preflight

This is a bounded framework check, not a training run. It verifies the frozen
full Swiss Dwellings adapter on one real hole-containing train floor, one real
validation floor, and one intentional negative floor. The bundle contains the
unchanged content-addressed full manifest plus only those three images and COCO
RLE shards. Generated bundle data stays outside Git.

## Kaggle runtime

- GPU: NVIDIA T4 16 GB minimum; L4/A10 24 GB is also valid.
- Python: 3.12 (validated against Kaggle Python 3.12.13).
- CUDA wheel runtime: 12.1.
- PyTorch: 2.5.1+cu121.
- torchvision: 0.20.1+cu121.
- Smoke batch size: 1.

Create two private Kaggle Datasets from the generated archives
`takeoff-maskrcnn-preflight-v2.zip` and
`takeoff-task6-preflight-source-v2.zip`. Import
`ml/notebooks/maskrcnn_full_adapter_kaggle_preflight.ipynb`, attach both private
datasets, select a T4 GPU, enable Internet for the pinned dependency-install
cell, and run all cells exactly once. A valid run emits
`maskrcnn-gpu-preflight-report.json` and never enters an epoch loop.

PASS requires the expected GPU/runtime versions, at least 14 GiB usable VRAM,
the exact frozen manifest hash, three real samples loaded, preserved hole RLE,
an empty intentional-negative target, finite Mask R-CNN losses, successful
backward and optimizer step, bounded peak memory below available VRAM, and a
standard output convertible to TakeOff `label`, `score`, `bbox`, and `mask`.

## Verified Task 6 result

The final bounded run passed on 2026-09-21 using a Tesla T4, CUDA 12.1,
PyTorch 2.5.1+cu121, and torchvision 0.20.1+cu121. The external evidence file
`E:\Takeoff_datasets\maskrcnn-gpu-preflight-report.json` has SHA-256
`be5beded0d1f946cc2a1cd7e8d2d27b46566507fb32e2d245086a8dea8668e8b`.
It records three real samples, two verified hole instances, an intentional
negative, finite losses, backward propagation, one optimizer step, peak
reserved memory of 4.705 GiB against 14.56 GiB available, and a compatible
TakeOff inference result. `training_started` is false.
