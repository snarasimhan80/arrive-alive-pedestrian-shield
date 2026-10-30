# Generated obstruction clips

These are generated simulations of Indian street layouts. No real person,
place, CCTV event or measured road speed is represented. Each source MP4
has a visible `GENERATED DEMO FOOTAGE` label. The marked analysis also labels
the scene as generated.

## Assets and motion

Each scenario directory contains three image-generation keyframes:
`start.png`, `detour.png` and `return.png`. The built-in image generation tool
created the first frame and edited the same scene to preserve the camera,
obstruction and actor identities across the other two frames.

The start-frame specification was a photorealistic elevated fixed camera
looking along an Indian shopfront footpath beside a road, with a clear curb,
an obstruction spanning the walking route, and pedestrians approaching.
The middle-frame edit moved the same pedestrians onto the asphalt beside
the obstruction. The final-frame edit placed them back on the footpath past
it. The four cases are:

| Scene | Obstruction | Main pedestrians |
|---|---|---|
| parked-car | Silver hatchback across pavement | Woman in rust-red clothes, man in green shirt |
| shop-goods | Crates, sacks and a display table | Woman in teal kurta |
| motorbike | Motorcycle across pavement | Woman in yellow kurta; man already beyond it |
| bicycles | Two bicycles protruding across pavement | Man with cream shirt and backpack |

`motion-prompts.json` contains the exact final video prompts. The generated
motion uses LTX-2.3, int4 MLX weights, distilled two-stage inference, guided by
the three images at frames 0, 60 and 120. Settings: 1024×576, 121 frames,
15 fps, no audio, low-memory block streaming and two temporal tiles. Seeds
are 22102026 through 22102029 in the order in that prompt JSON. This is
continuous generative video, not a static person image translated sideways.

The implementation is https://github.com/dgrauet/ltx-2-mlx at commit
`8efbfef427afd873f25d976231a87922786fe39e`. The generator is an offline asset
tool, not part of the hosted detector. Its weights and dependencies are not
included in the app's source archive. LTX's separate Community License is
included in `LICENSE-LTX-2.txt`; do not infer a commercial model license from
the app's AGPL distribution.

## Reproduce from the source archive

Create the app's Python environment and install its requirements first.
The optional generation scripts live in `.video-tools/`. They also support
the original workspace layout with the app inside `module3-demo/`.

```sh
git clone https://github.com/dgrauet/ltx-2-mlx .video-tools/ltx-2-mlx
git -C .video-tools/ltx-2-mlx checkout 8efbfef427afd873f25d976231a87922786fe39e
(cd .video-tools/ltx-2-mlx && uv sync)
.venv/bin/python .video-tools/download_ltx.py
.venv/bin/python .video-tools/download_ltx.py --gemma
.venv/bin/python .video-tools/render_scenarios.py
.venv/bin/python .video-tools/package_scenarios.py
```

The first render on the development M1 Max took about 15 minutes. Generation
needs substantial local disk and unified memory; it does not run on the
small public web server. Packaging preserves every generated frame, adds
the provenance label, encodes H.264 and hashes each upload-ready MP4.

`calibrations.json` contains the reviewed footpath and road boundaries.
`presets.json` associates these boundaries with exact MP4 content hashes.
Neither file stores scores or movement events. The app reruns its local
vision detectors and tracker for every uploaded example.

## Verification

Review the whole source movement, the obstruction's persistence and each red
track. Check the detected exit and return against visible movement. A visible
crossing in generated footage demonstrates workflow behavior, not field
accuracy. The clear filmed control clip was also checked for false alarms.
The final run evidence is in `VALIDATION.json` when delivery is complete.

The first public shop-goods run joined two tiny distant people into a false
extra track. The crossing tracker now excludes person boxes shorter than
12% of the image height. All four examples and the clear control are rerun
against the final code locally and on the public server. This illustrates
why the generated workflow checks are not a substitute for field validation.
