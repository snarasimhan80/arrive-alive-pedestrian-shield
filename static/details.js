const $ = (id) => document.getElementById(id);
const jobId = new URLSearchParams(window.location.search).get('job');
if (!/^[0-9a-f]{32}$/.test(jobId || '')) {
  $('detail-status').textContent = 'No analysis selected. Upload a video from the first page.';
} else {
  fetch(`api/status/${jobId}`).then(async (response) => {
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Analysis unavailable.');
    if (result.status !== 'done') throw new Error('Analysis is still running. Return to the first page.');
    if (result.report.mode !== 'quick') {
      window.location.replace(`analyze?job=${jobId}`);
      return;
    }
    render(result.report);
  }).catch((error) => { $('detail-status').textContent = error.message; });
}

function render(report) {
  $('detail-status').classList.add('hidden');
  $('detail-content').classList.remove('hidden');
  $('detail-score').textContent = `${report.score}/100`;
  $('detail-label').textContent = report.score >= 60 ? 'Higher visual concern' : report.score >= 30 ? 'Some visual concern' : 'Lower visual concern';
  const calibrated = report.displacement_status === 'observed_crossing';
  $('detail-intro').textContent = calibrated
    ? `${report.camera_preset || 'Configured camera'}. The model checked ${report.sampled_frames} frames and tracked ${report.path_to_road_crossings} path-to-road exits. ${report.crossings_with_blockage_nearby} were near a detected obstruction.`
    : `The model sampled ${report.sampled_frames} frames. This camera has no saved path boundary, so crossings were not measured.`;
  const metrics = [
    [calibrated ? report.path_to_road_crossings : '—', 'tracked path-to-road crossings'],
    [calibrated ? report.crossings_with_blockage_nearby : '—', 'crossings with blocker nearby'],
    [report.road_person_seconds == null ? '—' : report.road_person_seconds.toFixed(1), 'tracked person-seconds in road'],
    [report.returned_to_path_count ?? '—', 'tracked returns to footpath'],
    [report.blocker_frames ?? '—', 'sampled frames with obstruction'],
    [report.max_people_in_frame, 'most people in one frame'],
  ];
  for (const [value, label] of metrics) {
    const tile = document.createElement('div'); tile.className = 'metric';
    const strong = document.createElement('strong'); strong.textContent = value;
    const span = document.createElement('span'); span.textContent = label;
    tile.append(strong, span); $('metrics').append(tile);
  }
  if (report.annotated_video) {
    const video = $('marked-video');
    video.src = `media/${jobId}/annotated.mp4`;
    const firstEvent = (report.movement_events || [])[0];
    if (firstEvent?.snapshot) video.poster = `media/${jobId}/${firstEvent.snapshot}`;
    video.classList.remove('hidden');
  } else if (report.snapshots.length) {
    $('marked-photo').src = `media/${jobId}/${report.snapshots[0].file}`;
    $('marked-photo').classList.remove('hidden');
  }
  if (calibrated) {
    $('movement-section').classList.remove('hidden');
    if (!report.movement_events.length) {
      $('movement-events').textContent = 'No path-to-road crossing was tracked in this clip.';
    }
    for (const event of report.movement_events) {
      const row = document.createElement('p');
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'event-jump';
      button.textContent = `Watch ${event.seconds.toFixed(1)}s`;
      button.addEventListener('click', () => {
        const video = $('marked-video');
        video.currentTime = Math.max(0, event.seconds - .5);
        video.play();
        video.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
      const movement = event.blocked_nearby ? ' · Possible obstruction detour' : ' · Path exit; no obstruction confirmed nearby';
      const duration = event.road_seconds == null ? '' : ` · ${event.road_seconds.toFixed(1)}s tracked in road`;
      const returned = event.return_seconds == null ? '' : ` · back on path at ${event.return_seconds.toFixed(1)}s`;
      row.append(button, document.createTextNode(movement + duration + returned));
      $('movement-events').append(row);
    }
  }
  for (const snapshot of report.snapshots) {
    const figure = document.createElement('figure');
    const img = document.createElement('img');
    img.src = `media/${jobId}/${snapshot.file}`;
    img.alt = `Detector snapshot at ${snapshot.seconds} seconds`;
    const caption = document.createElement('figcaption');
    caption.textContent = `${snapshot.seconds.toFixed(1)}s · ${snapshot.kind === 'crossing' ? 'tracked crossing in red' : snapshot.kind === 'nearby' ? 'person and nearby vehicle' : 'sampled frame'}`;
    figure.append(img, caption); $('snapshots').append(figure);
  }
  $('method').textContent = report.score_method + '. This calculation uses detector output from this run.';
  for (const text of report.limits) {
    const item = document.createElement('li'); item.textContent = text; $('limits').append(item);
  }
}
