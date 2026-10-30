const $ = (id) => document.getElementById(id);
const hosted = document.body.dataset.hosted === 'true';
const embedded = document.body.dataset.embedded === 'true';
let jobId = null;
let preview = new Image();
let polygon = [];
let roadPolygon = [];
let speedGatePoints = [];
let widthLinePoints = [];
let flowLinePoints = [];
let drawMode = 'footpath';
let pollTimer = null;
let latestReviews = { events: {}, misses: [] };
let currentSiteRows = [];
let currentSiteJobIds = [];
let movingSample = false;
const siteJobsKey = 'pedestrianShieldSiteJobs';

async function jsonRequest(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body;
}

function message(id, value, bad = false) {
  $(id).textContent = value;
  $(id).style.color = bad ? '#b3261e' : '';
}

function drawPolygon() {
  const canvas = $('preview-canvas');
  if (!preview.complete || !preview.naturalWidth) return;
  const context = canvas.getContext('2d');
  canvas.width = preview.naturalWidth;
  canvas.height = preview.naturalHeight;
  context.drawImage(preview, 0, 0);
  function drawArea(points, stroke, fill) {
    if (!points.length) return;
    context.beginPath();
    points.forEach(([x, y], index) => {
      if (index === 0) context.moveTo(x * canvas.width, y * canvas.height);
      else context.lineTo(x * canvas.width, y * canvas.height);
    });
    if (points.length > 2) { context.closePath(); context.fillStyle = fill; context.fill(); }
    context.strokeStyle = stroke;
    context.lineWidth = 3;
    context.stroke();
    points.forEach(([x, y]) => {
      context.beginPath();
      context.arc(x * canvas.width, y * canvas.height, 6, 0, 2 * Math.PI);
      context.fillStyle = '#fff';
      context.fill();
      context.strokeStyle = stroke;
      context.lineWidth = 2;
      context.stroke();
    });
  }
  drawArea(polygon, '#f5a623', 'rgba(242, 164, 31, .24)');
  drawArea(roadPolygon, '#2695d4', 'rgba(38, 149, 212, .15)');
  function drawLine(points, color, label) {
    if (!points.length) return;
    context.beginPath();
    points.forEach(([x, y], index) => index ? context.lineTo(x * canvas.width, y * canvas.height) : context.moveTo(x * canvas.width, y * canvas.height));
    context.strokeStyle = color; context.lineWidth = 4; context.stroke();
    points.forEach(([x, y]) => {
      context.beginPath(); context.arc(x * canvas.width, y * canvas.height, 6, 0, 2 * Math.PI);
      context.fillStyle = color; context.fill();
    });
    context.fillStyle = '#fff'; context.font = 'bold 14px sans-serif';
    context.fillText(label, points[0][0] * canvas.width + 9, points[0][1] * canvas.height - 9);
  }
  drawLine(widthLinePoints, '#f0dc3b', 'WIDTH');
  drawLine(flowLinePoints, '#71f27e', 'FLOW');
  speedGatePoints.forEach(([x, y], index) => {
    const color = index < 2 ? '#d8ed22' : '#db54ce';
    context.beginPath(); context.arc(x * canvas.width, y * canvas.height, 7, 0, 2 * Math.PI);
    context.fillStyle = color; context.fill();
    context.fillStyle = '#111'; context.font = 'bold 13px sans-serif';
    context.fillText(index < 2 ? 'A' : 'B', x * canvas.width + 10, y * canvas.height - 8);
    if (index === 1 || index === 3) {
      const first = speedGatePoints[index - 1];
      context.beginPath(); context.moveTo(first[0] * canvas.width, first[1] * canvas.height);
      context.lineTo(x * canvas.width, y * canvas.height);
      context.strokeStyle = color; context.lineWidth = 4; context.stroke();
    }
  });
  $('point-count').textContent = `Footpath ${polygon.length} · Roadway ${roadPolygon.length} · Width ${widthLinePoints.length}/2 · Count ${flowLinePoints.length}/2 · Speed ${speedGatePoints.length}/4`;
  $('analyze').disabled = polygon.length < 3;
}

