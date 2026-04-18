# TakeOff.ai — AI Model Training Guide
## 5 Core Detection Features

---

## FEATURE 1: Room Detection & Segmentation

### Model: YOLOv8 + Mask R-CNN
### Goal: Detect room boundaries and classify room types with polygon masks

### Dataset Requirements
- **Min training images**: 2,000 annotated floor plans
- **Labels**: Living, Bedroom, Kitchen, Bathroom, Dining, Office, Hallway, Closet, Utility
- **Annotation format**: COCO Instance Segmentation (polygon masks)
- **Tools**: CVAT or Label Studio (self-hosted for IP protection)

### Training Steps
```bash
# 1. Install dependencies
pip install ultralytics torch torchvision detectron2

# 2. Prepare dataset structure
/data/rooms/
  train/images/  train/masks/
  val/images/    val/masks/
  data.yaml

# 3. Train YOLOv8-seg for room segmentation
from ultralytics import YOLO
model = YOLO('yolov8m-seg.pt')
results = model.train(
    data='data/rooms/data.yaml',
    epochs=200,
    imgsz=1280,          # Large for floor plans
    batch=8,
    device='0',
    optimizer='AdamW',
    lr0=0.001,
    patience=50,
    augment=True
)

# 4. Evaluate
metrics = model.val()
# Target: mAP@0.5 > 0.88, mAP@0.5:0.95 > 0.72
```

### data.yaml
```yaml
path: /data/rooms
train: train/images
val: val/images
nc: 9
names: ['living', 'bedroom', 'kitchen', 'bathroom',
        'dining', 'office', 'hallway', 'closet', 'utility']
```

### Augmentation Strategy
```python
# In ultralytics training config
hsv_h=0.01,   # Slight hue shift for scan variation
hsv_v=0.4,    # Brightness for different scan qualities
translate=0.1,
scale=0.9,
degrees=0,    # NO rotation — floor plans are always upright
fliplr=0.3,   # Mirror horizontally (valid for floor plans)
```

---

## FEATURE 2: Door Detection & Classification

### Model: YOLOv8 Object Detection
### Goal: Detect doors, classify type, and determine swing direction

### Dataset Requirements
- **Min training images**: 1,500 floor plans with annotated doors
- **Classes**: standard_door, bifold_door, sliding_door, double_door, pocket_door
- **Key challenge**: Small objects (30-60px), high precision required

### Training Steps
```python
from ultralytics import YOLO

model = YOLO('yolov8m.pt')
results = model.train(
    data='data/doors/data.yaml',
    epochs=300,
    imgsz=1280,
    batch=16,
    device='0',
    # Smaller objects need higher resolution
    conf=0.25,
    iou=0.45,
    # Door-specific settings
    cls=0.5,          # Classification weight
    box=7.5,          # Box loss weight (higher for small objects)
)
# Target: mAP@0.5 > 0.91
```

### Post-processing for Swing Direction
```python
def detect_door_swing(bbox, image_region):
    """Detect door swing angle from the arc symbol"""
    # Arc detection using Hough Circle Transform
    import cv2
    gray = cv2.cvtColor(image_region, cv2.COLOR_BGR2GRAY)
    circles = cv2.HoughCircles(gray, cv2.HOUGH_GRADIENT, 1, 20,
                               param1=50, param2=30,
                               minRadius=10, maxRadius=40)
    if circles is not None:
        # Calculate rotation from arc position relative to door hinge
        return calculate_rotation(bbox, circles[0][0])
    return 0  # default: no rotation
```

---

## FEATURE 3: Window Detection

### Model: YOLOv8 Object Detection
### Goal: Detect windows, classify type, extract dimensions

### Dataset Requirements
- **Min training images**: 1,200 floor plans
- **Classes**: fixed_window, casement_window, sliding_window, transom_window, bay_window
- **Critical**: Distinguish windows from wall segments (similar visual pattern)

### Training Steps
```python
from ultralytics import YOLO

model = YOLO('yolov8m.pt')
results = model.train(
    data='data/windows/data.yaml',
    epochs=250,
    imgsz=1280,
    batch=16,
    # Windows often confused with walls — use higher conf threshold
    conf=0.35,
    iou=0.5,
)
# Target: mAP@0.5 > 0.89, precision > 0.90 (minimize false positives)
```

