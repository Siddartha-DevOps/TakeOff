---
title: TakeOff Spaces Inference
emoji: 🏗️
colorFrom: blue
colorTo: yellow
sdk: gradio
sdk_version: 6.1.0
app_file: app.py
pinned: false
license: apache-2.0
models:
  - Siddartha96/takeoff-spaces-yolov8m-seg
---

# TakeOff.ai spaces inference

Private ZeroGPU inference service for the TakeOff.ai ResPlan-pretrained room
segmentation model. The `predict_spaces` Gradio API returns an annotated image
and normalized JSON detections for the Render API to consume.

The Space requires an `HF_TOKEN` secret with read access to the private model.
Model SHA-256:
`2cc2cfffaa294f9915a2fddab9812f06b10450e8149e75d5d3361f5b792c9acd`.
