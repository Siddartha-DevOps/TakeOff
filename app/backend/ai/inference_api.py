"""
TakeOff.ai AI inference engine.
- If best.pt exists: runs real YOLOv8-seg detection
- If best.pt missing: falls back to mock (same JSON shape as real output)
  so the app works during development before training is complete.
"""
import json
import time
import numpy as np
from dataclasses import dataclass, field, asdict
from typing import Optional, List


CLASSES = {
    0: "living",    1: "bedroom",  2: "bathroom",
    3: "kitchen",   4: "wall",     5: "door",
    6: "window",    7: "balcony",  8: "front_door",
    9: "stair",     10: "storage",
}


@dataclass
class TakeoffAnalysis:
    drawing_id: int
    processing_time_ms: int
    ai_model_version: str
    rooms: list
    doors: list
    windows: list
    walls: list
    balconies: list
    summary: dict
    quantities: list
    confidence_avg: float


class TakeoffAIInference:
    """
    Singleton AI engine. Call get_instance() once at server startup.
    Then call .analyze(image_path, drawing_id) per drawing upload.
    """
    _instance = None

    def __init__(self, model_path: str = "models/best.pt"):
        self.model_path = model_path
        self.model = None
        self._load_model()

    @classmethod
    def get_instance(cls, model_path: str = "models/best.pt"):
        if cls._instance is None:
            cls._instance = cls(model_path)
        return cls._instance

    def _load_model(self):
        try:
            from ultralytics import YOLO
            import os
            if not os.path.exists(self.model_path):
                raise FileNotFoundError(f"Model not found: {self.model_path}")
            self.model = YOLO(self.model_path)
            print(f"[TakeoffAI] Model loaded: {self.model_path}")
        except FileNotFoundError as e:
            print(f"[TakeoffAI] {e}")
            print("[TakeoffAI] Running in MOCK MODE — train model in Colab and copy best.pt to models/")
            self.model = None
        except ImportError:
            print("[TakeoffAI] ultralytics not installed — running in mock mode")
            self.model = None

    def analyze(self, image_path: str, drawing_id: int = 0,
                conf: float = 0.35, iou: float = 0.45) -> TakeoffAnalysis:
        t0 = time.time()
        if self.model is None:
            return self._mock_analysis(drawing_id, t0)
        return self._real_analysis(image_path, drawing_id, conf, iou, t0)

    def _real_analysis(self, image_path, drawing_id, conf, iou, t0):
        results = self.model(image_path, conf=conf, iou=iou, verbose=False)
        r = results[0]
        rooms, doors, windows, walls, balconies = [], [], [], [], []
        all_confs = []

        if r.boxes is not None:
            for i, (box, cls_id, conf_val) in enumerate(zip(
                r.boxes.xyxy.tolist(), r.boxes.cls.tolist(), r.boxes.conf.tolist()
            )):
                name = CLASSES.get(int(cls_id), "unknown")
                x1, y1, x2, y2 = box
                det = {
                    "id": f"{name[0]}{i}", "label": name,
                    "bbox": [round(v, 1) for v in box],
                    "confidence": round(float(conf_val), 3),
                    "area": round((x2 - x1) * (y2 - y1), 1),
                }
                if r.masks and i < len(r.masks.xy):
                    pts = r.masks.xy[i].tolist()
                    det["polygon"] = [[round(x, 2), round(y, 2)] for x, y in pts[::3]]

                all_confs.append(conf_val)
                if name == "door":           doors.append(det)
                elif name == "window":        windows.append(det)
                elif name == "wall":          walls.append(det)
                elif name == "balcony":       balconies.append(det)
                else:                         rooms.append(det)

        quantities = self._quantities(rooms, doors, windows, walls)
        summary = {
            "rooms": len(rooms), "doors": len(doors),
            "windows": len(windows), "walls": len(walls),
            "totalArea": sum(r["area"] for r in rooms),
        }
        return TakeoffAnalysis(
            drawing_id=drawing_id,
            processing_time_ms=int((time.time() - t0) * 1000),
            ai_model_version="yolov8m-seg-v1.0",
            rooms=rooms, doors=doors, windows=windows,
            walls=walls, balconies=balconies,
            summary=summary, quantities=quantities,
            confidence_avg=round(float(np.mean(all_confs)) if all_confs else 0, 3)
        )

    def _quantities(self, rooms, doors, windows, walls):
        flooring = {"bedroom": "Carpet", "bathroom": "Tile", "kitchen": "Tile"}
        by_mat = {}
        for r in rooms:
            mat = flooring.get(r["label"], "Hardwood")
            by_mat[mat] = by_mat.get(mat, 0) + r["area"]
        qs = [{"trade": "Flooring", "item": f"{mat} flooring", "quantity": round(a, 1), "unit": "sf"}
              for mat, a in by_mat.items()]
        total_lf = sum(max(w["bbox"][2]-w["bbox"][0], w["bbox"][3]-w["bbox"][1]) for w in walls)
        qs += [
            {"trade": "Drywall",   "item": "Wall linear footage", "quantity": round(total_lf / 9, 1), "unit": "lf"},
            {"trade": "Drywall",   "item": "Gypsum board (9ft)",  "quantity": round(total_lf, 1),     "unit": "sf"},
            {"trade": "Doors",     "item": "Interior doors",      "quantity": len(doors),             "unit": "ea"},
            {"trade": "Windows",   "item": "Window openings",     "quantity": len(windows),           "unit": "ea"},
            {"trade": "Electrical","item": "Outlets (est.)",      "quantity": max(1, len(rooms)*5),   "unit": "ea"},
            {"trade": "Plumbing",  "item": "Fixtures (est.)",     "quantity": sum(3 if r["label"]=="bathroom" else 1 for r in rooms if r["label"] in ("bathroom","kitchen")), "unit": "ea"},
        ]
        return qs

    def _mock_analysis(self, drawing_id: int, t0: float) -> TakeoffAnalysis:
        """Used during development before best.pt is trained."""
        import random
        rooms = [
            {"id":"r0","label":"living",   "bbox":[60, 60, 260, 200],"confidence":0.98,"area":40000},
            {"id":"r1","label":"kitchen",  "bbox":[320,60, 500, 200],"confidence":0.97,"area":32400},
            {"id":"r2","label":"bedroom",  "bbox":[340,220,560,440],"confidence":0.96,"area":48400},
            {"id":"r3","label":"bathroom", "bbox":[560,220,720,340],"confidence":0.94,"area":19200},
        ]
        doors   = [{"id":f"d{i}","label":"door",  "bbox":[100+i*50,100,128+i*50,140],"confidence":round(0.92+random.uniform(0,0.06),3),"area":1080} for i in range(8)]
        windows = [{"id":f"w{i}","label":"window","bbox":[80+i*60,60,130+i*60,80],  "confidence":round(0.91+random.uniform(0,0.07),3),"area":1000} for i in range(10)]
        return TakeoffAnalysis(
            drawing_id=drawing_id,
            processing_time_ms=int((time.time()-t0)*1000)+1200,
            ai_model_version="mock_v1.0",
            rooms=rooms, doors=doors, windows=windows,
            walls=[], balconies=[],
            summary={"rooms":4,"doors":8,"windows":10,"walls":42,"totalArea":4280},
            quantities=[
                {"trade":"Flooring","item":"Hardwood flooring","quantity":420,"unit":"sf"},
                {"trade":"Flooring","item":"Carpet flooring",  "quantity":510,"unit":"sf"},
                {"trade":"Doors",   "item":"Interior doors",   "quantity":8,  "unit":"ea"},
                {"trade":"Windows", "item":"Window openings",  "quantity":10, "unit":"ea"},
                {"trade":"Drywall", "item":"Wall linear footage","quantity":312,"unit":"lf"},
                {"trade":"Electrical","item":"Outlets (est.)", "quantity":40, "unit":"ea"},
            ],
            confidence_avg=0.95
        )