"""Semantic acceptance on complete source clips, including a clear control."""
from pathlib import Path
import argparse
import hashlib
import json
import sys
import time
import cv2
import requests

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / 'module3-demo' if (ROOT/'module3-demo').exists() else ROOT
BASE = APP/'examples/generated-scenarios'
parser = argparse.ArgumentParser()
parser.add_argument('--mode', choices=['local', 'public'], required=True)
parser.add_argument('--url', default='https://134.209.149.217/footpath-demo/')
parser.add_argument('--only', nargs='+', help='Validate selected slugs while retaining other runs for the same code')
parser.add_argument('--output', type=Path, default=ROOT/'artifacts/VALIDATION.json', help='Ignored run evidence; historical acceptance stays in examples/')
args = parser.parse_args()
output = args.output
output.parent.mkdir(parents=True, exist_ok=True)
baseline = output if output.exists() else BASE/'VALIDATION.json'
results = json.loads(baseline.read_text()) if baseline.exists() else {}
results['scope'] = 'Generated-scenario workflow checks, not field accuracy statistics'
code = hashlib.sha256()
for name in ['quick_screen.py', 'analyzer.py', 'obstructions.py', 'pedestrian_tracks.py']:
    code.update((APP/name).read_bytes())
if not args.only or results.get(args.mode, {}).get('analysis_code_sha256') != code.hexdigest():
    results[args.mode] = {'analysis_code_sha256': code.hexdigest(), 'runs': []}
cases = [('01-parked-car', BASE/'01-parked-car.mp4', 2),
         ('02-shop-goods', BASE/'02-shop-goods.mp4', 1),
         ('03-motorbike', BASE/'03-motorbike.mp4', 1),
         ('04-bicycles', BASE/'04-bicycles.mp4', 1),
         ('clear-control', APP/'examples/real-scenarios/02-real-clear-path.mp4', 0)]
if args.only:
    if set(args.only) - {case[0] for case in cases}:
        parser.error('Unknown sample slug')
    cases = [case for case in cases if case[0] in args.only]
session = requests.Session()

def video_info(path):
    cap = cv2.VideoCapture(str(path))
    info = {'fps': round(cap.get(cv2.CAP_PROP_FPS), 3),
            'frames': int(cap.get(cv2.CAP_PROP_FRAME_COUNT))}
    cap.release()
    return info

if args.mode == 'local':
    sys.path.insert(0, str(APP))
    from quick_screen import quick_analyze

for slug, source, expected in cases:
    folder = ROOT/'artifacts/videos'/args.mode/slug
    folder.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    job_id = None
    if args.mode == 'local':
        report = quick_analyze(source, folder)
    else:
        # The clear clip intentionally borrows the car's filename. Content,
        # rather than a filename or sample slug, must determine the result.
        filename = '01-parked-car.mp4' if slug == 'clear-control' else 'renamed-'+slug+'.mp4'
        with source.open('rb') as handle:
            response = session.post(args.url+'api/upload', files={'file': (filename, handle, 'video/mp4')}, timeout=120)
        response.raise_for_status()
        job_id = response.json()['job_id']
        response = session.post(args.url+'api/quick/'+job_id, timeout=30)
        response.raise_for_status()
        deadline = time.monotonic()+600
        while time.monotonic() < deadline:
            response = session.get(args.url+'api/status/'+job_id, timeout=30)
            response.raise_for_status()
            state = response.json()
            if state['status'] == 'done':
                report = state['report']
                break
            if state['status'] == 'error':
                raise RuntimeError(state.get('message', 'Analysis failed'))
            time.sleep(1.2)
        else:
            raise RuntimeError('Analysis timeout: '+slug)
        media = session.get(args.url+f'media/{job_id}/annotated.mp4', timeout=120)
        media.raise_for_status()
        (folder/'annotated.mp4').write_bytes(media.content)
        (folder/'report.json').write_text(json.dumps(report, indent=2))
    entry = {'slug': slug, 'job_id': job_id, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
             'score': report['score'], 'exits': report['path_to_road_crossings'],
             'near_obstruction': report['crossings_with_blockage_nearby'],
             'returns': report['returned_to_path_count'], 'road_person_seconds': report['road_person_seconds'],
             'obstruction_frames': report['blocker_frames'], 'seconds_to_analyze': round(time.monotonic()-started, 1),
             'source_video': video_info(source), 'marked_video': video_info(folder/'annotated.mp4'),
             'events': report['movement_events']}
    results[args.mode]['runs'] = [run for run in results[args.mode]['runs'] if run['slug'] != slug] + [entry]
    output.write_text(json.dumps(results, indent=2))
    print(args.mode, slug, 'score', entry['score'], 'exits', entry['exits'],
          'returns', entry['returns'], 'blocker frames', entry['obstruction_frames'], flush=True)
    assert entry['exits'] == expected, f'Unexpected exit count: {slug}'
    assert entry['returns'] == expected, f'Incomplete return tracking: {slug}'
    assert entry['source_video'] == entry['marked_video'], f'Frame rate or frame count changed: {slug}'
    if expected:
        assert entry['near_obstruction'] == expected, f'Obstruction association missing: {slug}'
        assert entry['obstruction_frames'] > 0, f'Obstruction not detected: {slug}'
    else:
        assert entry['obstruction_frames'] == 0 and entry['road_person_seconds'] == 0, 'False alarm on control'
print('PASS', args.mode, len(cases), 'complete video checks', flush=True)