$('preview-canvas').addEventListener('click', (event) => {
  const rect = event.currentTarget.getBoundingClientRect();
  const point = [
    Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
    Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
  ];
  if (drawMode === 'footpath' && polygon.length < 30) polygon.push(point);
  if (drawMode === 'road' && roadPolygon.length < 30) roadPolygon.push(point);
  if (drawMode === 'width' && widthLinePoints.length < 2) widthLinePoints.push(point);
  if (drawMode === 'flow' && flowLinePoints.length < 2) flowLinePoints.push(point);
  if (drawMode === 'speed' && speedGatePoints.length < 4) speedGatePoints.push(point);
  drawPolygon();
});
function selectedPoints() { return drawMode === 'road' ? roadPolygon : drawMode === 'speed' ? speedGatePoints : drawMode === 'width' ? widthLinePoints : drawMode === 'flow' ? flowLinePoints : polygon; }
function setDrawMode(mode) {
  drawMode = mode;
  for (const name of ['footpath', 'road', 'width', 'flow', 'speed']) $('mode-' + name).classList.toggle('mode-active', mode === name);
  $('mode-help').textContent = mode === 'footpath' ? 'Footpath: click at least three corners of the walking area.'
    : mode === 'road' ? 'Roadway: click at least three corners of the adjacent traffic area.'
      : mode === 'width' ? 'Width: click two points across the footpath where an obstruction meets the ground. Enter the real footpath width below; video width loss is provisional.'
        : mode === 'flow' ? 'Count: click two points to form a line pedestrians cross while walking along the footpath. A short clip is not a peak-hour count.'
          : 'Speed gates: click two endpoints across a traffic lane for A, then two for B; enter the real distance below.';
}
for (const name of ['footpath', 'road', 'width', 'flow', 'speed']) $('mode-' + name).addEventListener('click', () => setDrawMode(name));
$('undo-point').addEventListener('click', () => { selectedPoints().pop(); drawPolygon(); });
$('reset-points').addEventListener('click', () => { selectedPoints().length = 0; drawPolygon(); });
$('sample-setup').addEventListener('click', () => {
  polygon = [[0, 1], [0.43, 0.35], [0.58, 0.27], [0.85, 0.18], [0.995, 0.18], [0.995, 0.995]];
  roadPolygon = [[0, 0], [0.63, 0], [0.60, 0.18], [0.58, 0.27], [0.43, 0.35], [0, 1]];
  widthLinePoints = [[0.2, 0.55], [0.93, 0.55]];
  flowLinePoints = movingSample ? [[0.70, 0.55], [0.70, 0.95]] : [];
  speedGatePoints = movingSample ? [[0.27, 0.25], [0.27, 0.75], [0.15, 0.25], [0.15, 0.75]] : [];
  $('gate-distance').value = movingSample ? '6' : '';
  $('site-name').value = movingSample ? 'Synthetic moving Indian street' : 'Synthetic sample camera';
  $('footpath-width').value = '2.4'; $('footpath-width-source').value = 'synthetic demo value';
  $('width-lost').value = ''; $('width-lost-source').value = '';
  $('peak-flow').value = movingSample ? '' : '2400'; $('flow-source').value = movingSample ? '' : 'synthetic demo value';
  $('traffic-speed').value = movingSample ? '' : '40'; $('speed-source').value = movingSample ? '' : 'synthetic demo value';
  $('use-clip-flow').checked = movingSample;
  setDrawMode('footpath'); drawPolygon();
  message('file-status', movingSample
    ? 'Synthetic sample marks loaded. The 6 m gate spacing is part of this invented scene, and clip flow is an illustrative extrapolation. Review, then analyze.'
    : 'Synthetic sample marks and illustrative values loaded. Review them, then analyze.');
});

