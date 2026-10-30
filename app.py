"""Local-only browser UI for reviewing footpath obstruction detections."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from urllib.parse import urlencode

import cv2
from flask import Flask, jsonify, redirect, render_template, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge

from analyzer import analyze, polygon_mask, read_first_frame
from quick_screen import quick_analyze
from scene_signals import exposure_estimate
from site_table import rank_sites


ROOT = Path(__file__).resolve().parent
SCENARIO_DIR = ROOT / 'examples' / 'real-scenarios'
generated_dir = ROOT / 'examples' / 'generated-scenarios'
if (generated_dir / 'manifest.json').exists():
    generated_items = json.loads((generated_dir / 'manifest.json').read_text())
    if generated_items and all((generated_dir / (item['slug'] + '.mp4')).is_file() for item in generated_items):
        SCENARIO_DIR = generated_dir
SCENARIOS = json.loads((SCENARIO_DIR / 'manifest.json').read_text()) if (SCENARIO_DIR / 'manifest.json').exists() else []
HOSTED_DEMO = os.environ.get("HOSTED_DEMO", "0") == "1"
MAX_UPLOAD_MB = 25 if HOSTED_DEMO else 250
MAX_VIDEO_SECONDS = 30 if HOSTED_DEMO else 120
JOB_TTL_HOURS = 24
JOBS = Path(os.environ.get("DEMO_JOBS_DIR", str(ROOT / "jobs")))
JOBS.mkdir(exist_ok=True)
ALLOWED = {".mp4", ".mov", ".avi", ".mkv", ".jpg", ".jpeg", ".png"}
ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
MEDIA_PATTERN = re.compile(r"^(?:first\.jpg|annotated\.mp4|report\.json|reviews\.json|events\.csv|evidence\.zip|flag-[0-9]{3}\.jpg|no-flag-[0-9]{2}\.jpg|move-[0-9]{3}\.jpg|crowd-01\.jpg|road-person-01\.jpg|screen-[0-9]{2}\.jpg)$")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
pool = ThreadPoolExecutor(max_workers=1)
states: dict[str, dict] = {}
cleanup_lock = Lock()
last_cleanup = 0.0


@app.before_request
def expire_hosted_jobs() -> None:
    """Keep uploaded footage on the hosted demo for at most one day."""
    global last_cleanup
    if not HOSTED_DEMO or time.time() - last_cleanup < 300:
        return
    if not cleanup_lock.acquire(blocking=False):
        return
    try:
        now = time.time()
        if now - last_cleanup < 300:
            return
        for folder in JOBS.iterdir():
            if not folder.is_dir() or not ID_PATTERN.fullmatch(folder.name):
                continue
            if states.get(folder.name, {}).get("status") in {"queued", "running"}:
                continue
            if now - folder.stat().st_mtime >= JOB_TTL_HOURS * 3600:
                shutil.rmtree(folder)
                states.pop(folder.name, None)
        last_cleanup = now
    finally:
        cleanup_lock.release()


def job_path(job_id: str) -> Path:
    if not ID_PATTERN.fullmatch(job_id):
        raise ValueError("Invalid job ID.")
    path = JOBS / job_id
    if not path.is_dir():
        raise FileNotFoundError("Job not found.")
    return path


def source_path(path: Path) -> Path:
    files = list(path.glob("source.*"))
    if len(files) != 1:
        raise FileNotFoundError("Uploaded source not found.")
    return files[0]


def fail(message: str, code: int = 400):
    return jsonify({"error": message}), code


@app.errorhandler(RequestEntityTooLarge)
def too_large(_error):
    return fail(f"Use a file smaller than {MAX_UPLOAD_MB} MB.", 413)


@app.get("/")
def home():
    if request.args.get("sites"):
        return redirect("proposal?" + urlencode({"sites": request.args["sites"]}))
    return render_template("quick.html", hosted=HOSTED_DEMO,
                           scenarios=SCENARIOS,
                           max_upload_mb=MAX_UPLOAD_MB,
                           max_video_seconds=MAX_VIDEO_SECONDS,
                           job_ttl_hours=JOB_TTL_HOURS)


@app.get("/details")
def details_page():
    return render_template("details.html", hosted=HOSTED_DEMO)


@app.get("/proposal")
def proposal_page():
    return send_from_directory(ROOT / "templates", "proposal.html")


def detector_page(embedded: bool):
    space_id = os.environ.get("SPACE_ID", "")
    source_url = f"https://huggingface.co/spaces/{space_id}" if space_id else "source.zip" if HOSTED_DEMO else None
    return render_template("index.html", hosted=HOSTED_DEMO, max_upload_mb=MAX_UPLOAD_MB,
                           max_video_seconds=MAX_VIDEO_SECONDS, job_ttl_hours=JOB_TTL_HOURS,
                           source_url=source_url, embedded=embedded)


@app.get("/analyze")
def analyzer_ui():
    return detector_page(embedded=request.args.get("embedded") == "1")


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.get("/sample.mp4")
def sample_video():
    return send_from_directory(ROOT / "examples", "indian-footpath-clear-to-blocked.mp4")


@app.get("/sample-pedestrians.mp4")
def sample_pedestrians_video():
    return send_from_directory(ROOT / "examples", "indian-footpath-blocked-with-pedestrians.mp4")


@app.get("/sample-moving.mp4")
def sample_moving_video():
    return send_from_directory(ROOT / "examples", "indian-footpath-continuous-motion.mp4")


@app.get("/sample-higher.mp4")
def sample_higher_video():
    return send_from_directory(ROOT / "examples", "demo-higher-concern.mp4")


@app.get("/sample-lower.mp4")
def sample_lower_video():
    return send_from_directory(ROOT / "examples", "demo-lower-concern.mp4")


@app.get('/samples/<slug>.mp4')
def scenario_video(slug: str):
    if slug not in {item['slug'] for item in SCENARIOS}:
        return fail('Sample not found.', 404)
    return send_from_directory(SCENARIO_DIR, slug + '.mp4')


@app.get('/samples/<slug>.jpg')
def scenario_poster(slug: str):
    if slug not in {item['slug'] for item in SCENARIOS}:
        return fail('Sample not found.', 404)
    return send_from_directory(SCENARIO_DIR, slug + '.jpg')


@app.get("/source.zip")
def source_archive():
    archive = ROOT / "source.zip"
    if not archive.is_file():
        archive = ROOT / "dist" / "source.zip"
    if not HOSTED_DEMO or not archive.is_file():
        return fail("Source archive unavailable.", 404)
    return send_from_directory(archive.parent, archive.name, as_attachment=True)


@app.post("/api/upload")
def upload():
    incoming = request.files.get("file")
    if incoming is None or not incoming.filename:
        return fail("Choose a video or photo.")
    suffix = Path(incoming.filename).suffix.lower()
    if suffix not in ALLOWED:
        return fail("Use MP4, MOV, AVI, MKV, JPG, or PNG.")
    if HOSTED_DEMO and sum(1 for path in JOBS.iterdir() if path.is_dir()) >= 100:
        return fail("The demo is at capacity. Please try again after older jobs expire.", 429)
    job_id = uuid.uuid4().hex
    folder = JOBS / job_id
    folder.mkdir()
    source = folder / f"source{suffix}"
    incoming.save(source)
    try:
        frame, meta = read_first_frame(source)
        if meta["duration_seconds"] > MAX_VIDEO_SECONDS:
            raise ValueError(f"Use a clip no longer than {MAX_VIDEO_SECONDS} seconds.")
        cv2.imwrite(str(folder / "first.jpg"), frame)
    except (ValueError, RuntimeError) as exc:
        source.unlink(missing_ok=True)
        folder.rmdir()
        return fail(str(exc))
    (folder / "source-meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return jsonify({"job_id": job_id, "preview": f"media/{job_id}/first.jpg", **meta})


def run_job(job_id: str, points: list[list[float]], min_overlap: float,
            scene_config: dict) -> None:
    state = states[job_id]
    try:
        folder = job_path(job_id)
        state.update(status="running", message="Loading local model and reading frames")

        def on_progress(done: int, total: int):
            state.update(
                status="running",
                done=done,
                total=total,
                message=f"Analyzed {done} of about {total} sampled frames",
            )

        analyze(source_path(folder), folder, points, min_overlap, on_progress, scene_config)
        state.update(status="done", message="Analysis complete")
    except Exception as exc:
        state.update(status="error", message=str(exc))


def run_quick_job(job_id: str) -> None:
    state = states[job_id]
    try:
        folder = job_path(job_id)
        state.update(status="running", message="Detecting people and nearby vehicles")

        def on_progress(done: int, total: int):
            state.update(status="running", done=done, total=total,
                         message=f"Analyzed {done} of about {total} sampled frames")

        quick_analyze(source_path(folder), folder, on_progress)
        state.update(status="done", message="Analysis complete")
    except Exception as exc:
        state.update(status="error", message=str(exc))


def optional_number(body: dict, name: str, low: float, high: float) -> float | None:
    value = body.get(name)
    if value in (None, ""):
        return None
    value = float(value)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name.replace('_', ' ').capitalize()} must be between {low} and {high}.")
    return value


def optional_line(body: dict, name: str, meta: dict) -> list[list[float]] | None:
    line = body.get(name) or None
    if line is None:
        return None
    if (meta["kind"] != "video" or not isinstance(line, list) or len(line) != 2
            or any(not isinstance(point, list) or len(point) != 2 or any(
                not isinstance(value, (int, float)) or isinstance(value, bool)
                or not math.isfinite(value) or not 0 <= value <= 1 for value in point
            ) for point in line) or math.dist(line[0], line[1]) < 0.03):
        raise ValueError(f"{name.replace('_', ' ').capitalize()} needs two distinct points on a video.")
    return line


def optional_source(body: dict, name: str, allowed: set[str]) -> str | None:
    value = body.get(name) or None
    if value is not None and value not in allowed:
        raise ValueError(f"Choose a valid {name.replace('_', ' ')}.")
    return value


def scene_config_from_body(body: dict, meta: dict) -> dict:
    road_polygon = body.get("road_polygon") or []
    if road_polygon:
        polygon_mask(road_polygon, meta["width"], meta["height"])
    gates = body.get("speed_gates") or None
    if gates:
        if meta["kind"] != "video" or not road_polygon:
            raise ValueError("Video speed gates need a video and a marked roadway.")
        if not isinstance(gates, dict) or set(gates) != {"a", "b", "distance_m"}:
            raise ValueError("Mark both speed gates and enter their real distance.")
        for name in ("a", "b"):
            pair = gates[name]
            if (not isinstance(pair, list) or len(pair) != 2 or any(
                not isinstance(point, list) or len(point) != 2 or any(
                    not isinstance(value, (int, float)) or not math.isfinite(value)
                    or value < 0 or value > 1 for value in point) for point in pair
            )):
                raise ValueError("Each speed gate needs two points on the image.")
            if math.dist(pair[0], pair[1]) < 0.03:
                raise ValueError("Speed gate lines are too short.")
        gates = {"a": gates["a"], "b": gates["b"],
                 "distance_m": float(gates["distance_m"])}
        if not math.isfinite(gates["distance_m"]) or not 1 <= gates["distance_m"] <= 100:
            raise ValueError("Gate distance must be 1 to 100 metres.")
    width = optional_number(body, "footpath_width_m", 0.5, 20)
    width_line = optional_line(body, "width_line", meta)
    flow_line = optional_line(body, "flow_line", meta)
    if width_line and width is None:
        raise ValueError("Enter measured footpath width to estimate blocked metres from the video.")
    lost = optional_number(body, "width_lost_m", 0, 20)
    if lost is not None and (width is None or lost > width):
        raise ValueError("Enter footpath width first; width lost cannot exceed it.")
    speed = optional_number(body, "traffic_speed_kmh", 5, 120)
    speed_source = body.get("speed_source") if speed is not None else None
    if speed_source not in (None, "measured survey or radar", "planning assumption", "synthetic demo value"):
        raise ValueError("Choose a speed source.")
    if speed is not None and speed_source is None:
        raise ValueError("Choose whether the speed is measured or assumed.")
    site_name = str(body.get("site_name") or "").strip()
    if not site_name or len(site_name) > 80:
        raise ValueError("Enter a site name of up to 80 characters.")
    manual_flow = optional_number(body, "peak_flow_per_hour", 0, 100000)
    use_clip_flow = body.get("use_clip_flow_for_demo", False)
    if not isinstance(use_clip_flow, bool):
        raise ValueError("Invalid clip flow option.")
    if use_clip_flow and not flow_line:
        raise ValueError("Mark a pedestrian count line before using a clip-derived flow rate.")
    width_source = optional_source(body, "footpath_width_source", {"site measurement", "synthetic demo value"})
    lost_source = optional_source(body, "width_lost_source", {"site measurement", "synthetic demo value"})
    flow_source = optional_source(body, "flow_source", {"peak-hour manual count", "synthetic demo value"})
    if width is not None and width_source is None:
        raise ValueError("Choose the source of the footpath width.")
    if lost is not None and lost_source is None:
        raise ValueError("Choose the source of the blocked width.")
    if manual_flow is not None and flow_source is None:
        raise ValueError("Choose the source of peak pedestrian flow.")
    return {
        "site_name": site_name,
        "road_polygon": road_polygon,
        "width_line": width_line,
        "flow_line": flow_line,
        "speed_gates": gates,
        "footpath_width_m": width,
        "footpath_width_source": width_source,
        "width_lost_m": lost,
        "width_lost_source": lost_source,
        "peak_flow_per_hour": manual_flow,
        "flow_source": flow_source,
        "use_clip_flow_for_demo": use_clip_flow,
        "traffic_speed_kmh": speed,
        "speed_source": speed_source,
    }


@app.post("/api/sites")
def sites():
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return fail("Send site IDs as a JSON object.")
    ids = body.get("job_ids")
    if not isinstance(ids, list) or len(ids) > 20 or any(
        not isinstance(job_id, str) or not ID_PATTERN.fullmatch(job_id) for job_id in ids
    ):
        return fail("Provide up to 20 valid analysis job IDs.")
    reports, missing = [], []
    for job_id in dict.fromkeys(ids):
        try:
            path = job_path(job_id) / "report.json"
            report = json.loads(path.read_text(encoding="utf-8"))
            report["job_id"] = job_id
            reports.append(report)
        except (FileNotFoundError, json.JSONDecodeError):
            missing.append(job_id)
    return jsonify({"rows": rank_sites(reports), "missing": missing,
                    "scope": "Only the selected jobs; scores are relative to the highest in this set."})


@app.get("/api/demo-sites")
def demo_sites():
    examples = [
        ("Synthetic example: Market Road", 2.0, 1.2, 900, 42),
        ("Synthetic example: School Gate", 2.4, 0.6, 1400, 28),
        ("Synthetic example: Bus Stand", 1.8, 0.9, 700, 35),
    ]
    reports = []
    for name, width, lost, flow, speed in examples:
        reports.append({
            "site_name": name, "synthetic": True,
            "site_inputs": {"footpath_width_m": width, "width_lost_m": lost,
                            "footpath_width_source": "synthetic demo value",
                            "width_lost_source": "synthetic demo value",
                            "peak_flow_per_hour": flow, "flow_source": "synthetic demo value"},
            "traffic_speed": {"kmh": speed, "source": "synthetic demo value"},
            "exposure": exposure_estimate(flow, width, lost, speed),
        })
    return jsonify({"rows": rank_sites(reports), "scope": "Synthetic formula example only; no video measurements."})


@app.post("/api/analyze/<job_id>")
def start_analysis(job_id: str):
    try:
        folder = job_path(job_id)
        body = request.get_json(force=True)
        if not isinstance(body, dict):
            raise ValueError("Send analysis settings as a JSON object.")
        points = body.get("polygon", [])
        min_overlap = float(body.get("min_overlap", 0.12))
        meta = json.loads((folder / "source-meta.json").read_text(encoding="utf-8"))
        polygon_mask(points, meta["width"], meta["height"])
        scene_config = scene_config_from_body(body, meta)
        if not 0.02 <= min_overlap <= 0.8:
            raise ValueError("Overlap threshold must be between 2% and 80%.")
    except FileNotFoundError as exc:
        return fail(str(exc), 404)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return fail(str(exc))
    if states.get(job_id, {}).get("status") in {"queued", "running"}:
        return fail("This clip is already being analyzed.", 409)
    if HOSTED_DEMO and (folder / "report.json").exists():
        return fail("This clip was already analyzed. Upload it again for a new run.", 409)
    if HOSTED_DEMO and sum(
        state.get("status") in {"queued", "running"} for state in states.values()
    ) >= 3:
        return fail("The demo is busy analyzing other clips. Please try again shortly.", 429)
    states[job_id] = {"status": "queued", "message": "Waiting for local detector", "done": 0, "total": 0}
    pool.submit(run_job, job_id, points, min_overlap, scene_config)
    return jsonify({"status": "queued"}), 202


@app.post("/api/quick/<job_id>")
def start_quick_analysis(job_id: str):
    try:
        folder = job_path(job_id)
    except (ValueError, FileNotFoundError):
        return fail("Job not found.", 404)
    if states.get(job_id, {}).get("status") in {"queued", "running"}:
        return fail("This clip is already being analyzed.", 409)
    if (folder / "report.json").exists():
        return fail("This clip was already analyzed. Upload it again for a new run.", 409)
    if HOSTED_DEMO and sum(
        state.get("status") in {"queued", "running"} for state in states.values()
    ) >= 3:
        return fail("The demo is busy analyzing other clips. Please try again shortly.", 429)
    states[job_id] = {"status": "queued", "message": "Waiting for local detector", "done": 0, "total": 0}
    pool.submit(run_quick_job, job_id)
    return jsonify({"status": "queued"}), 202


@app.get("/api/status/<job_id>")
def status(job_id: str):
    try:
        folder = job_path(job_id)
    except (ValueError, FileNotFoundError):
        return fail("Job not found.", 404)
    state = states.get(job_id)
    report_path = folder / "report.json"
    if report_path.exists() and (state is None or state.get("status") == "done"):
        report = json.loads(report_path.read_text(encoding="utf-8"))
        reviews_path = folder / "reviews.json"
        reviews = json.loads(reviews_path.read_text(encoding="utf-8")) if reviews_path.exists() else {"events": {}, "misses": []}
        return jsonify({"status": "done", "report": report, "reviews": reviews})
    return jsonify(state or {"status": "ready", "message": "Ready to analyze"})


def save_reviews(folder: Path, body: dict) -> dict:
    path = folder / "reviews.json"
    reviews = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"events": {}, "misses": []}
    if body.get("type") == "event":
        event_id = int(body["event_id"])
        verdict = body.get("verdict")
        report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
        if verdict not in {"correct", "false_alarm"} or event_id not in [e["id"] for e in report["events"]]:
            raise ValueError("Invalid review choice.")
        reviews["events"][str(event_id)] = verdict
    elif body.get("type") == "miss":
        seconds = float(body["seconds"])
        note = str(body.get("note", "")).strip()[:240]
        report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
        if not 0 <= seconds <= max(1, report["duration_seconds"]) or not note:
            raise ValueError("Enter a valid time and a short description.")
        reviews["misses"].append({"seconds": round(seconds, 2), "note": note})
    else:
        raise ValueError("Invalid review type.")
    path.write_text(json.dumps(reviews, indent=2), encoding="utf-8")
    return reviews


@app.post("/api/review/<job_id>")
def review(job_id: str):
    try:
        folder = job_path(job_id)
        if not (folder / "report.json").exists():
            return fail("Analyze the clip first.", 409)
        reviews = save_reviews(folder, request.get_json(force=True))
        return jsonify({"reviews": reviews})
    except FileNotFoundError:
        return fail("Job not found.", 404)
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        return fail(str(exc))


@app.get("/media/<job_id>/<path:filename>")
def media(job_id: str, filename: str):
    try:
        folder = job_path(job_id)
    except (ValueError, FileNotFoundError):
        return fail("Job not found.", 404)
    if not MEDIA_PATTERN.fullmatch(filename):
        return fail("This file is not available for download.", 403)
    return send_from_directory(folder, filename)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765, debug=False, threaded=True)
