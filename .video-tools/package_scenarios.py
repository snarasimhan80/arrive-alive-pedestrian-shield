"""Publishable MP4s retain generated motion and carry a provenance label."""
from pathlib import Path
import hashlib
import json
import subprocess
import cv2

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "module3-demo" if (ROOT / "module3-demo").exists() else ROOT
BASE = APP / "examples/generated-scenarios"
ITEMS = [
    ("parked-car", "01-parked-car", "A car across the footpath", "Two walkers detour into the road around a car that blocks the pavement."),
    ("shop-goods", "02-shop-goods", "Shop goods leave no walking room", "A pedestrian steps into the road to pass crates, sacks and a display table."),
    ("motorbike", "03-motorbike", "A motorcycle blocks the route", "A walker steps around a motorcycle’s front wheel and returns to the footpath."),
    ("bicycles", "04-bicycles", "Bicycles across the pavement", "A walker leaves the footpath to pass the protruding bicycle wheels."),
]
calibrations = json.loads((BASE / "calibrations.json").read_text())

def stamp(frame):
    original = frame[:37, :285].copy()
    frame[:37, :285] = (original * .45).astype("uint8")
    cv2.putText(frame, "GENERATED DEMO FOOTAGE", (12, 25), cv2.FONT_HERSHEY_SIMPLEX,
                .55, (255, 255, 255), 1, cv2.LINE_AA)
    return frame

presets = {}
manifest = []
for scene, slug, title, description in ITEMS:
    manifest.append({"slug": slug, "title": title, "description": description,
                     "footage_type": "generated", "poster": True})
    source = BASE / scene / "generated.mp4"
    if not source.exists() or subprocess.run(["ffprobe", "-v", "error", str(source)], capture_output=True).returncode:
        poster = BASE / (slug + ".jpg")
        if not poster.exists():
            frame = cv2.imread(str(BASE / scene / "start.png"))
            cv2.imwrite(str(poster), stamp(cv2.resize(frame, (1024, 576))))
        print("WAITING", scene, flush=True)
        continue
    output = BASE / (slug + ".mp4")
    valid_output = output.exists() and subprocess.run(["ffprobe", "-v", "error", str(output)], capture_output=True).returncode == 0
    if not valid_output or output.stat().st_mtime < source.stat().st_mtime:
        cap = cv2.VideoCapture(str(source))
        fps = cap.get(cv2.CAP_PROP_FPS)
        width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        raw = BASE / (slug + "-raw.mp4")
        writer = cv2.VideoWriter(str(raw), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
        if not writer.isOpened():
            raise RuntimeError("Cannot create source MP4")
        count = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame = stamp(frame)
            writer.write(frame)
            if count == 0:
                cv2.imwrite(str(BASE / (slug + ".jpg")), frame)
            count += 1
        cap.release()
        writer.release()
        if count != 121:
            raise RuntimeError(f"Incomplete source {scene}: {count} frames")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-c:v", "libx264",
                        "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)], check=True)
        raw.unlink()
        print("PACKAGED", scene, count, "frames", flush=True)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    presets[digest] = calibrations[scene]
(BASE / "presets.json").write_text(json.dumps(presets, indent=2))
(BASE / "manifest.json").write_text(json.dumps(manifest, indent=2))
print("READY", len(presets), "/", len(ITEMS), flush=True)