$('upload-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const file = $('source-file').files[0];
  if (!file) return;
  message('file-status', 'Loading and checking file…');
  const form = new FormData();
  form.append('file', file);
  try {
    const result = await jsonRequest('api/upload', { method: 'POST', body: form });
    jobId = result.job_id;
    localStorage.setItem('pedestrianShieldJob', jobId);
    polygon = [];
    roadPolygon = [];
    speedGatePoints = [];
    widthLinePoints = [];
    flowLinePoints = [];
    setDrawMode('footpath');
    $('mode-speed').disabled = result.kind !== 'video';
    $('mode-width').disabled = result.kind !== 'video';
    $('mode-flow').disabled = result.kind !== 'video';
    $('site-name').value = file.name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').slice(0, 80);
    movingSample = file.name.toLowerCase() === 'indian-footpath-continuous-motion.mp4';
    const isSample = movingSample || ['indian-footpath-clear-to-blocked.mp4', 'indian-footpath-blocked-with-pedestrians.mp4'].includes(file.name.toLowerCase());
    $('sample-setup').classList.toggle('hidden', !isSample);
    $('sample-setup-note').classList.toggle('hidden', !isSample);
    $('sample-setup-note').textContent = movingSample
      ? 'This synthetic clip includes moving people and cars. The preset draws the footpath, road, count line and speed gates. Its 2.4 m path width and 6 m gate spacing are invented test values; the short-clip flow rate is not a measured peak hour.'
      : 'This preset applies to the linked still-image synthetic videos. Width, pedestrian flow and speed values are illustrative; the video cross-section estimates blocked width.';
    $('result-section').classList.add('hidden');
    $('progress-section').classList.add('hidden');
    $('mark-section').classList.remove('hidden');
    preview = new Image();
    preview.onload = drawPolygon;
    preview.src = result.preview;
    message('file-status', `${file.name} loaded. ${result.kind === 'video' ? `${result.duration_seconds}s video` : 'Photo'} · ${result.width} × ${result.height} preview.`);
    $('mark-section').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    message('file-status', error.message, true);
  }
});

