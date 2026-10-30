"""Generate continuous, anchored LTX motion for the four obstruction examples."""
from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "module3-demo" if (ROOT / "module3-demo").exists() else ROOT
SCENES = APP / "examples/generated-scenarios"
PROMPTS = {
    "motorbike": "A fixed elevated camera observes an ordinary Indian street in daylight. A woman in a yellow kurta and white trousers walks away from the camera along the raised pavement. A stationary motorcycle is parked across the pavement ahead of her, leaving no walking room. She reaches it, turns naturally to her right, steps down off the curb into the asphalt road, walks around the motorcycle's front wheel, then turns left and steps back up onto the pavement beyond it and continues walking away. Her feet take alternating natural walking steps, arms swing gently, her body changes direction smoothly. The man in blue continues away along the pavement ahead. The motorcycle remains completely stationary. The camera and buildings remain absolutely locked in place. One continuous realistic documentary shot, no cut, no zoom, no text, no graphics. The reference frames show the start, midpoint in the road and return to the pavement.",
    "parked-car": "A locked elevated street camera films an Indian shopping street in daylight. A woman in a rust-red salwar kameez and cream trousers and a man following in a pale green shirt walk away from the camera along the raised pavement. A stationary silver car blocks the full width of the pavement. They approach it, turn to their right, step down from the curb into the road, walk around the car's nose, then turn back left and return up onto the pavement beyond the car. Both pedestrians walk with natural alternating footfalls and realistic body turns, keeping the same identities and clothes. The parked silver car and buildings remain completely stationary. Distant traffic moves naturally along the road. Fixed camera, one continuous documentary shot, no cuts, no zoom, no text or graphics. The reference frames show approach, road detour and return.",
    "shop-goods": "A locked elevated camera films an Indian shopfront and raised footpath beside a road in daylight. A woman in a teal kurta and beige trousers walks away from the camera on the footpath. A stationary display of crates, sacks and shop goods fills the footpath ahead. She approaches the obstruction, turns right, steps down over the curb into the asphalt road, walks around the display close to the road edge, then turns left and steps back onto the pavement beyond the goods. Her walking gait and turns are physically natural with alternating feet, gentle arm movement and no sliding. Her identity and clothes remain consistent. The shopkeeper stays in the doorway. The goods, buildings and camera stay completely stationary. One continuous realistic documentary shot, no cuts, no zoom, no text or graphics. Reference frames show approach, detour and return.",
    "bicycles": "A locked elevated camera films an ordinary Indian footpath beside a road in daylight. A man in a cream shirt, dark blue trousers and a backpack walks away from camera along the pavement. Two stationary parked bicycles block his walking route. He approaches the bicycles, turns right, steps down off the curb into the road, walks around their protruding wheels, then turns left and steps back onto the pavement past them and continues away. He takes natural alternating footsteps with realistic body turns and gentle arm motion, never sliding or floating. The bicycles, railing, shops and camera remain completely stationary. Distant road traffic moves naturally. A single continuous documentary shot with no cuts, zoom, text or graphics. Reference frames show approach, road detour and return.",
}
(SCENES / "motion-prompts.json").write_text(json.dumps(PROMPTS, indent=2))
selected = sys.argv[1:] or list(PROMPTS)
for index, scene in enumerate(selected):
    folder = SCENES / scene
    output = folder / "generated.mp4"
    valid = output.exists() and subprocess.run(["ffprobe", "-v", "error", str(output)],
                                               capture_output=True).returncode == 0
    if valid:
        print("EXISTS", output, flush=True)
        continue
    command = [str(ROOT / ".video-tools/ltx-2-mlx/.venv/bin/ltx-2-mlx"), "generate",
               "--model", str(ROOT / ".video-tools/models/ltx-2.3-q4"),
               "--gemma", str(ROOT / ".video-tools/models/gemma-3-12b-4bit"),
               "--distilled", "--low-ram", "--tile-frames", "2", "--tile-overlap", "4",
               "-W", "1024", "-H", "576", "-f", "121", "--frame-rate", "15",
               "--no-audio", "--seed", str(22102026 + list(PROMPTS).index(scene)),
               "--image", str(folder / "start.png"), "0", "1.0", "replace", "0",
               "--image", str(folder / "detour.png"), "60", "1.0", "guide", "0",
               "--image", str(folder / "return.png"), "last", "1.0", "guide", "0",
               "--prompt", PROMPTS[scene], "-o", str(output)]
    (folder / "render-command.json").write_text(json.dumps(command, indent=2))
    print("GENERATING", scene, flush=True)
    environment = {**os.environ, "LTX2_COMPUTE_DTYPE": "float16", "LTX2_VAE_DECODE_BUDGET_GB": "4"}
    with (folder / "generation.log").open("w") as log:
        completed = subprocess.run(command, cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT)
    print("FINISHED", scene, completed.returncode, flush=True)
    if completed.returncode:
        print((folder / "generation.log").read_text()[-5000:], flush=True)
        raise SystemExit(completed.returncode)