### Dimension Extraction via OCR
```python
from paddleocr import PaddleOCR

ocr = PaddleOCR(lang='en')

def extract_window_dimensions(image, bbox):
    """Extract dimension labels near a detected window"""
    x1, y1, x2, y2 = bbox
    # Expand search region for nearby text
    search_region = image[
        max(0, y1-40):min(image.shape[0], y2+40),
        max(0, x1-60):min(image.shape[1], x2+60)
    ]
    result = ocr.ocr(search_region)
    # Parse dimension strings like "4'-0"" or "1200mm"
    return parse_dimensions(result)
```

---

## FEATURE 4: Wall Detection & Measurement

### Model: Line detection + custom CNN classifier
### Goal: Detect walls, classify type (exterior/interior/load-bearing), measure linear footage

### Approach: Two-stage pipeline
1. **Stage 1**: Hough Line Transform for initial line detection
2. **Stage 2**: CNN to classify line segments as walls vs other lines

### Training Steps
```python
# Stage 1: Line detection (no training needed)
import cv2
import numpy as np

def detect_wall_candidates(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(edges,
                            rho=1, theta=np.pi/180,
                            threshold=80,
                            minLineLength=30,
                            maxLineGap=10)
    return lines

# Stage 2: Train CNN to classify wall vs non-wall line segments
import torch
import torch.nn as nn

class WallClassifier(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(1, 32, 3, padding=1), nn.ReLU(),
            nn.Conv2d(32, 64, 3, padding=1), nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(64, 128, 3, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool2d((4, 4))
        )
        self.fc = nn.Sequential(
            nn.Flatten(),
            nn.Linear(128*4*4, 256), nn.ReLU(), nn.Dropout(0.3),
            nn.Linear(256, 3)  # exterior, interior, non-wall
        )

    def forward(self, x):
        return self.fc(self.conv(x))

# Training: 500 labeled 32x32 patches per class
# Target: Accuracy > 94%
```

### Auto-scale Detection for Real-world Measurements
```python
def detect_scale(image):
    """Find scale bar or notation like '1/8" = 1'-0"'"""
    # 1. OCR to find scale notation
    scale_patterns = [
        r'(\d+)/(\d+)"\s*=\s*1\'-0"',
        r'1:\s*(\d+)',
        r'Scale:\s*(\S+)',
    ]
    ocr_result = run_ocr(image)
    for pattern in scale_patterns:
        match = re.search(pattern, ocr_result)
        if match:
            return parse_scale(match)

    # 2. Fallback: detect scale bar graphic
    return detect_scale_bar(image)

def calculate_real_length(pixel_length, scale_ratio, dpi=300):
    """Convert pixel measurements to real-world feet"""
    inches_per_pixel = 1 / dpi
    real_inches = pixel_length * inches_per_pixel * scale_ratio
    return real_inches / 12  # return in feet
```

---

## FEATURE 5: Plumbing & Electrical Symbol Classification

### Model: CLIP + YOLOv8 (two-stage)
### Goal: Detect and classify MEP symbols (toilets, sinks, outlets, switches, fixtures)

### Why Two-Stage?
- YOLOv8 finds symbol candidates (fast, bounding boxes)
- CLIP classifies edge cases (semantic understanding of symbol shape)

### Dataset Requirements
- **Min training images**: 2,000 floor plans with MEP annotations
- **Classes (Plumbing)**: toilet, sink, shower, bathtub, washer, water_heater
- **Classes (Electrical)**: outlet, switch, light_fixture, panel, junction_box, smoke_detector
- **Annotation**: Bounding boxes (YOLO format)

### Training Steps
```python
# Stage 1: YOLOv8 for symbol detection
from ultralytics import YOLO

model = YOLO('yolov8s.pt')  # smaller model, symbols are small objects
results = model.train(
    data='data/mep_symbols/data.yaml',
    epochs=300,
    imgsz=1280,
    batch=16,
    device='0',
    # Small symbol detection settings
    conf=0.2,           # Lower threshold for small symbols
    iou=0.4,
    box=10.0,           # High box loss weight for precision
)
# Target: mAP@0.5 > 0.85 (harder task due to symbol similarity)

# Stage 2: CLIP for classification of ambiguous symbols
import clip
import torch

device = "cuda"
clip_model, preprocess = clip.load("ViT-B/32", device=device)

SYMBOL_DESCRIPTIONS = [
    "architectural floor plan symbol for toilet/WC",
    "architectural floor plan symbol for sink/lavatory",
    "architectural floor plan symbol for electrical outlet/receptacle",
    "architectural floor plan symbol for light switch",
    "architectural floor plan symbol for ceiling light fixture",
    "architectural floor plan symbol for smoke detector",
]

def classify_symbol_with_clip(image_crop):
    image = preprocess(image_crop).unsqueeze(0).to(device)
    text = clip.tokenize(SYMBOL_DESCRIPTIONS).to(device)

    with torch.no_grad():
        logits, _ = clip_model(image, text)
        probs = logits.softmax(dim=-1)[0]

    top_class = SYMBOL_DESCRIPTIONS[probs.argmax()]
    confidence = probs.max().item()
    return top_class, confidence
```

