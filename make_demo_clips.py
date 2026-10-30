"""Create ten reproducible, synthetic fixed-camera test clips from source footage."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXAMPLES = ROOT / 'examples'
SCENARIOS = [
    ('01-clear-walk', 'Clear walk', 'No marked path-to-road crossing', 'demo-lower-concern.mp4', 0, 10),
    ('02-blocked-stay', 'Blocked but staying on path', 'Car on path, no tracked exit', 'indian-footpath-blocked-with-pedestrians.mp4', 0, 12),
    ('03-first-exit', 'First path exit', 'One tracked crossing near the car', 'demo-higher-concern.mp4', 0, 8),
    ('04-later-exit', 'Later path exit', 'Another view of a crossing moment', 'demo-higher-concern.mp4', 7, 8),
    ('05-two-exits', 'Two exits', 'Two path-to-road moments in one clip', 'demo-higher-concern.mp4', 0, 14),
    ('06-three-exits', 'Three exits', 'Repeated crossing moments', 'demo-higher-concern.mp4', 0, 20),
    ('07-arriving-car', 'Car arrives', 'The path becomes occupied', 'indian-footpath-clear-to-blocked.mp4', 0, 11),
    ('08-long-walk-exit', 'Long walk to road', 'A walker crosses after several seconds', 'indian-footpath-continuous-motion.mp4', 17.5, 6),
    ('09-repeated-diversion', 'Repeated movement', 'Multiple crossing moments', 'indian-footpath-continuous-motion.mp4', 10, 16),
    ('10-full-scene', 'Full street sequence', 'Clear opening followed by repeated exits', 'indian-footpath-continuous-motion.mp4', 0, 29.5),
]


def main():
    folder = EXAMPLES / 'ten-scenarios'
    folder.mkdir(exist_ok=True)
    manifest = []
    for slug, title, description, source, start, duration in SCENARIOS:
        target = folder / f'{slug}.mp4'
        subprocess.run([
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
            '-ss', str(start), '-t', str(duration), '-i', str(EXAMPLES / source),
            '-vf', 'fps=12,scale=960:540:flags=lanczos', '-an',
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '27',
            '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(target),
        ], check=True)
        manifest.append({'slug': slug, 'title': title, 'description': description,
                         'source': source, 'start_seconds': start,
                         'duration_seconds': duration})
        print(target.name, target.stat().st_size)
    featured = ['05-two-exits', '01-clear-walk']
    manifest.sort(key=lambda item: (featured.index(item['slug']) if item['slug'] in featured
                                    else len(featured) + next(i for i, row in enumerate(SCENARIOS)
                                                            if row[0] == item['slug'])))
    (folder / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
