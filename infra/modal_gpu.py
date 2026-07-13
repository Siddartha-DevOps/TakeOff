import modal

app = modal.App("takeoff-ai")

# Shared image for all training jobs
training_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "ultralytics>=8.2",       # YOLOv8/v11
        "torch>=2.2", "torchvision",
        "segment-anything-2",      # SAM2
        "paddlepaddle", "paddleocr",
        "open-clip-torch",
        "opencv-python-headless",
        "pycocotools",
        "albumentations",
        "wandb",                   # experiment tracking
        "boto3",                   # S3 uploads
    )
)

# Shared volume for datasets + weights
vol = modal.Volume.from_name("takeoff-data", create_if_missing=True)

@app.function(
    image=training_image,
    gpu="A10G",               # 24GB VRAM, ~$1.10/hr
    volumes={"/data": vol},
    timeout=3600 * 4,         # 4hr max per job
)
def train_yolo(config: dict):
    """Generic YOLO training entrypoint."""
    from ultralytics import YOLO
    model = YOLO(config["base_model"])
    model.train(
        data=config["data_yaml"],
        epochs=config["epochs"],
        imgsz=config["imgsz"],
        batch=config["batch"],
        project="/data/runs",
        name=config["run_name"],
    )
    # Save best weights
    return f"/data/runs/{config['run_name']}/weights/best.pt"
