"""One-click screen, including tracked crossings for the saved demo camera."""

from __future__ import annotations

import json
import hashlib
import math
import shutil
import subprocess
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from analyzer import (PERSON_CLASS, SAMPLE_FPS, VEHICLE_CLASSES, detect_scene,
                      get_model, polygon_mask, read_first_frame)
from scene_signals import largest_person_group
from pedestrian_tracks import PedestrianTrackMatcher

ROOT = Path(__file__).resolve().parent
CAMERA_CONFIG = json.loads((ROOT / 'examples/indian-footpath-continuous-motion-settings.json').read_text())
CAMERA_REFERENCE = cv2.imread(str(ROOT / 'examples/demo-camera-reference.jpg'))
REAL_PRESET_PATH = ROOT / 'examples/real-scenarios/presets.json'
REAL_PRESETS = json.loads(REAL_PRESET_PATH.read_text()) if REAL_PRESET_PATH.exists() else {}
GENERATED_PRESET_PATH = ROOT / 'examples/generated-scenarios/presets.json'
if GENERATED_PRESET_PATH.exists():
    REAL_PRESETS.update(json.loads(GENERATED_PRESET_PATH.read_text()))


def _same_demo_camera(frame: np.ndarray) -> bool:
    """Use saved zones only for the synthetic fixed scene, regardless of filename."""
    if CAMERA_REFERENCE is None:
        return False
    def signature(image):
        small = cv2.resize(image, (128, 72), interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(small[:18], cv2.COLOR_BGR2GRAY)
    reference, candidate = signature(CAMERA_REFERENCE), signature(frame)
    corr = float(cv2.matchTemplate(reference, candidate, cv2.TM_CCOEFF_NORMED)[0, 0])
    difference = float(np.abs(reference.astype(np.float32) - candidate).mean() / 255)
    return corr >= .95 and difference <= .07


def _calibrated_clip(source: Path, first: np.ndarray, meta: dict) -> bool:
    if meta['kind'] != 'video' or not _same_demo_camera(first):
        return False
    cap = cv2.VideoCapture(str(source))
    try:
        for fraction in (.4, .8):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(meta['frame_count'] * fraction))
            ok, frame = cap.read()
            if not ok or not _same_demo_camera(frame):
                return False
    finally:
        cap.release()
    return True


def _saved_preset(source: Path, first: np.ndarray, meta: dict) -> dict | None:
    """Apply a saved example's marked zones only to its exact, reviewed footage."""
    if meta['kind'] != 'video':
        return None
    digest = hashlib.sha256()
    with source.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    preset = REAL_PRESETS.get(digest.hexdigest())
    if preset:
        return preset
    if _calibrated_clip(source, first, meta):
        return {**CAMERA_CONFIG, 'name': 'Synthetic Indian fixed camera',
                'footage_type': 'synthetic'}
    return None


def crossing_score(crossings: int, blocked_crossings: int, nearby_frames: int,
                   blocker_frames: int, sampled_frames: int,
                   road_person_seconds: float = 0, duration: float = 0) -> int:
    if sampled_frames <= 0:
        return 0
    road_share = min(1, road_person_seconds / duration) if duration > 0 else 0
    return min(100, round(5 + 25 * min(crossings, 3) + 10 * min(blocked_crossings, 1)
                          + 10 * nearby_frames / sampled_frames
                          + 5 * blocker_frames / sampled_frames
                          + 15 * road_share))


def screening_score(frames_with_people: int, frames_with_nearby_pair: int,
                    sampled_frames: int, max_people: int, max_group: int) -> int:
    """A repeatable visual cue index, not an accident probability."""
    if sampled_frames <= 0:
        return 0
    people_share = frames_with_people / sampled_frames
    nearby_share = frames_with_nearby_pair / sampled_frames
    return min(100, round(65 * nearby_share + 10 * people_share
                          + 5 * min(max_people, 2) + 3 * min(max_group, 2)))


def _nearby(person: dict, vehicle: dict, width: int, height: int) -> bool:
    """Check image-space proximity of detection ground points, as a cue only."""
    px, py = person["footpoint"]
    vx, vy = vehicle["footpoint"]
    return math.hypot((px - vx) / width, (py - vy) / height) <= 0.27


