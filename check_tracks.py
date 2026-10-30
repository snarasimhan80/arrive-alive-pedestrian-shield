"""Inspect path-to-road tracks in the original synthetic fixed-camera clip."""
import json
from pathlib import Path
import cv2
import sys
from analyzer import detect_scene, polygon_mask, read_first_frame
from scene_signals import ShortTrackMatcher

source = Path(sys.argv[1] if len(sys.argv) > 1 else 'examples/indian-footpath-continuous-motion.mp4')
config = json.loads(Path('examples/indian-footpath-continuous-motion-settings.json').read_text())
_, meta = read_first_frame(source)
w, h = meta['width'], meta['height']
footpath = polygon_mask(config['polygon'], w, h)
road = polygon_mask(config['road_polygon'], w, h)
matcher = ShortTrackMatcher(w, 0.12)
cap = cv2.VideoCapture(str(source))
n = 0
while True:
    ok, frame = cap.read()
    if not ok: break
    if n % max(1, round(meta['fps']/2)) == 0:
        frame = cv2.resize(frame, (w, h))
        blockers, people, _ = detect_scene(frame, footpath, road, .12)
        matches = matcher.update(people, n / meta['fps'])
        for item, track, previous in matches:
            if previous and previous.zone != track.zone:
                print(f'{n/meta["fps"]:4.1f}s ID {track.id}: {previous.zone} -> {track.zone} at {track.point}; blocked={bool(blockers)}')
        print(f'{n/meta["fps"]:4.1f}s people={[(p["zone"],p["footpoint"]) for p in people]} blockers={len(blockers)}')
    n += 1
cap.release()
