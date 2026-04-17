"# 🧠 PHASE 3: AI SYSTEM ARCHITECTURE DESIGN
## TakeOff.ai Real AI Detection System

**Status:** Design Phase (NO TRAINING YET)  
**Purpose:** Complete architecture for future AI implementation  
**Last Updated:** December 2025

---

## 📋 TABLE OF CONTENTS

1. [System Overview](#system-overview)
2. [YOLO Blueprint Detection Architecture](#yolo-detection-architecture)
3. [Dataset Strategy](#dataset-strategy)
4. [Training Pipeline Design](#training-pipeline)
5. [Human-in-the-Loop System](#human-in-loop)
6. [Implementation Roadmap](#roadmap)

---

## 1. SYSTEM OVERVIEW {#system-overview}

### Architecture Components

```
┌─────────────────────────────────────────────────────────────────┐
│                    TakeOff.ai AI Pipeline                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  INPUT: Blueprint PDF/TIFF/PNG                                  │
│     │                                                            │
│     ├─► Image Preprocessing                                     │
│     │      - DPI normalization                                  │
│     │      - Scale detection (OCR)                              │
│     │      - Noise reduction                                    │
│     │                                                            │
│     ├─► YOLOv8 Object Detection                                 │
│     │      - Doors (bounding boxes)                             │
│     │      - Windows (bounding boxes)                           │
│     │      - Plumbing fixtures                                  │
│     │      - Electrical symbols                                 │
│     │                                                            │
│     ├─► Mask R-CNN Room Segmentation                            │
│     │      - Room boundaries (polygons)                         │
│     │      - Wall detection                                     │
│     │      - Area calculation                                   │
│     │                                                            │
│     ├─► OCR Text Extraction                                     │
│     │      - Room labels                                        │
│     │      - Dimensions                                         │
│     │      - Scale notation                                     │
│     │                                                            │
│     ├─► CLIP Embedding (Future)                                 │
│     │      - Semantic understanding                             │
│     │      - Symbol classification                              │
│     │                                                            │
│     └─► Post-Processing                                         │
│            - Confidence filtering                               │
│            - Duplicate removal                                  │
│            - Geometric validation                               │
│                                                                  │
│  OUTPUT: Structured Detection JSON                              │
│     {                                                            │
│       \"rooms\": [...],                                            │
│       \"doors\": [...],                                            │
│       \"windows\": [...],                                          │
│       \"plumbing\": [...],                                         │
│       \"electrical\": [...]                                        │
│     }                                                            │
└─────────────────────────────────────────────────────────────────┘
```

### Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Object Detection | **YOLOv8** | Fast, accurate small object detection (doors, windows, symbols) |
| Instance Segmentation | **Mask R-CNN** | Precise room boundary detection and wall segmentation |
| Text Recognition | **PaddleOCR / Tesseract** | Extract room labels, dimensions, scales |
| Semantic Search | **CLIP (OpenAI)** | Understanding architectural symbols and context |
| Backend Framework | **FastAPI + PostgreSQL** | API and data storage |
| Model Serving | **TorchServe / FastAPI** | Model inference API |
| Training Platform | **PyTorch** | Model training framework |

---

## 2. YOLO BLUEPRINT DETECTION ARCHITECTURE {#yolo-detection-architecture}

### Model Selection: YOLOv8

**Why YOLOv8?**
- ✅ State-of-the-art speed + accuracy
- ✅ Excellent for small objects (doors, windows, symbols)
- ✅ Multiple model sizes (nano to extra-large)
- ✅ Easy fine-tuning on custom datasets
- ✅ Strong community and documentation

**Model Sizes for TakeOff.ai:**
- **Development/Testing:** YOLOv8n (nano) - Fast inference, good for prototyping
- **Production:** YOLOv8m (medium) - Balance of speed and accuracy
- **High-Accuracy Mode:** YOLOv8x (extra-large) - Maximum accuracy for critical projects

### Detection Classes

#### Primary Classes (Phase 1)
1. **Doors** (bounding box)
   - Standard door
   - Bi-fold door
   - Sliding door
   - Double door

2. **Windows** (bounding box)
   - Fixed window
   - Casement window
   - Sliding window
   - Transom window

3. **Rooms** (bounding box + segmentation mask)
   - Living spaces
   - Bedrooms
   - Bathrooms
   - Kitchens
   - Utility rooms
   - Hallways

4. **Walls** (line segments)
   - Exterior walls (thick lines)
   - Interior walls (thin lines)
   - Load-bearing walls

#### Extended Classes (Phase 2)
5. **Plumbing Symbols**
   - Toilets, sinks, showers, bathtubs
   - Water lines, drain lines

6. **Electrical Symbols**
   - Outlets, switches, light fixtures
   - Panels, junction boxes

7. **HVAC Symbols**
   - Vents, ducts, registers
   - Equipment (furnaces, AC units)

8. **Structural Elements**
   - Stairs, elevators
   - Columns, beams

### Input/Output Schema

#### Input Format
```python
{
  \"drawing_id\": 123,
  \"file_path\": \"/uploads/project_1/drawing_456.pdf\",
  \"scale\": \"1/8\\" = 1'-0\\"\",
  \"dpi\": 300,
  \"page_number\": 1
}
```

#### Output Format
```python
{
  \"drawing_id\": 123,
  \"processing_time_ms\": 1420,
  \"ai_model_version\": \"yolov8m-blueprint-v1.0\",
  \"detections\": {
    \"doors\": [
      {
        \"id\": \"d1\",
        \"class\": \"standard_door\",
        \"bbox\": [x1, y1, x2, y2],  # pixel coordinates
        \"confidence\": 0.95,
        \"width_inches\": 36,
        \"rotation\": 90  # degrees
      }
    ],
    \"windows\": [
      {
        \"id\": \"w1\",
        \"class\": \"fixed_window\",
        \"bbox\": [x1, y1, x2, y2],
        \"confidence\": 0.92,
        \"width_inches\": 48
      }
    ],
    \"rooms\": [
      {
        \"id\": \"r1\",
        \"label\": \"Living Room\",  # from OCR
        \"bbox\": [x1, y1, x2, y2],
        \"segmentation_mask\": [[x1,y1], [x2,y2], ...],  # polygon
        \"area_sqft\": 420,
        \"confidence\": 0.98
      }
    ],
    \"walls\": [
      {
        \"id\": \"wall1\",
        \"type\": \"exterior\",
        \"line\": [[x1,y1], [x2,y2]],
        \"thickness_inches\": 8,
        \"confidence\": 0.96
      }
    ]
  },
  \"summary\": {
    \"total_rooms\": 9,
    \"total_doors\": 14,
    \"total_windows\": 18,
    \"total_area_sqft\": 4280,
    \"walls_linear_feet\": 312
  }
}
```

### Inference Pipeline

```python
# Pseudocode for inference
class BlueprintDetectionPipeline:
    def __init__(self):
        self.yolo_model = YOLO('yolov8m-blueprint.pt')
        self.mask_rcnn = MaskRCNN('maskrcnn-rooms.pth')
        self.ocr_engine = PaddleOCR()
    
    def process_drawing(self, image_path, scale_info):
        # 1. Preprocess image
        image = self.load_and_preprocess(image_path)
        
        # 2. Run YOLO for doors, windows, symbols
        detections = self.yolo_model.predict(
            image,
            conf=0.25,  # confidence threshold
            iou=0.45,   # NMS IoU threshold
            classes=[0,1,2,3,4]  # door, window, plumbing, electrical, hvac
        )
        
        # 3. Run Mask R-CNN for room segmentation
        room_masks = self.mask_rcnn.detect(image)
        
        # 4. Extract text with OCR
        text_data = self.ocr_engine.ocr(image)
        room_labels = self.match_labels_to_rooms(text_data, room_masks)
        
        # 5. Post-process and combine results
        results = self.combine_detections(
            detections, room_masks, room_labels, scale_info
        )
        
        # 6. Calculate quantities
        quantities = self.calculate_quantities(results, scale_info)
        
        return {
            \"detections\": results,
            \"quantities\": quantities,
            \"processing_time_ms\": self.timer.elapsed()
        }
```

---

## 3. DATASET STRATEGY {#dataset-strategy}

### Dataset Sources

#### 1. Public Datasets
- **ROBIN (Reconstruction of Buildings in Images)** - 3D floor plan dataset
- **RPLAN** - Floor plan dataset (70K+ residential layouts)
- **FloorNet** - Building floor plan images
- **Structured3D** - 3D structures with floor plans

#### 2. Architectural Drawing Libraries
- **CAD Block Libraries** - Standard architectural symbols
- **Autodesk Symbol Libraries**
- **ArchiCAD Libraries**

#### 3. Licensed/Commercial Sources
- **Construction document repositories**
- **Architectural firm partnerships** (with NDAs)
- **Building permit archives** (public records)

#### 4. Synthetic Data Generation
- Generate synthetic floor plans using procedural generation
- Augment with CAD software (AutoCAD, Revit API)
- Vary: scales, line weights, symbol styles, text fonts

### Labeling Classes

#### Core Labels (YOLO Format)
```yaml
Classes:
  0: door_standard
  1: door_bifold
  2: door_sliding
  3: door_double
  4: window_fixed
  5: window_casement
  6: window_sliding
  7: window_transom
  8: toilet
  9: sink
  10: shower
  11: bathtub
  12: outlet
  13: switch
  14: light_fixture
  15: vent
  16: stair
  17: elevator
  18: column
```

#### Segmentation Labels (Mask R-CNN)
```yaml
Classes:
  0: background
  1: room_living
  2: room_bedroom
  3: room_bathroom
  4: room_kitchen
  5: room_dining
  6: room_hallway
  7: room_utility
  8: room_closet
  9: wall_exterior
  10: wall_interior
```

### Annotation Tools

#### Recommended: **CVAT (Computer Vision Annotation Tool)**
- **Pros:** Open-source, supports bounding boxes + segmentation, team collaboration
- **Deployment:** Self-hosted on company servers for data security
- **Workflow:**
  1. Upload batches of blueprints
  2. Assign to annotators
  3. Draw bounding boxes for objects
  4. Create polygon masks for rooms
  5. Export in YOLO/COCO format

#### Alternative: **Label Studio**
- More flexible, supports custom labeling interfaces
- Good for complex multi-stage annotation

#### Alternative: **Roboflow**
- Cloud-based, excellent augmentation tools
- Auto-annotation with pre-trained models
- Version control for datasets

### Dataset Structure

```
/datasets/
├── blueprint_detection_v1/
│   ├── train/
│   │   ├── images/
│   │   │   ├── blueprint_001.jpg
│   │   │   ├── blueprint_002.jpg
│   │   │   └── ...
│   │   └── labels/
│   │       ├── blueprint_001.txt  # YOLO format
│   │       ├── blueprint_002.txt
│   │       └── ...
│   ├── val/
│   │   ├── images/
│   │   └── labels/
│   ├── test/
│   │   ├── images/
│   │   └── labels/
│   └── data.yaml
│
├── room_segmentation_v1/
│   ├── train/
│   │   ├── images/
│   │   └── masks/  # PNG masks
│   ├── val/
│   └── test/
│
└── metadata/
    ├── annotation_guidelines.md
    ├── label_mapping.json
    └── quality_checks.md
```

### Dataset Size Targets

| Phase | Train Images | Val Images | Test Images | Total |
|-------|-------------|------------|-------------|-------|
| **MVP** | 1,000 | 200 | 200 | 1,400 |
| **Production v1** | 5,000 | 1,000 | 500 | 6,500 |
| **Mature System** | 20,000+ | 4,000 | 2,000 | 26,000+ |

### Data Augmentation Strategy

```python
augmentation_pipeline = [
    # Geometric
    RandomRotate(limit=15),  # slight rotation
    RandomScale(scale_limit=0.1),  # zoom in/out
    HorizontalFlip(p=0.3),  # mirror plans
    
    # Appearance
    RandomBrightnessContrast(p=0.5),  # simulate scan quality
    GaussNoise(p=0.3),  # simulate print artifacts
    Blur(blur_limit=3, p=0.3),  # simulate low-res scans
    
    # Domain-specific
    AddGridLines(p=0.2),  # add/remove grid overlay
    SimulateScanArtifacts(p=0.3),  # coffee stains, fold lines
    RandomLineThickness(p=0.4),  # vary wall line weights
]
```

---

## 4. TRAINING PIPELINE DESIGN {#training-pipeline}

### Phase 1: YOLOv8 Object Detection

#### Training Configuration

```python
# train_yolo_blueprint.py
from ultralytics import YOLO

# Load pretrained YOLOv8 model
model = YOLO('yolov8m.pt')  # medium model

# Training hyperparameters
results = model.train(
    data='datasets/blueprint_detection_v1/data.yaml',
    epochs=200,
    imgsz=1280,  # large image size for blueprints
    batch=16,
    device='0',  # GPU
    
    # Optimization
    optimizer='AdamW',
    lr0=0.001,
    lrf=0.01,  # final learning rate
    momentum=0.937,
    weight_decay=0.0005,
    
    # Augmentation
    hsv_h=0.015,
    hsv_s=0.7,
    hsv_v=0.4,
    degrees=0.0,  # no rotation for blueprints
    translate=0.1,
    scale=0.9,
    
    # Validation
    patience=50,  # early stopping
    save=True,
    save_period=10,  # save every 10 epochs
    
    # Hardware
    workers=8,
    amp=True,  # mixed precision training
)
```

#### Training Hardware Requirements
- **Minimum:** 1x NVIDIA RTX 3090 (24GB VRAM)
- **Recommended:** 2x NVIDIA A100 (40GB VRAM each)
- **Budget Option:** Google Colab Pro+ or Lambda Labs GPU rental

#### Training Time Estimates
- **YOLOv8n (nano):** ~6 hours on RTX 3090
- **YOLOv8m (medium):** ~18 hours on RTX 3090
- **YOLOv8x (extra):** ~48 hours on A100

### Phase 2: Mask R-CNN Room Segmentation

```python
# train_maskrcnn_rooms.py
import detectron2
from detectron2.engine import DefaultTrainer
from detectron2.config import get_cfg

cfg = get_cfg()
cfg.merge_from_file(\"configs/mask_rcnn_R_50_FPN_3x.yaml\")
cfg.DATASETS.TRAIN = (\"blueprint_rooms_train\",)
cfg.DATASETS.TEST = (\"blueprint_rooms_val\",)
cfg.DATALOADER.NUM_WORKERS = 4
cfg.MODEL.WEIGHTS = \"detectron2://COCO-InstanceSegmentation/mask_rcnn_R_50_FPN_3x/137849600/model_final_f10217.pkl\"
cfg.SOLVER.IMS_PER_BATCH = 4
cfg.SOLVER.BASE_LR = 0.001
cfg.SOLVER.MAX_ITER = 10000
cfg.MODEL.ROI_HEADS.NUM_CLASSES = 10  # room types

trainer = DefaultTrainer(cfg)
trainer.resume_or_load(resume=False)
trainer.train()
```

### Phase 3: OCR Integration

```python
# OCR for room labels and dimensions
from paddleocr import PaddleOCR

ocr = PaddleOCR(use_angle_cls=True, lang='en')

def extract_text_from_blueprint(image_path):
    result = ocr.ocr(image_path, cls=True)
    
    text_elements = []
    for line in result:
        for word_info in line:
            bbox = word_info[0]  # [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            text = word_info[1][0]
            confidence = word_info[1][1]
            
            text_elements.append({
                \"bbox\": bbox,
                \"text\": text,
                \"confidence\": confidence
            })
    
    return text_elements
```

### Phase 4: CLIP Embedding (Future Enhancement)

```python
# Use CLIP for semantic understanding of symbols
import clip
import torch

model, preprocess = clip.load(\"ViT-B/32\", device=\"cuda\")

def classify_symbol(image_crop, candidate_labels):
    image = preprocess(image_crop).unsqueeze(0).to(\"cuda\")
    text = clip.tokenize(candidate_labels).to(\"cuda\")
    
    with torch.no_grad():
        image_features = model.encode_image(image)
        text_features = model.encode_text(text)
        
        logits_per_image, _ = model(image, text)
        probs = logits_per_image.softmax(dim=-1).cpu().numpy()
    
    return probs
```

### Model Evaluation Metrics

#### Object Detection (YOLO)
- **mAP@0.5** (mean Average Precision at IOU 0.5)
- **mAP@0.5:0.95** (mAP across IOU thresholds)
- **Precision & Recall** per class
- **Inference Speed** (FPS on target hardware)

#### Segmentation (Mask R-CNN)
- **Mask AP** (Average Precision for masks)
- **Boundary F1 Score**
- **IOU** (Intersection over Union)

#### End-to-End System
- **Detection Accuracy** (% correct detections)
- **False Positive Rate**
- **Processing Time** (< 5 seconds per sheet target)
- **User Correction Rate** (% of detections manually edited)

---

## 5. HUMAN-IN-THE-LOOP SYSTEM {#human-in-loop}

### Correction Workflow

```
┌─────────────────────────────────────────────────────┐
│  1. AI Detection                                     │
│     - YOLO + Mask R-CNN predictions                 │
│     - Confidence scores attached                    │
└────────────────┬────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────┐
│  2. Estimator Review                                 │
│     - View detections on canvas                     │
│     - Color-coded by confidence                     │
│       • Green: High confidence (>0.9)               │
│       • Yellow: Medium confidence (0.7-0.9)         │
│       • Red: Low confidence (<0.7)                  │
│     - Click to accept/reject/modify                 │
└────────────────┬────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────┐
│  3. Correction Types                                 │
│     A. Accept: No change needed                     │
│     B. Reject: Remove false positive                │
│     C. Modify: Adjust bounding box/mask             │
│     D. Add: Draw missing detection                  │
│     E. Relabel: Change class (door → window)        │
└────────────────┬────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────┐
│  4. Feedback Storage                                 │
│     - Original AI prediction                        │
│     - User correction                               │
│     - Correction type & timestamp                   │
│     - User ID (for quality tracking)                │
└────────────────┬────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────┐
│  5. Dataset Improvement                              │
│     - Add corrected examples to training set       │
│     - Prioritize corrections for retraining        │
│     - Active learning: retrain on hard examples    │
└─────────────────────────────────────────────────────┘
```

### Database Schema for Corrections

```sql
CREATE TABLE ai_corrections (
    id SERIAL PRIMARY KEY,
    drawing_id INTEGER REFERENCES drawings(id),
    user_id INTEGER REFERENCES users(id),
    correction_type VARCHAR(20),  -- 'accept', 'reject', 'modify', 'add', 'relabel'
    
    -- Original AI prediction
    original_detection JSONB,  -- {class, bbox, confidence, ...}
    
    -- User correction
    corrected_detection JSONB,  -- {class, bbox, ...}
    
    -- Metadata
    ai_model_version VARCHAR(50),
    confidence_score FLOAT,
    correction_time_seconds INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Index for analytics
CREATE INDEX idx_corrections_type ON ai_corrections(correction_type);
CREATE INDEX idx_corrections_confidence ON ai_corrections(confidence_score);
```

### Continuous Improvement Loop

```python
# Active learning pipeline
class ActiveLearningPipeline:
    def __init__(self):
        self.correction_threshold = 100  # retrain after N corrections
    
    def collect_corrections(self):
        \"\"\"Query database for new corrections\"\"\"
        corrections = db.query(\"\"\"
            SELECT * FROM ai_corrections
            WHERE used_in_training = FALSE
            ORDER BY created_at DESC
            LIMIT 1000
        \"\"\")
        return corrections
    
    def prioritize_samples(self, corrections):
        \"\"\"Focus on most valuable corrections\"\"\"
        priority_samples = []
        
        for corr in corrections:
            # High priority: low confidence but user corrected
            if corr['confidence_score'] < 0.7 and corr['correction_type'] != 'accept':
                priority_samples.append(corr)
            
            # High priority: false positives
            elif corr['correction_type'] == 'reject':
                priority_samples.append(corr)
        
        return priority_samples
    
    def retrain_model(self, new_samples):
        \"\"\"Retrain model with new samples\"\"\"
        # Add samples to dataset
        self.add_to_dataset(new_samples)
        
        # Retrain YOLOv8 (transfer learning)
        model = YOLO('current_best_model.pt')
        results = model.train(
            data='updated_dataset.yaml',
            epochs=50,  # fewer epochs for fine-tuning
            resume=True
        )
        
        # Validate improvements
        val_metrics = model.val()
        
        if val_metrics['mAP50'] > self.current_mAP:
            self.deploy_new_model(model)
    
    def deploy_new_model(self, model):
        \"\"\"Deploy improved model to production\"\"\"
        model.save('production_model_v2.pt')
        # Update version in database
        # Notify users of improved AI
```

### User Correction UI Components

```javascript
// Frontend: Correction Interface
class DetectionCorrectionTool {
  constructor(canvas, detections) {
    this.canvas = canvas;
    this.detections = detections;
    this.corrections = [];
  }
  
  renderDetections() {
    this.detections.forEach(det => {
      // Color by confidence
      const color = this.getConfidenceColor(det.confidence);
      this.canvas.drawBoundingBox(det.bbox, color);
      
      // Add action buttons
      this.canvas.addButton(det.id, 'Accept', () => this.accept(det));
      this.canvas.addButton(det.id, 'Reject', () => this.reject(det));
      this.canvas.addButton(det.id, 'Modify', () => this.modify(det));
    });
  }
  
  accept(detection) {
    this.corrections.push({
      type: 'accept',
      detection_id: detection.id,
      timestamp: Date.now()
    });
    this.canvas.markAsAccepted(detection.id);
  }
  
  reject(detection) {
    this.corrections.push({
      type: 'reject',
      detection_id: detection.id,
      original: detection,
      timestamp: Date.now()
    });
    this.canvas.remove(detection.id);
  }
  
  modify(detection) {
    // Enable drag-to-resize on bounding box
    this.canvas.enableEditMode(detection.id, (newBbox) => {
      this.corrections.push({
        type: 'modify',
        detection_id: detection.id,
        original: detection.bbox,
        corrected: newBbox,
        timestamp: Date.now()
      });
    });
  }
  
  saveCorrections() {
    // Send to backend
    fetch('/api/ai/corrections', {
      method: 'POST',
      body: JSON.stringify({
        drawing_id: this.drawingId,
        corrections: this.corrections
      })
    });
  }
}
```

---

## 6. IMPLEMENTATION ROADMAP {#roadmap}

### Phase 1: MVP (3-4 months)

**Goal:** Basic object detection working on 1,000+ annotated blueprints

**Tasks:**
1. **Month 1:** Dataset collection & annotation
   - Collect 1,500 blueprint images
   - Annotate doors, windows, rooms
   - Set up CVAT annotation pipeline

2. **Month 2:** YOLOv8 training
   - Fine-tune YOLOv8m on blueprint dataset
   - Achieve >80% mAP@0.5 on test set
   - Deploy inference API

3. **Month 3:** Integration & testing
   - Connect AI API to backend
   - Build correction UI
   - Beta test with 10 real estimators

4. **Month 4:** Iteration based on feedback
   - Collect corrections from beta users
   - Retrain model with feedback
   - Launch to limited users

**Success Metrics:**
- ✅ 80%+ detection accuracy
- ✅ < 10 seconds processing time per sheet
- ✅ 90% user satisfaction in beta

---

### Phase 2: Production v1 (3-4 months)

**Goal:** Full-featured AI with room segmentation and 5K+ dataset

**Tasks:**
1. **Month 5:** Expand dataset to 6,500 images
2. **Month 6:** Train Mask R-CNN for room segmentation
3. **Month 7:** Integrate OCR for room labels
4. **Month 8:** Deploy to all users, collect feedback

**Success Metrics:**
- ✅ 90%+ detection accuracy
- ✅ Room segmentation working
- ✅ 10,000+ drawings processed

---

### Phase 3: Advanced Features (6+ months)

**Goal:** CLIP integration, plumbing/electrical symbols, 20K+ dataset

**Tasks:**
1. Expand to plumbing & electrical symbol detection
2. CLIP-based semantic understanding
3. Active learning pipeline fully automated
4. Mobile blueprint capture (camera app)

**Success Metrics:**
- ✅ 95%+ detection accuracy
- ✅ < 5% user correction rate
- ✅ Support for hand-drawn plans

---

## 🔚 CONCLUSION

This architecture provides a clear path from mock AI to production-ready computer vision system. The design prioritizes:

1. **Gradual rollout** - Start with core detection, expand to advanced features
2. **Human feedback** - Corrections improve the model continuously
3. **Scalability** - Can handle 100K+ drawings as dataset grows
4. **Flexibility** - Easy to swap models (YOLOv9, SAM, etc.) as technology improves

**Next Step:** Begin Phase 1 dataset collection and annotation when ready to move beyond mock AI.

---

**Document Version:** 1.0  
**Last Updated:** December 2025  
**Maintained by:** TakeOff.ai Engineering Team
"