def quick_analyze(source: Path, job_dir: Path,
                  progress: Callable[[int, int], None] | None = None) -> dict:
    first, meta = read_first_frame(source)
    width, height = meta["width"], meta["height"]
    preset = _saved_preset(source, first, meta)
    calibrated = preset is not None
    footpath = polygon_mask(preset['polygon'], width, height) if calibrated else None
    road = polygon_mask(preset['road_polygon'], width, height) if calibrated else None
    footpath_pixels = footpath.astype(bool) if calibrated else None
    tracker = PedestrianTrackMatcher(width, .12) if calibrated else None
    model = get_model()
    if meta["kind"] == "video":
        cap = cv2.VideoCapture(str(source))
        target_fps = 4.0 if preset and preset.get('footage_type') in {'real_stock', 'generated'} else SAMPLE_FPS
        stride = max(1, round(meta["fps"] / target_fps))
        total = math.ceil(meta["frame_count"] / stride)
        raw = job_dir / "annotated-raw.mp4"
        writer = cv2.VideoWriter(str(raw), cv2.VideoWriter_fourcc(*"mp4v"),
                                 meta["fps"], (width, height))
        if not writer.isOpened():
            cap.release()
            raise RuntimeError("Could not create the annotated video.")
    else:
        cap, writer, stride, total = None, None, 1, 1

    sampled = frames_with_people = frames_with_vehicles = nearby_frames = blocker_frames = 0
    max_people = max_group = 0
    snapshots = []
    movements = []
    counted_tracks = set()
    event_by_track = {}
    path_origins: dict[int, tuple[float, tuple[int, int]]] = {}
    last_blockage_seconds = -math.inf
    recent_blockers = []
    cached_goods = []
    cached_ink = None
    frame_number = 0
    try:
        while True:
            if cap is None:
                ok, frame = (True, first) if frame_number == 0 else (False, None)
            else:
                ok, frame = cap.read()
            if not ok or frame is None:
                break
            frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
            if frame_number % stride:
                if writer is not None and cached_ink is not None:
                    smooth_frame = frame.copy()
                    if calibrated:
                        overlay = smooth_frame.copy()
                        overlay[footpath_pixels] = (35, 135, 50)
                        cv2.addWeighted(overlay, .09, smooth_frame, .91, 0, smooth_frame)
                    ink, ink_mask = cached_ink
                    smooth_frame[ink_mask] = ink[ink_mask]
                    writer.write(smooth_frame)
                frame_number += 1
                continue
            seconds = frame_number / meta["fps"] if cap is not None else 0.0
            if calibrated:
                refresh_goods = sampled % 4 == 0
                blockers, people, road_vehicles = detect_scene(frame, footpath, road, .12,
                                                               include_goods=refresh_goods)
                if refresh_goods:
                    cached_goods = [item for item in blockers if item['class'] == 'shop goods']
                else:
                    blockers.extend(cached_goods)
                blockers = [item for item in blockers
                            if item['box'][2] - item['box'][0] >= width * (.025 if item['class'] == 'shop goods' else .07)
                            and item['box'][3] - item['box'][1] >= height * .05]
                vehicles = [item for item in blockers + road_vehicles
                            if item['class'] in VEHICLE_CLASSES.values()]
                if blockers:
                    blocker_frames += 1
                    last_blockage_seconds = seconds
                    recent_blockers = blockers
            else:
                blockers = []
                result = model.predict(frame, conf=0.25, imgsz=640,
                                       classes=[PERSON_CLASS, *VEHICLE_CLASSES],
                                       device="cpu", verbose=False)[0]
                people, vehicles = [], []
                if result.boxes is not None:
                    for box in result.boxes:
                        class_id = int(box.cls.item())
                        x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].cpu().tolist())
                        item = {"box": [x1, y1, x2, y2],
                                "footpoint": [(x1 + x2) // 2, max(0, y2 - 2)],
                                "class": "person" if class_id == PERSON_CLASS
                                else VEHICLE_CLASSES[class_id]}
                        if class_id == PERSON_CLASS:
                            if y2 - y1 >= height * 0.17:
                                people.append(item)
                        elif x2 - x1 >= width * 0.12 and y2 - y1 >= height * 0.10:
                            vehicles.append(item)
            pairs = [(person, vehicle) for person in people for vehicle in vehicles
                     if _nearby(person, vehicle, width, height)]
            sampled += 1
            frames_with_people += bool(people)
            frames_with_vehicles += bool(vehicles)
            nearby_frames += bool(pairs)
            max_people = max(max_people, len(people))
            max_group = max(max_group, largest_person_group(people, width, height))
            new_movements = []
            if tracker:
                # Distant, tiny boxes have unstable footpoints and can join
                # unrelated walkers. Keep them out of movement measurement.
                trackable = [person for person in people
                             if person['box'][3] - person['box'][1] >= height * .12]
                for person, current, previous in tracker.update(trackable, seconds, frame):
                    person['_track_id'] = current.id
                    if current.zone == 'footpath':
                        path_origins[current.id] = (seconds, tuple(current.point))
                    origin = path_origins.get(current.id)
                    if (previous and previous.zone == 'road' and current.zone == 'road' and origin
                            and seconds - origin[0] <= 1.5
                            and math.dist(origin[1], current.point) >= width * .025
                            and current.id not in counted_tracks):
                        counted_tracks.add(current.id)
                        def close_to_blocker(item):
                            x1, y1, x2, y2 = item['box']
                            return min(math.hypot(max(x1-p[0], 0, p[0]-x2),
                                                  max(y1-p[1], 0, p[1]-y2))
                                       for p in (origin[1], current.point)) <= width * .20
                        event = {'seconds': round(seconds, 1), 'track_id': current.id,
                                 'box': person['box'], 'from': list(origin[1]),
                                 'to': list(current.point),
                                 'blocked_nearby': seconds - last_blockage_seconds <= 2 and any(close_to_blocker(item) for item in recent_blockers),
                                 'road_seconds': 0.0, 'trail': [list(origin[1]), list(current.point)]}
                        new_movements.append(event)
                        movements.append(event)
                        event_by_track[current.id] = event
                    event = event_by_track.get(current.id)
                    if event and current.zone == 'road':
                        person['_displaced'] = True
                        event['trail'].append(list(current.point))
                        if previous and previous.zone == 'road':
                            event['road_seconds'] = round(event['road_seconds'] + seconds - previous.seconds, 2)
                        person['_trail'] = event['trail']
                    elif event and current.zone == 'footpath' and 'return_seconds' not in event:
                        event['return_seconds'] = round(seconds, 1)
                        person['_returned'] = True
            marked = frame.copy()
            base_frame = frame.copy()
            if calibrated:
                overlay = marked.copy()
                overlay[footpath_pixels] = (35, 135, 50)
                cv2.addWeighted(overlay, .09, marked, .91, 0, marked)
                base_frame = marked.copy()
                points = np.array([[round(x * (width - 1)), round(y * (height - 1))]
                                   for x, y in preset['polygon']], dtype=np.int32)
                cv2.polylines(marked, [points], True, (80, 220, 100), 2)
            display_vehicles = road_vehicles if calibrated else vehicles
            for items, color in ((blockers, (30, 155, 245)), (display_vehicles, (230, 150, 30)), (people, (45, 185, 55))):
                for item in items:
                    x1, y1, x2, y2 = item["box"]
                    if (item['class'] == 'person' and y2 - y1 < height * .12) or (
                        item['class'] != 'person' and item not in blockers and x2 - x1 < width * .10
                    ):
                        continue
                    if item.get('_displaced'):
                        cv2.rectangle(marked, (x1, y1), (x2, y2), (20, 20, 245), 4)
                        cv2.rectangle(marked, (x1, y1), (min(width, x1+72), y1+21), (20, 20, 245), -1)
                        cv2.putText(marked, 'IN ROAD', (x1+4, y1+15), cv2.FONT_HERSHEY_SIMPLEX,
                                    .43, (255, 255, 255), 1, cv2.LINE_AA)
                        cv2.polylines(marked, [np.array(item['_trail'], dtype=np.int32)], False,
                                      (20, 20, 245), 4, cv2.LINE_AA)
                        cv2.circle(marked, tuple(item['footpoint']), 11, (20, 20, 245), 3)
                        continue
                    cv2.rectangle(marked, (x1, y1), (x2, y2), color, 2)
                    label = 'GOODS' if item['class'] == 'shop goods' else item['class'].upper()
                    cv2.putText(marked, label, (max(4, x1), max(24, y1 - 7)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
            for event in new_movements:
                x1, y1, x2, y2 = event['box']
                cv2.rectangle(marked, (x1, y1), (x2, y2), (20, 20, 245), 5)
                cv2.arrowedLine(marked, tuple(event['from']), tuple(event['to']),
                                (20, 20, 245), 5, tipLength=.3)
            if calibrated and any(item.get('_displaced') for item in people):
                cv2.rectangle(marked, (0, 0), (width, 49), (20, 20, 180), -1)
                header = ('1 PERSON STEPPED INTO THE ROAD' if len(movements) == 1
                          else f'{len(movements)} PEOPLE STEPPED INTO THE ROAD')
                cv2.putText(marked, header,
                            (12, 32), cv2.FONT_HERSHEY_SIMPLEX, .75,
                            (255, 255, 255), 2, cv2.LINE_AA)
            cv2.rectangle(marked, (0, height - 45), (width, height), (18, 26, 24), -1)
            cue = ('GENERATED SCENE / TRACKED MOVEMENT' if preset and preset.get('footage_type') == 'generated'
                   else 'SAVED PATH / TRACKED MOVEMENT' if calibrated
                   else 'UNCALIBRATED VISUAL SCREEN')
            cv2.putText(marked, f"{seconds:05.1f}s  {cue}", (14, height - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
            cached_ink = (marked.copy(), np.any(marked != base_frame, axis=2))
            if writer is not None:
                writer.write(marked)
            if new_movements:
                name = f"screen-{len(snapshots) + 1:02d}.jpg"
                cv2.imwrite(str(job_dir / name), marked)
                snapshots.append({"seconds": round(seconds, 1), "file": name, "kind": "crossing"})
                for event in new_movements:
                    event['snapshot'] = name
            elif (pairs and not any(s["kind"] == "nearby" for s in snapshots)) or (
                sampled == 1 or sampled % 12 == 0
            ) and len(snapshots) < 5:
                name = f"screen-{len(snapshots) + 1:02d}.jpg"
                cv2.imwrite(str(job_dir / name), marked)
                snapshots.append({"seconds": round(seconds, 1), "file": name,
                                  "kind": "nearby" if pairs else "sample"})
            if progress:
                progress(sampled, total)
            frame_number += 1
    finally:
        if cap is not None:
            cap.release()
        if writer is not None:
            writer.release()

    annotated = None
    if meta["kind"] == "video":
        annotated = "annotated.mp4"
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run([ffmpeg, "-loglevel", "error", "-y", "-i", str(raw),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", str(job_dir / annotated)],
                       check=True, capture_output=True, text=True)
        raw.unlink(missing_ok=True)
    blocked_crossings = sum(event['blocked_nearby'] for event in movements)
    road_person_seconds = round(sum(event['road_seconds'] for event in movements), 2)
    score = (crossing_score(len(movements), blocked_crossings, nearby_frames,
                            blocker_frames, sampled, road_person_seconds,
                            meta['duration_seconds']) if calibrated else
             screening_score(frames_with_people, nearby_frames, sampled,
                             max_people, max_group))
    report = {
        "mode": "quick", "analysis_version": "obstruction-detours-20261022",
        "model": "yolov8n-seg.pt + obstruction-world.pt" if calibrated else "yolov8n-seg.pt", "score": score,
        "score_label": "Higher visual concern" if score >= 60 else "Lower visual concern",
        "source_type": meta["kind"], "duration_seconds": meta["duration_seconds"],
        "sampled_frames": sampled, "frames_with_people": frames_with_people,
        "analysis_fps": round(meta['fps'] / stride, 2), "output_fps": meta['fps'],
        "frames_with_vehicles": frames_with_vehicles,
        "frames_with_nearby_pair": nearby_frames,
        "max_people_in_frame": max_people, "max_nearby_group": max_group,
        "annotated_video": annotated, "snapshots": snapshots,
        "camera_preset": preset['name'] if calibrated else None,
        "footage_type": preset.get('footage_type') if calibrated else None,
        "displacement_status": "observed_crossing" if calibrated else "not_measured",
        "path_to_road_crossings": len(movements) if calibrated else None,
        "crossings_with_blockage_nearby": blocked_crossings if calibrated else None,
        "blocker_frames": blocker_frames if calibrated else None,
        "road_person_seconds": road_person_seconds if calibrated else None,
        "returned_to_path_count": sum('return_seconds' in event for event in movements),
        "movement_events": movements,
        "score_method": (
            "5 baseline + 25 per tracked path-to-road crossing (up to three) + 10 if a crossing was near a visible blocker + up to 10 for people near vehicles + up to 5 for frames with a path blocker + up to 15 for tracked person-seconds in the road divided by clip duration, capped at 100"
            if calibrated else
            "65 x nearby-frame share + 10 x people-frame share + up to 10 for visible people count + up to 6 for nearby group size, capped at 100"),
        "limits": ([
            "The green path boundary is a saved marking for this exact sample video, not automatic footpath detection.",
            "Red events are short visual tracks crossing from the marked path into the marked road. Review each event.",
            "Video cannot prove a blocker caused the crossing; 'blocker nearby' means temporal co-occurrence only.",
            "This score is a demo visual index, not measured speed, FR-24 exposure, crash risk, or mortality.",
            "Shop-goods proposals use approximate bounding boxes rather than measured object footprints.",
            "Tracks can bridge a brief occlusion; time in the road is an estimate rather than a continuous ground-truth measurement.",
            "Person boxes shorter than 12% of the image height are excluded from crossing tracks because distant footpoints are unstable.",
            "Tracking can miss people or join two people incorrectly. Generated or stock examples are not field validation.",
        ] if calibrated else [
            "Nearby means close in the image, not a measured ground distance.",
            "This upload has no reviewed path marking. Mark its footpath and road to measure crossings.",
            "No path-to-road movement is established by this general screening score.",
            "Vehicle speed in km/h, peak pedestrian flow and crash probability are not measured.",
            "This is a visual screening cue, not the proposal's FR-24 exposure index.",
            "Every model flag needs human review; missed people and vehicles are possible.",
        ]),
    }
    (job_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
