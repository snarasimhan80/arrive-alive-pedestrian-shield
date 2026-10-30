"""Local, reviewable footpath-obstruction analysis for short video clips."""

from __future__ import annotations

import csv
import json
import math
import shutil
import statistics
import subprocess
import zipfile
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import torch
from ultralytics import YOLO

# This CPU lacks NNPACK support; asking for it on every inference floods logs.
torch.backends.nnpack.set_flags(False)

from scene_signals import (FootpathFlowCounter, PersonMovementTracker, SpeedGateTracker,
                           exposure_estimate, largest_person_group)
from obstructions import goods_proposals


ROOT = Path(__file__).resolve().parent
MODEL_PATH = ROOT / "yolov8n-seg.pt"
VEHICLE_CLASSES = {1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
PERSON_CLASS = 0
MAX_WIDTH = 960
MAX_DURATION_SECONDS = 120
SAMPLE_FPS = 2.0

_model: YOLO | None = None


def get_model() -> YOLO:
    global _model
    if _model is None:
        if not MODEL_PATH.exists():
            raise RuntimeError(
                "Local model weights are missing. Run: .venv/bin/python download_model.py"
            )
        _model = YOLO(str(MODEL_PATH))
    return _model


def scaled_size(width: int, height: int) -> tuple[int, int]:
    scale = min(1.0, MAX_WIDTH / width)
    return max(1, round(width * scale)), max(1, round(height * scale))


def read_first_frame(source: Path) -> tuple[np.ndarray, dict]:
    if source.suffix.lower() in {".jpg", ".jpeg", ".png"}:
        frame = cv2.imread(str(source))
        if frame is None:
            raise ValueError("Could not read this image.")
        kind, fps, frame_count, duration = "image", 1.0, 1, 0.0
    else:
        cap = cv2.VideoCapture(str(source))
        if not cap.isOpened():
            raise ValueError("Could not open this video. Try an MP4 or MOV file.")
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None or not math.isfinite(fps) or fps <= 0:
            raise ValueError("The video has no readable frames or frame rate.")
        if frame_count <= 0:
            raise ValueError("Could not determine video length. Re-encode as MP4 and try again.")
        duration = frame_count / fps
        if duration > MAX_DURATION_SECONDS:
            raise ValueError("Use a clip no longer than two minutes for this demo.")
        kind = "video"
    width, height = scaled_size(frame.shape[1], frame.shape[0])
    frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
    return frame, {
        "kind": kind,
        "width": width,
        "height": height,
        "fps": fps,
        "frame_count": frame_count,
        "duration_seconds": round(duration, 2),
    }


def polygon_mask(points: list[list[float]], width: int, height: int) -> np.ndarray:
    if len(points) < 3 or len(points) > 30:
        raise ValueError("Mark the footpath with 3 to 30 points.")
    if any(
        not isinstance(p, list)
        or len(p) != 2
        or any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 or v > 1 for v in p)
        for p in points
    ):
        raise ValueError("Invalid footpath coordinates.")
    vertices = np.array(
        [[round(p[0] * (width - 1)), round(p[1] * (height - 1))] for p in points],
        dtype=np.int32,
    )
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(mask, [vertices], 1)
    if int(mask.sum()) < 100:
        raise ValueError("The marked footpath area is too small.")
    return mask


def overlap_score(object_mask: np.ndarray, footpath: np.ndarray) -> tuple[float, int]:
    """Fraction of the object's lower visible region inside the marked footpath."""
    ys, _ = np.nonzero(object_mask)
    if ys.size == 0:
        return 0.0, 0
    ground_band = object_mask.copy()
    cutoff = int(np.quantile(ys, 0.70))
    ground_band[:cutoff, :] = False
    pixels = int(ground_band.sum())
    overlap_pixels = int(np.logical_and(ground_band, footpath).sum())
    return (overlap_pixels / pixels if pixels else 0.0), overlap_pixels