$('analyze').addEventListener('click', async () => {
  if (!jobId || polygon.length < 3) return;
  if (roadPolygon.length > 0 && roadPolygon.length < 3) { message('file-status', 'Finish marking the roadway with at least three points, or clear it.', true); return; }
  if (speedGatePoints.length > 0 && speedGatePoints.length < 4) { message('file-status', 'Finish both speed gates with four points, or clear them.', true); return; }
  if (widthLinePoints.length === 1 || flowLinePoints.length === 1) { message('file-status', 'Finish each width or pedestrian count line with two points, or clear it.', true); return; }
  if (speedGatePoints.length === 4 && !$('gate-distance').value) { message('file-status', 'Enter the measured distance between speed gates.', true); return; }
  if (!$('site-name').value.trim()) { message('file-status', 'Enter a site name.', true); return; }
  $('analyze').disabled = true;
  $('progress-section').classList.remove('hidden');
  $('result-section').classList.add('hidden');
  $('progress-fill').style.width = '0%';
  message('progress-text', hosted ? 'Waiting for the server model…' : 'Waiting for the local model…');
  try {
    const numberOrNull = (id) => $(id).value.trim() ? Number($(id).value) : null;
    await jsonRequest(`api/analyze/${jobId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        site_name: $('site-name').value.trim(), polygon, road_polygon: roadPolygon,
        width_line: widthLinePoints.length === 2 ? widthLinePoints : null,
        flow_line: flowLinePoints.length === 2 ? flowLinePoints : null,
        min_overlap: Number($('overlap').value),
        speed_gates: speedGatePoints.length === 4 ? { a: speedGatePoints.slice(0, 2), b: speedGatePoints.slice(2, 4), distance_m: Number($('gate-distance').value) } : null,
        footpath_width_m: numberOrNull('footpath-width'), width_lost_m: numberOrNull('width-lost'),
        peak_flow_per_hour: numberOrNull('peak-flow'), traffic_speed_kmh: numberOrNull('traffic-speed'),
        footpath_width_source: $('footpath-width-source').value || null,
        width_lost_source: $('width-lost-source').value || null,
        flow_source: $('flow-source').value || null,
        use_clip_flow_for_demo: $('use-clip-flow').checked,
        speed_source: $('speed-source').value || null,
      }),
    });
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(checkStatus, 1200);
    checkStatus();
  } catch (error) {
    message('progress-text', error.message, true);
    $('analyze').disabled = false;
  }
});

async function checkStatus() {
  if (!jobId) return;
  try {
    const state = await jsonRequest(`api/status/${jobId}`);
    if (state.status === 'done') {
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = null;
      $('progress-section').classList.add('hidden');
      $('analyze').disabled = false;
      latestReviews = state.reviews || { events: {}, misses: [] };
      renderResult(state.report);
      return;
    }
    if (state.status === 'error') {
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = null;
      message('progress-text', state.message, true);
      $('analyze').disabled = false;
      return;
    }
    message('progress-text', state.message || 'Analyzing…');
    if (state.total) $('progress-fill').style.width = `${Math.min(100, state.done / state.total * 100)}%`;
  } catch (error) {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
    message('progress-text', error.message, true);
    $('analyze').disabled = false;
  }
}

function media(name) { return `media/${jobId}/${encodeURIComponent(name)}`; }
function line(text) { const p = document.createElement('p'); p.textContent = text; return p; }
function stat(value, label) {
  const div = document.createElement('div');
  div.className = 'stat';
  const big = document.createElement('b'); big.textContent = value;
  const small = document.createElement('span'); small.textContent = label;
  div.append(big, small);
  return div;
}
function link(name, label) {
  const anchor = document.createElement('a');
  anchor.href = media(name); anchor.download = name; anchor.textContent = label;
  return anchor;
}

function savedSiteJobs() {
  try {
    const value = JSON.parse(localStorage.getItem(siteJobsKey) || '[]');
    return Array.isArray(value) ? value.filter((id) => /^[0-9a-f]{32}$/.test(id)).slice(-20) : [];
  } catch { return []; }
}
function addSiteJob(id) {
  const ids = savedSiteJobs().filter((existing) => existing !== id);
  ids.push(id);
  localStorage.setItem(siteJobsKey, JSON.stringify(ids.slice(-20)));
}
function tableValue(value, suffix = '') { return value == null ? '—' : `${Number(value).toLocaleString()}${suffix}`; }
function siteCell(row, value, source) {
  const cell = document.createElement('td');
  cell.textContent = value;
  if (source) {
    const note = document.createElement('small'); note.className = 'source-note'; note.textContent = source;
    cell.append(note);
  }
  row.append(cell);
  return cell;
}
function renderSiteTable(rows, scope, ids = []) {
  currentSiteRows = rows;
  currentSiteJobIds = ids;
  const body = $('site-table-body'); body.replaceChildren();
  $('site-table').classList.toggle('hidden', !rows.length);
  $('copy-sites-link').classList.toggle('hidden', !ids.length);
  $('download-sites-csv').classList.toggle('hidden', !rows.length);
  $('site-table-note').textContent = rows.length ? `${scope} Complete rows are sorted by the PRD formula. This is a relative planning index, not accident probability.` : 'No saved site analyses yet. Analyze a clip or open the synthetic example.';
  for (const item of rows) {
    const tr = document.createElement('tr');
    const nameCell = document.createElement('td');
    if (item.job_id) {
      const anchor = document.createElement('a');
      anchor.href = `${window.location.pathname}?job=${item.job_id}`;
      anchor.textContent = item.site_name;
      nameCell.append(anchor);
    } else nameCell.textContent = item.site_name;
    if (item.synthetic) {
      const badge = document.createElement('small'); badge.className = 'synthetic-badge'; badge.textContent = 'SYNTHETIC';
      nameCell.append(badge);
    }
    tr.append(nameCell);
    siteCell(tr, tableValue(item.footpath_width_m, ' m'), item.footpath_width_source);
    siteCell(tr, tableValue(item.width_lost_m, ' m'), item.width_lost_source);
    siteCell(tr, tableValue(item.peak_flow_per_hour), item.flow_source);
    siteCell(tr, tableValue(item.speed_kmh, ' km/h'), item.speed_source);
    siteCell(tr, tableValue(item.displaced_per_hour));
    const score = siteCell(tr, item.relative_exposure_0_100 == null ? 'Inputs needed' : `${item.relative_exposure_0_100}/100`);
    score.classList.add(item.relative_exposure_0_100 == null ? 'score-missing' : 'score-chip');
    body.append(tr);
  }
}
async function loadMySites(ids = null) {
  const fromLocal = ids === null;
  ids = ids || savedSiteJobs();
  try {
    const result = await jsonRequest('api/sites', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ job_ids: ids }) });
    const availableIds = ids.filter((id) => !result.missing.includes(id));
    renderSiteTable(result.rows, result.scope, availableIds);
    if (fromLocal) localStorage.setItem(siteJobsKey, JSON.stringify(availableIds));
  } catch (error) { message('site-table-note', error.message, true); }
}
$('show-my-sites').addEventListener('click', () => loadMySites());
$('show-demo-sites').addEventListener('click', async () => {
  try {
    const result = await jsonRequest('api/demo-sites');
    renderSiteTable(result.rows, result.scope);
  } catch (error) { message('site-table-note', error.message, true); }
});
$('clear-my-sites').addEventListener('click', () => {
  localStorage.removeItem(siteJobsKey);
  renderSiteTable([], '');
});
$('copy-sites-link').addEventListener('click', async () => {
  const url = new URL(window.location.pathname, window.location.origin);
  url.searchParams.set('sites', currentSiteJobIds.join(','));
  try { await navigator.clipboard.writeText(url.toString()); message('site-table-note', 'Comparison link copied. It works until these analysis files expire.'); }
  catch { window.prompt('Copy comparison link', url.toString()); }
});
$('download-sites-csv').addEventListener('click', () => {
  const fields = ['site_name', 'footpath_width_m', 'footpath_width_source', 'width_lost_m', 'width_lost_source', 'peak_flow_per_hour', 'flow_source', 'speed_kmh', 'speed_source', 'displaced_per_hour', 'raw_exposure', 'relative_exposure_0_100', 'synthetic'];
  const csvCell = (value) => {
    let text = value == null ? '' : String(value);
    if (/^[=+@-]/.test(text)) text = `'${text}`;
    return `"${text.replaceAll('"', '""')}"`;
  };
  const csv = [fields.join(','), ...currentSiteRows.map((item) => fields.map((field) => csvCell(item[field])).join(','))].join('\r\n');
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'fr25-site-table.csv'; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

function renderResult(report) {
  const resultUrl = new URL(window.location.href);
  resultUrl.searchParams.set('job', jobId);
  if (!embedded) resultUrl.searchParams.delete('embedded');
  window.history.replaceState({}, '', resultUrl.pathname + resultUrl.search);
  $('result-section').classList.remove('hidden');
  addSiteJob(jobId);
  loadMySites();
  $('result-url').textContent = hosted ? 'You can share this page address with a reviewer. Anyone with it can view this run until its files expire.' : 'This page address opens the saved result on this computer.';
  const people = report.people || {};
  $('clip-status').textContent = report.possible_obstructions
    ? (people.possible_path_to_road_moves?.length ? 'Possible blockage and candidate footpath-to-road movement found. Review the marked frames before treating them as related.'
      : people.road_person_with_blockage_frames ? 'Possible blockage and a person-shaped road detection appear in the same frames. It may be a rider; this clip does not establish displacement.'
        : 'Possible footpath obstruction detected. Roadway displacement was not established by this clip.')
    : 'No vehicle obstruction detected in sampled frames — check for missed hazards.';
  $('summary').replaceChildren(
    stat(report.possible_obstructions, 'Possible obstruction events'),
    stat(report.flagged_frames, 'Sampled frames with a flag'),
    stat(report.sampled_frames, 'Frames analyzed'),
    stat(people.max_in_frame ?? '—', 'Most people detected in a frame'),
  );
  $('downloads').replaceChildren(
    link('evidence.zip', 'Download marked photos and report'),
    link('report.json', 'JSON report'),
    link('events.csv', 'Event CSV'),
    link('reviews.json', 'Review labels'),
  );
  const videoPanel = $('video-panel');
  if (report.annotated_video) {
    $('annotated-video').src = media(report.annotated_video);
    videoPanel.classList.remove('hidden');
  } else videoPanel.classList.add('hidden');

  const eventWrap = $('events');
  eventWrap.replaceChildren();
  if (!report.events.length) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = 'No vehicle obstruction was flagged. Review the no-flag frames below; the model can miss hazards.';
    eventWrap.append(empty);
  }
  report.events.forEach((item) => {
    const card = document.createElement('article'); card.className = 'event-card';
    const img = document.createElement('img'); img.src = media(item.snapshot); img.alt = `Marked possible ${item.class} obstruction at ${item.start_seconds} seconds`;
    const body = document.createElement('div'); body.className = 'event-body';
    const title = document.createElement('h3'); title.textContent = `${item.class} · ${item.start_seconds.toFixed(1)}s${item.end_seconds > item.start_seconds ? `–${item.end_seconds.toFixed(1)}s` : ''}`;
    const info = document.createElement('p'); info.className = 'event-meta';
    info.textContent = `Model confidence ${(item.peak_confidence * 100).toFixed(0)}% · lower visible area overlap ${(item.peak_overlap * 100).toFixed(0)}%`;
    const row = document.createElement('div'); row.className = 'review-row';
    for (const [verdict, label] of [['correct', 'Real obstruction'], ['false_alarm', 'False alarm']]) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'button button-plain button-small';
      button.textContent = label; button.dataset.selected = String(latestReviews.events[String(item.id)] === verdict);
      button.addEventListener('click', async () => {
        try {
          const saved = await jsonRequest(`api/review/${jobId}`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: 'event', event_id: item.id, verdict }),
          });
          latestReviews = saved.reviews;
          row.querySelectorAll('button').forEach((b) => { b.dataset.selected = String(b === button); });
        } catch (error) { alert(error.message); }
      });
      row.append(button);
    }
    body.append(title, info, row); card.append(img, body); eventWrap.append(card);
  });

  const personLines = [
    line(`Most people seen together in one frame: ${people.max_in_frame ?? 'not checked'}.`),
    line(`Possible crowd: ${people.crowd_frames ?? 0} sampled frames with at least three nearby people (largest nearby group: ${people.max_nearby_group ?? 0}).`),
    line(report.road_polygon?.length ? `Person-shaped detection in marked roadway: ${people.road_person_frames ?? 0} sampled frames; ${people.road_person_with_blockage_frames ?? 0} also had a blockage flag. Some may be riders.` : 'Roadway was not marked, so road presence and footpath-to-road movement were not assessed.'),
    line(`Possible footpath-to-road movements during a blockage: ${people.possible_path_to_road_moves?.length ?? 0}. These are short visual tracks for review, not proof of cause.`),
  ];
  $('people-summary').replaceChildren(...personLines);
  const personEvidence = $('person-evidence'); personEvidence.replaceChildren();
  const evidence = [];
  if (people.crowd_snapshot) evidence.push([people.crowd_snapshot, 'Possible crowd']);
  if (people.road_person_snapshot) evidence.push([people.road_person_snapshot, 'Person-shaped road cue during blockage']);
  for (const move of people.possible_path_to_road_moves || []) evidence.push([move.snapshot, `Possible footpath-to-road movement at ${move.seconds}s`]);
  for (const [name, label] of evidence) {
    const figure = document.createElement('figure'); figure.className = 'event-card';
    const img = document.createElement('img'); img.src = media(name); img.alt = label;
    const caption = document.createElement('figcaption'); caption.className = 'event-body'; caption.textContent = label;
    figure.append(img, caption); personEvidence.append(figure);
  }
  if (!evidence.length) personEvidence.append(line('No crowd or road-person evidence snapshot in this clip. Inspect the annotated video for people the model may have missed.'));

  const speed = report.traffic_speed || {};
  const exposure = report.exposure || {};
  const site = report.site_inputs || {};
  const flow = report.pedestrian_flow || {};
  const speedText = speed.kmh == null
    ? `Traffic speed unavailable. ${speed.video_gate_status || 'This clip needs moving road vehicles crossing two marked gates with a measured distance, or an external speed reading.'}`
    : `Traffic speed used: ${speed.kmh} km/h (${speed.source}; ${speed.video_vehicle_samples_kmh?.length || 0} video vehicle samples).`;
  const widthText = site.width_lost_m == null
    ? 'Blocked width unavailable. Enter a site measurement or draw a width line through the obstruction and enter measured footpath width.'
    : `Path width: ${site.footpath_width_m} m (${site.footpath_width_source || 'source unspecified'}). Width lost: ${site.width_lost_m} m (${site.width_lost_source || 'source unspecified'}; ${site.width_estimate_samples || 0} video cross-section samples).`;
  const flowText = flow.observed_line_crossings == null
    ? `Peak pedestrian flow: ${site.peak_flow_per_hour ?? 'unavailable'} people/hour (${site.flow_source || 'no count line marked'}).`
    : `Count-line crossings: ${flow.observed_line_crossings} in ${flow.clip_duration_seconds}s. Short-clip hourly equivalent: ${flow.clip_hourly_equivalent ?? 'unavailable'}; PRD peak flow used: ${site.peak_flow_per_hour ?? 'unavailable'} (${site.flow_source || 'none'}).`;
  const displacementText = exposure.displaced_per_hour == null
    ? 'FR-23 unavailable: footpath width, width lost, and peak pedestrian flow are all needed.'
    : `FR-23 estimate: ${exposure.displaced_per_hour.toLocaleString()} people/hour potentially displaced = ${site.peak_flow_per_hour} × (${site.width_lost_m} m ÷ ${site.footpath_width_m} m). This is not an observed count of people stepping onto the road.`;
  const riskText = exposure.speed_weighted_exposure == null
    ? 'FR-24 unavailable: a sourced traffic speed and FR-23 inputs are needed.'
    : `FR-24 raw exposure index: ${exposure.speed_weighted_exposure.toLocaleString()} = displaced/hour × (${speed.kmh} ÷ 30)^1.5. Speed multiplier versus 30 km/h: ${exposure.speed_multiplier}×.`;
  $('exposure-summary').replaceChildren(line(widthText), line(flowText), line(speedText), line(displacementText), line(riskText),
    line('FR-25 at the top compares all selected sites and normalizes the worst complete site to 100. It is a relative planning ranking, not an accident or mortality prediction.'));

  const clearWrap = $('clear-frames'); clearWrap.replaceChildren();
  report.no_flag_samples.forEach((item) => {
    const figure = document.createElement('figure');
    const img = document.createElement('img'); img.src = media(item.snapshot); img.alt = `No vehicle blockage detected at ${item.seconds} seconds`;
    const caption = document.createElement('figcaption'); caption.textContent = `${item.seconds.toFixed(1)}s · no flag`;
    figure.append(img, caption); clearWrap.append(figure);
  });
  $('result-section').scrollIntoView({ behavior: 'smooth', block: 'start' });
  if (embedded && window.parent !== window) {
    const height = Math.ceil(document.querySelector('.shell').getBoundingClientRect().height + 8);
    window.parent.postMessage({ type: 'module3:resize', height }, window.location.origin);
    window.parent.postMessage({ type: 'module3:analysis-complete', jobId }, window.location.origin);
  }
}

