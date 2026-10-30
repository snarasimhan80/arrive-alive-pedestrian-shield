# Pedestrian Shield: Module 3 demo

The root page accepts a video, tracks visible people and reports a visual
concern score. Four generated Indian street scenes illustrate a parked car,
shop goods, a motorcycle and bicycles obstructing a pavement. The clips show
an approach, a detour into the road, and a return to the footpath. They carry
an explicit generated-footage label. They are simulations for demonstrating
the workflow, not field validation.

## What runs locally

* `yolov8n-seg.pt` detects people and vehicles and segments vehicle overlap
  with the saved footpath polygon.
* `obstruction-world.pt` is YOLOv8s-Worldv2 with frozen text embeddings for
  possible shop goods. This catches some boxes/crates outside the ordinary
  vehicle categories. These are approximate bounding boxes, not surveyed
  object footprints. The runtime does not download or run a text encoder.
* Short visual tracks associate detections between sampled frames. A road
  exit needs a recent footpath origin, two consecutive road observations,
  and a minimum image-space movement. Each track is counted once per clip.
  Clothing colour and motion help reconnect a walker after an occlusion of
  up to 1.5 seconds; this is anonymous tracking, not face recognition.
  Person boxes shorter than 12% of the image height are excluded from
  crossing tracks because distant detections have unstable footpoints.
* A nearby obstruction must be visible within two seconds and within an
  image-space distance of the crossing. That association is a review cue;
  real footage alone cannot establish why someone moved.
* A person remains red while their track is in the road. The red trail shows
  their route. A recorded return ends the red person highlight.

Generated examples are checked at about 3.75 frames per second. Goods
proposals refresh about once per second. The annotated output retains all
source frames at 15 fps; boxes update on analysis frames. Source video motion
is not replaced by a sequence of detection snapshots.

The server hashes a sample upload before applying that exact clip's reviewed
footpath and road polygons from `examples/generated-scenarios/presets.json`.
Renaming a sample does not change recognition. Another camera requires a
one-time footpath/road marking in `/analyze`. The demo does not automatically
infer the footpath boundary for arbitrary footage.

## Score and the proposal formulas

The simple page's 0–100 visual concern score is calculated from each run:

`5 + 25 × min(tracked exits, 3) + 10 if an exit was near an obstruction
+ 10 × nearby-vehicle frame share + 5 × obstruction frame share
+ 15 × min(tracked person-seconds in road / clip seconds, 1)`

The result is rounded and capped at 100. Runtime presets contain camera
polygons, without prefilled detections, timestamps or result scores. Each
upload is analyzed again. The detector can miss or misassociate people,
and a short clip is not an accuracy study. Two walkers spending three seconds
each in the road produce six person-seconds, not six seconds of video.

This visual index is distinct from the proposal's FR-24 exposure index. The
advanced `/analyze` workflow accepts explicitly sourced site inputs and uses:

* FR-23: peak pedestrian flow × (walking width lost / total path width).
* FR-24: displaced per hour × (traffic speed / 30)^1.5, normalized within
  the selected site set.
* FR-25: a site table ranked by that exposure.

The original proposal at `/proposal` retains its ten illustrative rows.
Advanced uploaded analyses appear in a separate table. Calibrated speed
gates and width/flow lines provide provisional visual estimates. Real metre
and km/h validation still needs surveyed dimensions and independent footage
measurements. Neither score is a crash probability or mortality prediction.

## Running the app

Use Python 3.12, FFmpeg, and `requirements-hosted.txt`, or the Dockerfile.
The two detector checkpoints and the example/config files must be present.
Set `HOSTED_DEMO=1` for the public demo limits and `DEMO_JOBS_DIR` for uploads.
One analysis worker queues jobs to bound CPU and memory use. Public uploaded
files expire after 24 hours on a later request; a result link grants viewing
access to its output.

## Media provenance and regeneration

The generated keyframes, motion prompts, reviewed zones, MP4s and generation
notes are in `examples/generated-scenarios/`. Keyframes were created with
the built-in image generation tool. Continuous motion was generated locally
with LTX-2.3 on MLX, rather than moving a static person cutout across a frame.
The optional `.video-tools/` source scripts describe generation and packaging;
the large generation model weights are not part of the runtime source ZIP.
See `examples/generated-scenarios/GENERATION.md` for commands and provenance.

Older filmed control clips under `examples/real-scenarios/` retain their
Pexels source credits and separate license terms:
https://www.pexels.com/legal-pages/license/ . The ten older synthetic edits
are not in the public gallery. Legacy advanced sample routes remain available.

## Licenses

The app and its Ultralytics detectors are distributed under AGPL-3.0; see
`LICENSE` and https://www.ultralytics.com/license . The generated footage is
labeled as such. Generation uses LTX-2's separate Community License, included
with the generation notes; its model weights are not distributed here.
Do not assume publishing this app grants a separate Enterprise model license
or clears every commercial use of a generation tool.