def width_line_profile(object_mask: np.ndarray, footpath: np.ndarray,
                       line: list[list[float]], samples: int = 101) -> list[bool]:
    """Visible object overlap along a marked cross-section; provisional width cue."""
    ys, _ = np.nonzero(object_mask)
    if ys.size == 0:
        return [False] * samples
    ground_band = object_mask.copy()
    ground_band[:int(np.quantile(ys, 0.70)), :] = False
    occupied = np.logical_and(ground_band, footpath)
    height, width = footpath.shape
    a = np.array([line[0][0] * (width - 1), line[0][1] * (height - 1)])
    b = np.array([line[1][0] * (width - 1), line[1][1] * (height - 1)])
    profile = []
    for fraction in np.linspace(0, 1, samples):
        x, y = np.rint(a + fraction * (b - a)).astype(int)
        x0, x1 = max(0, x - 3), min(width, x + 4)
        y0, y1 = max(0, y - 3), min(height, y + 4)
        profile.append(bool(occupied[y0:y1, x0:x1].any()))
    return profile


def detect_scene(frame: np.ndarray, footpath: np.ndarray, road: np.ndarray | None,
                 min_overlap: float, width_line: list[list[float]] | None = None,
                 include_goods: bool = True
                 ) -> tuple[list[dict], list[dict], list[dict]]:
    result = get_model().predict(
        frame,
        conf=0.25,
        imgsz=640,
        classes=[PERSON_CLASS, *VEHICLE_CLASSES],
        device="cpu",
        verbose=False,
    )[0]
    mask_polygons = result.masks.xy if result.masks is not None else None
    blockers, people, road_vehicles = [], [], []
    for idx, box in enumerate(result.boxes if result.boxes is not None else []):
        class_id = int(box.cls.item())
        x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].cpu().tolist()]
        foot_x = min(frame.shape[1] - 1, max(0, round((x1 + x2) / 2)))
        foot_y = min(frame.shape[0] - 1, max(0, y2 - 2))
        zone = ("footpath" if footpath[foot_y, foot_x]
                else "road" if road is not None and road[foot_y, foot_x] else "other")
        if class_id == PERSON_CLASS:
            people.append({"class": "person", "confidence": round(float(box.conf.item()), 3),
                           "box": [x1, y1, x2, y2], "footpoint": [foot_x, foot_y], "zone": zone})
            continue
        if class_id not in VEHICLE_CLASSES:
            continue
        mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        if mask_polygons is not None:
            outline = mask_polygons[idx].astype(np.int32)
            if len(outline) >= 3:
                cv2.fillPoly(mask, [outline], 1)
        if not mask.any():
            cv2.rectangle(mask, (x1, y1), (x2, y2), 1, -1)
        mask = mask.astype(bool)
        score, pixels = overlap_score(mask, footpath)
        item = {
            "class": VEHICLE_CLASSES[class_id],
            "confidence": round(float(box.conf.item()), 3),
            "footpath_overlap": round(score, 3),
            "box": [x1, y1, x2, y2],
            "footpoint": [foot_x, foot_y], "zone": zone,
        }
        if score >= min_overlap and pixels >= 35:
            if width_line:
                item["width_profile"] = width_line_profile(mask, footpath, width_line)
            blockers.append(item)
        elif zone == "road":
            road_vehicles.append(item)
    occupied_boxes = [item["box"] for item in blockers + people + road_vehicles]
    for item in goods_proposals(frame, occupied_boxes) if include_goods else []:
        x1, y1, x2, y2 = item["box"]
        mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        cv2.rectangle(mask, (x1, y1), (x2, y2), 1, -1)
        mask = mask.astype(bool)
        score, pixels = overlap_score(mask, footpath)
        if score < min_overlap or pixels < 35:
            continue
        foot_x = min(frame.shape[1]-1, max(0, round((x1+x2)/2)))
        foot_y = min(frame.shape[0]-1, max(0, y2-2))
        item.update(footpath_overlap=round(score, 3), footpoint=[foot_x, foot_y], zone="footpath")
        if width_line:
            item["width_profile"] = width_line_profile(mask, footpath, width_line)
        blockers.append(item)
    return blockers, people, road_vehicles


def detect(frame: np.ndarray, footpath: np.ndarray, min_overlap: float) -> list[dict]:
    """Compatibility helper for the original obstruction-only workflow."""
    return detect_scene(frame, footpath, None, min_overlap)[0]


