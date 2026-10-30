from pathlib import Path
import requests
from clip.clip import _MODELS
from ultralytics import YOLOWorld
from ultralytics.utils import WEIGHTS_DIR
from download_helpers import download

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "module3-demo" if (ROOT / "module3-demo").exists() else ROOT
url = _MODELS["ViT-B/32"]
target = WEIGHTS_DIR / "clip" / Path(url).name
size = int(requests.head(url, timeout=30).headers["Content-Length"])
download(url, target, size, url.split("/")[-2])
model = YOLOWorld(str(ROOT / ".video-tools/models/yolov8s-worldv2.pt"))
names = ['table', 'crate', 'bag', 'sack of rice', 'vegetable stand', 'fruit stand',
         'pile of goods', 'cardboard box', 'person', 'car', 'motorcycle', 'bicycle']
model.model.set_classes(names, cache_clip_model=False)
model.model.names = names
out = APP / "obstruction-world.pt"
model.save(str(out))
print("Saved", out, flush=True)
for scene in ["motorbike", "parked-car", "shop-goods", "bicycles"]:
    image = APP / "examples/generated-scenarios" / scene / "start.png"
    result = model.predict(str(image), imgsz=960, conf=.24, device="cpu", verbose=False, agnostic_nms=True)[0]
    print(scene, [(names[int(b.cls.item())], round(b.conf.item(), 2), [round(x) for x in b.xyxy[0].tolist()]) for b in result.boxes], flush=True)
    result.save(filename=str(ROOT / ".video-tools" / f"world-{scene}.jpg"))