---

## PRODUCTION DEPLOYMENT PIPELINE

```python
# backend/ai/pipeline.py

class TakeoffAIPipeline:
    """
    Full AI pipeline for blueprint analysis.
    Called when a drawing is uploaded.
    """

    def __init__(self):
        self.room_model = YOLO('models/rooms_v1.pt')
        self.door_model = YOLO('models/doors_v1.pt')
        self.window_model = YOLO('models/windows_v1.pt')
        self.wall_classifier = WallClassifier.load('models/walls_v1.pt')
        self.mep_model = YOLO('models/mep_v1.pt')
        self.ocr = PaddleOCR(lang='en')

    def process(self, image_path: str, drawing_id: int) -> dict:
        image = cv2.imread(image_path)

        # Parallel inference
        rooms = self.room_model(image, conf=0.5)
        doors = self.door_model(image, conf=0.3)
        windows = self.window_model(image, conf=0.35)
        walls = self.detect_walls(image)
        mep = self.mep_model(image, conf=0.25)

        # Scale detection for real measurements
        scale = detect_scale(image)
        ocr_text = self.ocr.ocr(image)

        # Combine and calculate quantities
        detection_data = self.combine_detections(
            rooms, doors, windows, walls, mep, scale, ocr_text
        )

        quantities = self.calculate_quantities(detection_data, scale)

        return {
            'detection_data': json.dumps(detection_data),
            'quantities_data': json.dumps(quantities),
            'confidence_scores': json.dumps(self.get_confidence_summary(detection_data)),
            'processing_time_ms': self.timer.elapsed_ms()
        }
```

### Integration with FastAPI endpoint
```python
# Add to backend/routes/takeoff_routes.py

@router.post("/drawings/{drawing_id}/analyze")
async def analyze_drawing(
    drawing_id: int,
    background_tasks: BackgroundTasks,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    drawing = db.query(models.Drawing).filter(
        models.Drawing.id == drawing_id
    ).first()

    if not drawing:
        raise HTTPException(status_code=404, detail="Drawing not found")

    # Update status to processing
    drawing.processing_status = models.ProcessingStatus.PROCESSING
    db.commit()

    # Run AI in background (non-blocking)
    background_tasks.add_task(run_ai_analysis, drawing_id, drawing.file_path, db)

    return {"status": "processing", "drawing_id": drawing_id}


async def run_ai_analysis(drawing_id: int, file_path: str, db: Session):
    try:
        pipeline = TakeoffAIPipeline()
        results = pipeline.process(file_path, drawing_id)

        # Save results
        db_result = models.TakeoffResult(
            drawing_id=drawing_id,
            **results,
            ai_model_version="v1.0.0"
        )
        db.add(db_result)

        drawing = db.query(models.Drawing).filter(
            models.Drawing.id == drawing_id
        ).first()
        drawing.processing_status = models.ProcessingStatus.COMPLETED
        drawing.processed_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as e:
        drawing = db.query(models.Drawing).filter(
            models.Drawing.id == drawing_id
        ).first()
        drawing.processing_status = models.ProcessingStatus.FAILED
        db.commit()
        logger.error(f"AI analysis failed for drawing {drawing_id}: {e}")
```

---

## ACCURACY TARGETS BY FEATURE

| Feature | mAP@0.5 | mAP@0.5:0.95 | Min Dataset | Est. Training Time |
|---------|---------|--------------|-------------|-------------------|
| Room segmentation | >0.88 | >0.72 | 2,000 plans | 18h (A100) |
| Door detection | >0.91 | >0.78 | 1,500 plans | 12h (A100) |
| Window detection | >0.89 | >0.74 | 1,200 plans | 10h (A100) |
| Wall detection | >0.94 acc | — | 500 patches | 2h (A100) |
| MEP symbols | >0.85 | >0.68 | 2,000 plans | 20h (A100) |

---

## RECOMMENDED GPU HARDWARE
- Development: NVIDIA RTX 3090 (24GB VRAM)
- Production training: NVIDIA A100 (40GB VRAM) x2
- Budget cloud: Lambda Labs ($1.10/hr A100), RunPod ($0.79/hr)