$('new-file').addEventListener('click', () => {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
  jobId = null;
  polygon = [];
  roadPolygon = [];
  speedGatePoints = [];
  widthLinePoints = [];
  flowLinePoints = [];
  setDrawMode('footpath');
  localStorage.removeItem('pedestrianShieldJob');
  window.history.replaceState({}, '', window.location.pathname + (embedded ? '?embedded=1' : ''));
  $('source-file').value = '';
  $('mode-speed').disabled = false;
  $('mode-width').disabled = false;
  $('mode-flow').disabled = false;
  for (const id of ['gate-distance', 'footpath-width', 'width-lost', 'peak-flow', 'traffic-speed']) $(id).value = '';
  $('site-name').value = '';
  for (const id of ['footpath-width-source', 'width-lost-source', 'flow-source', 'speed-source']) $(id).value = '';
  $('use-clip-flow').checked = false;
  $('sample-setup').classList.add('hidden');
  $('sample-setup-note').classList.add('hidden');
  $('mark-section').classList.add('hidden');
  $('progress-section').classList.add('hidden');
  $('result-section').classList.add('hidden');
  message('file-status', hosted ? 'Choose a video or photo to start a new server analysis.' : 'Choose a video or photo to start a new local analysis.');
  window.scrollTo({ top: 0, behavior: 'smooth' });
});

