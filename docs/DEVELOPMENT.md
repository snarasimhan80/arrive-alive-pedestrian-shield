# Changing the demo

## Where to edit

| Change | Files |
|---|---|
| First page layout, wording, upload/result flow | `templates/quick.html`, `static/quick.css`, `static/quick.js` |
| Evidence page | `templates/details.html`, `static/details.js` |
| Simple visual concern formula and crossing rules | `quick_screen.py` |
| Short anonymous pedestrian tracks | `pedestrian_tracks.py` |
| Person/vehicle segmentation and path overlap | `analyzer.py` |
| Extra shop-goods proposals | `obstructions.py` |
| FR-23/24 inputs and provisional visual signals | `scene_signals.py` |
| Site ranking | `site_table.py` |
| Original proposal and upload integration | `templates/proposal.html`, `static/proposal-module3.js` |
| Saved demo camera boundaries | `examples/generated-scenarios/calibrations.json`, `presets.json` |

Preserve the original ten illustrative proposal rows. Uploaded advanced
analyses belong in their separate table. Keep generated footage labelled.
The simple visual concern score is not the proposal's FR-24 exposure score.

## Edit and test

```sh
git switch -c improve-demo
python app.py
```

Refresh the page after static/template edits. Restart the development
process after Python changes. Restart also reloads camera presets.

In another shell with the venv active:

```sh
python -m unittest discover -s tests -v
python .video-tools/validate_clips.py --mode local
```

The clip runner checks complete videos: 2 exits and 2 returns for the car;
1 exit and return for shop goods, motorcycle and bicycles; 0 exits and 0
obstruction frames for the clear control. It also verifies that marked
videos retain the source frame rate and frame count. It records scores,
timestamps, content hashes and annotated videos in `artifacts/`.

For focused diagnosis, `--only 02-shop-goods` runs just that case. Run all
five before a release. Do not change expected counts merely to make a test
green; compare visible foot positions and review identity joins/occlusions.

Manually check upload, analysis progress, score, video playback, event-jump
buttons, detailed evidence and the proposal. New camera uploads need their
own reviewed path/road marking. The demo uses image-space heuristics and
does not infer real metres or km/h for an arbitrary upload.

Commit and push the branch, review/merge it, then deploy the pushed `main`
commit. The deployment helper rejects a dirty checkout and a commit that
is not the current `origin/main`.

## Updating sample assets

The four upload-ready MP4s, posters and polygons are committed. Their
content hashes select saved camera geometry, not cached scores. Renaming
an unchanged MP4 still works. Re-encoding it changes the hash and requires
reviewing/updating the preset.

If replacing the source generated clips, use the optional tools and
instructions in `examples/generated-scenarios/GENERATION.md`, run
`.video-tools/package_scenarios.py`, inspect all source motion and rerun
acceptance. Generation is optional and needs substantially more memory,
disk and separate model weights than the web demo.

Never commit `jobs/`, real user uploads, `.env`, credentials, virtual
environments, cache directories or generator weights. `.gitignore`, the
publication inventory and `.dockerignore` exclude these runtime artifacts.

## Source releases

```sh
python scripts/build_source.py
```

This produces ignored `dist/source.zip` from tracked source, model weights,
sample videos and handover files. Fresh validation, if present in
`artifacts/VALIDATION.json`, replaces the historical validation inside the
ZIP. The builder checks that acceptance matches the current analysis code
and sample hashes. `BUILD_MANIFEST.json` inventories every packaged file;
`RELEASE.json` records the Git commit. The server deployment helper checks
the complete inventory again before any restart.
