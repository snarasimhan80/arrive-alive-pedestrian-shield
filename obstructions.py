"""Fixed-vocabulary YOLO-World proposals for goods outside COCO vehicle classes.

Text embeddings are frozen into the local checkpoint. Inference needs no CLIP
download or network service. These are box proposals requiring human review.
"""
from pathlib import Path
from ultralytics import YOLOWorld

MODEL_PATH = Path(__file__).resolve().parent / "obstruction-world.pt"
GOODS_LABELS = {"table", "crate", "sack of rice", "vegetable stand",
                "fruit stand", "pile of goods", "cardboard box"}
_model = None


def _intersection_over_union(a, b):
    intersection = max(0, min(a[2], b[2])-max(a[0], b[0])) * max(0, min(a[3], b[3])-max(a[1], b[1]))
    area_a = max(0, a[2]-a[0]) * max(0, a[3]-a[1])
    area_b = max(0, b[2]-b[0]) * max(0, b[3]-b[1])
    return intersection / max(1, area_a + area_b - intersection)


def goods_proposals(frame, occupied_boxes):
    global _model
    if not MODEL_PATH.exists():
        raise RuntimeError("The local shop-goods detector weights are missing. Restore obstruction-world.pt from the source package.")
    if _model is None:
        _model = YOLOWorld(str(MODEL_PATH))
    names = _model.names
    allowed = [i for i, name in (names.items() if isinstance(names, dict) else enumerate(names))
               if name in GOODS_LABELS]
    result = _model.predict(frame, conf=.24, imgsz=960, classes=allowed,
                            agnostic_nms=True, device="cpu", verbose=False)[0]
    height, width = frame.shape[:2]
    output = []
    for box in result.boxes:
        bounds = [round(value) for value in box.xyxy[0].cpu().tolist()]
        x1, y1, x2, y2 = bounds
        if (x2-x1)*(y2-y1) < width*height*.0015:
            continue
        if any(_intersection_over_union(bounds, other) > .35 for other in occupied_boxes):
            continue
        output.append({"class": "shop goods", "object_label": names[int(box.cls.item())],
                       "confidence": round(float(box.conf.item()), 3), "box": bounds,
                       "mask_method": "box approximation", "detector": "YOLO-World"})
    return output