$('miss-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!jobId) return;
  try {
    const saved = await jsonRequest(`api/review/${jobId}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'miss', seconds: Number($('miss-seconds').value), note: $('miss-note').value }),
    });
    latestReviews = saved.reviews;
    message('miss-status', `Saved. ${latestReviews.misses.length} missed finding(s) recorded.`);
    $('miss-form').reset();
  } catch (error) { message('miss-status', error.message, true); }
});

const queryParams = new URLSearchParams(window.location.search);
const querySites = queryParams.get('sites');
if (querySites) loadMySites(querySites.split(',').filter((id) => /^[0-9a-f]{32}$/.test(id)).slice(0, 20));
else loadMySites();
const queryJob = queryParams.get('job');
const previousJob = /^[0-9a-f]{32}$/.test(queryJob || '') ? queryJob : querySites || embedded ? null : localStorage.getItem('pedestrianShieldJob');
if (previousJob) {
  jobId = previousJob;
  jsonRequest(`api/status/${jobId}`).then((state) => {
    if (state.status === 'done') {
      latestReviews = state.reviews || { events: {}, misses: [] };
      renderResult(state.report);
      message('file-status', hosted ? 'Showing your last server analysis. Load another file to start a new one.' : 'Showing your last local analysis. Load another file to start a new one.');
    } else if (state.status === 'running' || state.status === 'queued') {
      $('progress-section').classList.remove('hidden');
      pollTimer = setInterval(checkStatus, 1200);
      checkStatus();
    }
  }).catch(() => localStorage.removeItem('pedestrianShieldJob'));
}
if (embedded && window.parent !== window) {
  const sendHeight = () => {
    const height = Math.ceil(document.querySelector('.shell').getBoundingClientRect().height + 8);
    window.parent.postMessage({ type: 'module3:resize', height }, window.location.origin);
  };
  new ResizeObserver(sendHeight).observe(document.querySelector('.shell'));
  window.addEventListener('load', sendHeight);
  sendHeight();
}