def draw_frame(
    frame: np.ndarray, points: list[list[float]], detections: list[dict], seconds: float,
    road_points: list[list[float]] | None = None, people: list[dict] | None = None,
    speed_gates: dict | None = None, crowd_size: int = 0,
    width_line: list[list[float]] | None = None,
    flow_line: list[list[float]] | None = None,
) -> np.ndarray:
    out = frame.copy()
    h, w = out.shape[:2]
    vertices = np.array(
        [[round(p[0] * (w - 1)), round(p[1] * (h - 1))] for p in points],
        dtype=np.int32,
    )
    tint = out.copy()
    cv2.fillPoly(tint, [vertices], (80, 190, 235))
    cv2.addWeighted(tint, 0.18, out, 0.82, 0, out)
    cv2.polylines(out, [vertices], True, (20, 180, 245), 3, cv2.LINE_AA)
    if road_points:
        road_vertices = np.array(
            [[round(p[0] * (w - 1)), round(p[1] * (h - 1))] for p in road_points],
            dtype=np.int32,
        )
        cv2.polylines(out, [road_vertices], True, (235, 150, 35), 3, cv2.LINE_AA)
    if speed_gates:
        for name, color in (("a", (200, 220, 30)), ("b", (220, 60, 200))):
            pair = speed_gates[name]
            a, b = [tuple(round(value * (w - 1 if index == 0 else h - 1))
                          for index, value in enumerate(point)) for point in pair]
            cv2.line(out, a, b, color, 3, cv2.LINE_AA)
            cv2.putText(out, name.upper(), a, cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                        (255, 255, 255), 3, cv2.LINE_AA)
    for line_points, label, color in ((width_line, "WIDTH", (60, 220, 240)),
                                      (flow_line, "FLOW", (105, 240, 90))):
        if line_points:
            a, b = [tuple(round(value * (w - 1 if index == 0 else h - 1))
                          for index, value in enumerate(point)) for point in line_points]
            cv2.line(out, a, b, color, 3, cv2.LINE_AA)
            cv2.putText(out, label, a, cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (255, 255, 255), 2, cv2.LINE_AA)
    for item in people or []:
        x1, y1, x2, y2 = item["box"]
        color = (30, 65, 230) if item["zone"] == "road" else (50, 180, 45)
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        cv2.putText(out, "PERSON DETECTION: " + item["zone"].upper(), (max(4, x1), max(24, y1 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 2, cv2.LINE_AA)
    for item in detections:
        x1, y1, x2, y2 = item["box"]
        cv2.rectangle(out, (x1, y1), (x2, y2), (28, 42, 230), 3)
        label = f"POSSIBLE BLOCKAGE: {item['class']} {item['confidence']:.0%}"
        baseline_y = max(28, y1 - 7)
        cv2.putText(out, label, (max(4, x1), baseline_y), cv2.FONT_HERSHEY_SIMPLEX,
                    0.62, (255, 255, 255), 4, cv2.LINE_AA)
        cv2.putText(out, label, (max(4, x1), baseline_y), cv2.FONT_HERSHEY_SIMPLEX,
                    0.62, (20, 20, 160), 2, cv2.LINE_AA)
    if detections and any(item["zone"] == "road" for item in people or []):
        status = "BLOCKAGE + ROAD PERSON CUE: REVIEW"
    else:
        status = "REVIEW POSSIBLE BLOCKAGE" if detections else "NO VEHICLE BLOCKAGE DETECTED"
    cv2.rectangle(out, (0, h - 42), (w, h), (20, 29, 26), -1)
    cv2.putText(out, f"{seconds:05.1f}s  {status}", (14, h - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.67, (255, 255, 255), 2, cv2.LINE_AA)
    if crowd_size >= 3:
        cv2.putText(out, f"POSSIBLE CROWD: {crowd_size} NEARBY PEOPLE", (14, 31),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (20, 20, 20), 4, cv2.LINE_AA)
        cv2.putText(out, f"POSSIBLE CROWD: {crowd_size} NEARBY PEOPLE", (14, 31),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)
    return out


def _same_event(event: dict, detection: dict, seconds: float, width: int) -> bool:
    if event["class"] != detection["class"] or seconds - event["end_seconds"] > 2.0:
        return False
    old = event["last_box"]
    new = detection["box"]
    old_cx = (old[0] + old[2]) / 2
    new_cx = (new[0] + new[2]) / 2
    return abs(old_cx - new_cx) < width * 0.18


def analyze(
    source: Path,
    job_dir: Path,
    points: list[list[float]],
    min_overlap: float,
    progress: Callable[[int, int], None] | None = None,
    scene_config: dict | None = None,
) -> dict:
    scene_config = scene_config or {}
    first, meta = read_first_frame(source)
    height, width = first.shape[:2]
    footpath = polygon_mask(points, width, height).astype(bool)
    road_points = scene_config.get("road_polygon") or []
    road = polygon_mask(road_points, width, height).astype(bool) if road_points else None
    width_line = scene_config.get("width_line")
    flow_line = scene_config.get("flow_line")
    speed_gates = scene_config.get("speed_gates")
    speed_tracker = SpeedGateTracker(width, height, speed_gates) if speed_gates else None
    movement_tracker = PersonMovementTracker(width) if road is not None else None
    flow_counter = FootpathFlowCounter(width, height, flow_line) if flow_line else None
    model = get_model()
    _ = model  # Load once before opening/writing the clip.
    if not 0.02 <= min_overlap <= 0.8:
        raise ValueError("Overlap threshold must be between 2% and 80%.")

    if meta["kind"] == "video":
        cap = cv2.VideoCapture(str(source))
        stride = max(1, round(meta["fps"] / (4.0 if speed_gates else SAMPLE_FPS)))
        output_fps = meta["fps"] / stride
        total_samples = math.ceil(meta["frame_count"] / stride)
        raw_video = job_dir / "annotated-raw.mp4"
        writer = cv2.VideoWriter(
            str(raw_video), cv2.VideoWriter_fourcc(*"mp4v"), output_fps, (width, height)
        )
        if not writer.isOpened():
            cap.release()
            raise RuntimeError("Could not create the annotated video.")
    else:
        cap, writer, stride, total_samples = None, None, 1, 1

    events: list[dict] = []
    width_fraction_samples: list[float] = []
    clear_samples: list[dict] = []
    movement_events: list[dict] = []
    crowd_snapshot = road_person_snapshot = None
    max_people_in_frame = max_crowd_size = crowd_frames = road_person_frames = road_person_blockage_frames = 0
    sample_count = flagged_count = 0
    frame_number = 0
    try:
        while True:
            if cap is None:
                frame = first if frame_number == 0 else None
                ok = frame is not None
            else:
                ok, frame = cap.read()
            if not ok or frame is None:
                break
            if frame_number % stride:
                frame_number += 1
                continue
            if cap is not None:
                frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
            seconds = frame_number / meta["fps"] if cap is not None else 0.0
            found, people, road_vehicles = detect_scene(frame, footpath, road, min_overlap, width_line)
            if found and width_line:
                profiles = [item.get("width_profile", []) for item in found]
                if profiles:
                    combined = np.any(np.asarray(profiles, dtype=bool), axis=0)
                    fraction = float(combined.mean())
                    if fraction > 0:
                        width_fraction_samples.append(fraction)
            if flow_counter is not None:
                flow_counter.update(people, seconds)
            max_people_in_frame = max(max_people_in_frame, len(people))
            crowd_size = largest_person_group(people, width, height)
            max_crowd_size = max(max_crowd_size, crowd_size)
            if crowd_size >= 3:
                crowd_frames += 1
            has_road_person = any(item["zone"] == "road" for item in people)
            road_person_frames += int(has_road_person)
            road_person_blockage_frames += int(has_road_person and bool(found))
            if speed_tracker is not None:
                speed_tracker.update(road_vehicles, seconds)
            new_movements = movement_tracker.update(people, seconds, bool(found)) if movement_tracker else []
            annotated = draw_frame(frame, points, found, seconds, road_points, people,
                                   speed_gates, crowd_size, width_line, flow_line)
            if crowd_snapshot is None and crowd_size >= 3:
                crowd_snapshot = "crowd-01.jpg"
                cv2.imwrite(str(job_dir / crowd_snapshot), annotated)
            if road_person_snapshot is None and has_road_person and found:
                road_person_snapshot = "road-person-01.jpg"
                cv2.imwrite(str(job_dir / road_person_snapshot), annotated)
            for movement in new_movements:
                name = f"move-{len(movement_events) + 1:03d}.jpg"
                cv2.imwrite(str(job_dir / name), annotated)
                movement_events.append({"seconds": movement["seconds"], "snapshot": name})
            if writer is not None:
                writer.write(annotated)
            sample_count += 1
            if found:
                flagged_count += 1
                for item in found:
                    event = next(
                        (e for e in reversed(events) if _same_event(e, item, seconds, width)),
                        None,
                    )
                    if event is None:
                        event_id = len(events) + 1
                        name = f"flag-{event_id:03d}.jpg"
                        cv2.imwrite(str(job_dir / name), annotated)
                        events.append({
                            "id": event_id,
                            "class": item["class"],
                            "start_seconds": round(seconds, 2),
                            "end_seconds": round(seconds, 2),
                            "peak_confidence": item["confidence"],
                            "peak_overlap": item["footpath_overlap"],
                            "snapshot": name,
                            "last_box": item["box"],
                            "frames_seen": 1,
                        })
                    else:
                        event["end_seconds"] = round(seconds, 2)
                        event["last_box"] = item["box"]
                        event["frames_seen"] += 1
                        event["peak_confidence"] = max(event["peak_confidence"], item["confidence"])
                        if item["footpath_overlap"] > event["peak_overlap"]:
                            event["peak_overlap"] = item["footpath_overlap"]
                            cv2.imwrite(str(job_dir / event["snapshot"]), annotated)
            elif len(clear_samples) < 6 and (sample_count == 1 or sample_count % 8 == 0):
                name = f"no-flag-{len(clear_samples) + 1:02d}.jpg"
                cv2.imwrite(str(job_dir / name), annotated)
                clear_samples.append({"seconds": round(seconds, 2), "snapshot": name})
            if progress:
                progress(sample_count, total_samples)
            frame_number += 1
    finally:
        if cap is not None:
            cap.release()
        if writer is not None:
            writer.release()

    annotated_video = None
    if meta["kind"] == "video":
        annotated_video = "annotated.mp4"
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run(
            [ffmpeg, "-loglevel", "error", "-y", "-i", str(raw_video),
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
             str(job_dir / annotated_video)],
            check=True,
            capture_output=True,
            text=True,
        )
        raw_video.unlink(missing_ok=True)

    for event in events:
        event.pop("last_box")
    measured_speeds = speed_tracker.samples if speed_tracker else []
    if len(measured_speeds) >= 3:
        speed_kmh = round(sum(measured_speeds) / len(measured_speeds), 1)
        speed_source = "experimental calibrated video gates"
    else:
        speed_kmh = scene_config.get("traffic_speed_kmh")
        speed_source = scene_config.get("speed_source") if speed_kmh is not None else None
    footpath_width_m = scene_config.get("footpath_width_m")
    video_width_lost_m = (round(footpath_width_m * statistics.median(width_fraction_samples), 2)
                          if footpath_width_m is not None and width_fraction_samples else None)
    manual_width_lost_m = scene_config.get("width_lost_m")
    width_lost_m = manual_width_lost_m if manual_width_lost_m is not None else video_width_lost_m
    width_lost_source = (scene_config.get("width_lost_source") if manual_width_lost_m is not None
                         else "experimental video cross-section" if video_width_lost_m is not None else None)
    flow_count = flow_counter.count if flow_counter is not None else None
    clip_flow_rate = (round(flow_count * 3600 / meta["duration_seconds"], 1)
                      if flow_count is not None and meta["duration_seconds"] >= 15
                      and flow_count >= 3 else None)
    manual_flow = scene_config.get("peak_flow_per_hour")
    use_clip_flow = bool(scene_config.get("use_clip_flow_for_demo")) and manual_flow is None
    flow_per_hour = clip_flow_rate if use_clip_flow else manual_flow
    flow_source = ("short-clip extrapolation (synthetic/demo only)" if use_clip_flow and clip_flow_rate is not None
                   else scene_config.get("flow_source") if manual_flow is not None else None)
    exposure = exposure_estimate(flow_per_hour, footpath_width_m, width_lost_m, speed_kmh)
    report = {
        "site_name": scene_config.get("site_name") or "Unnamed site",
        "synthetic": any(source == "synthetic demo value" for source in
                         (scene_config.get("footpath_width_source"), width_lost_source,
                          flow_source, speed_source)),
        "source_type": meta["kind"],
        "duration_seconds": meta["duration_seconds"],
        "sampled_frames": sample_count,
        "flagged_frames": flagged_count,
        "possible_obstructions": len(events),
        "footpath_polygon": points,
        "road_polygon": road_points,
        "width_line": width_line,
        "flow_line": flow_line,
        "overlap_threshold": min_overlap,
        "model": MODEL_PATH.name,
        "annotated_video": annotated_video,
        "events": events,
        "people": {
            "max_in_frame": max_people_in_frame,
            "max_nearby_group": max_crowd_size,
            "crowd_frames": crowd_frames,
            "crowd_snapshot": crowd_snapshot,
            "road_person_frames": road_person_frames,
            "road_person_with_blockage_frames": road_person_blockage_frames,
            "road_person_snapshot": road_person_snapshot,
            "possible_path_to_road_moves": movement_events,
        },
        "traffic_speed": {
            "kmh": speed_kmh,
            "source": speed_source,
            "video_vehicle_samples_kmh": measured_speeds,
            "video_gate_status": (f"{len(measured_speeds)} valid vehicle passes; at least 3 needed for a clip average"
                                  if speed_gates and len(measured_speeds) < 3 else None),
            "calibrated_gate_distance_m": speed_gates["distance_m"] if speed_gates else None,
        },
        "pedestrian_flow": {
            "observed_line_crossings": flow_count,
            "clip_hourly_equivalent": clip_flow_rate,
            "clip_duration_seconds": meta["duration_seconds"],
            "note": "Short-clip rate is not a measured peak-hour flow and tracks may be missed or double-counted.",
        },
        "site_inputs": {
            "footpath_width_m": footpath_width_m,
            "footpath_width_source": scene_config.get("footpath_width_source") if footpath_width_m is not None else None,
            "width_lost_m": width_lost_m,
            "width_lost_source": width_lost_source,
            "video_width_lost_m": video_width_lost_m,
            "width_estimate_samples": len(width_fraction_samples),
            "peak_flow_per_hour": flow_per_hour,
            "flow_source": flow_source,
        },
        "exposure": exposure,
        "no_flag_samples": clear_samples,
        "limits": [
            "Flags are possible obstructions, not verified blocked footpaths.",
            "The generic model recognizes vehicles and bicycles, not stalls or all local obstructions.",
            "A person in the road during a blockage does not prove the blockage caused the movement.",
            "Short visual tracks and two-frame-per-second sampling can miss or confuse movements.",
            "Video width loss is a provisional silhouette cross-section estimate calibrated by measured path width.",
            "Short clips do not establish peak pedestrian flow; extrapolation is for synthetic/demo use only.",
            "Video gate speed is experimental and needs a fixed calibrated camera and moving vehicles.",
            "The speed-weighted exposure index is not a predicted crash or death probability.",
            "The PDF's 0-100 site ranking needs comparable measurements from multiple sites.",
        ],
    }
    (job_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (job_dir / "reviews.json").write_text(
        json.dumps({"events": {}, "misses": []}, indent=2), encoding="utf-8"
    )
    with (job_dir / "events.csv").open("w", newline="", encoding="utf-8") as handle:
        writer_csv = csv.DictWriter(handle, fieldnames=[
            "id", "class", "start_seconds", "end_seconds", "peak_confidence",
            "peak_overlap", "snapshot", "frames_seen",
        ])
        writer_csv.writeheader()
        writer_csv.writerows(events)
    with zipfile.ZipFile(job_dir / "evidence.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ["report.json", "events.csv", *[e["snapshot"] for e in events],
                     *[e["snapshot"] for e in clear_samples],
                     *[e["snapshot"] for e in movement_events],
                     *[name for name in (crowd_snapshot, road_person_snapshot) if name]]:
            archive.write(job_dir / name, arcname=name)
    return report
