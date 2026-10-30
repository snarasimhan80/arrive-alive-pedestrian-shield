const $ = (id) => document.getElementById(id);
let activeJob = null;
let polling = null;

async function jsonRequest(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body;
}

function status(text, error = false) {
  $('status').textContent = text;
  $('status').classList.toggle('error', error);
}

function setBusy(busy) {
  document.querySelectorAll('[data-sample]').forEach((button) => button.disabled = busy);
  $('source-file').disabled = busy;
  $('progress').classList.toggle('hidden', !busy);
  if (busy) $('progress-fill').style.width = '5%';
}

async function analyzeFile(file) {
  if (!file) return;
  if (polling) clearTimeout(polling);
  activeJob = null;
  $('result').classList.add('hidden');
  $('result-preview').classList.add('hidden');
  setBusy(true);
  status(`Uploading ${file.name}…`);
  try {
    const form = new FormData();
    form.append('file', file);
    const uploaded = await jsonRequest('api/upload', { method: 'POST', body: form });
    activeJob = uploaded.job_id;
    status('Analyzing video frames…');
    await jsonRequest(`api/quick/${activeJob}`, { method: 'POST' });
    await checkStatus();
  } catch (error) {
    setBusy(false);
    status(error.message, true);
  }
}

async function checkStatus() {
  if (!activeJob) return;
  try {
    const state = await jsonRequest(`api/status/${activeJob}`);
    if (state.status === 'done') {
      setBusy(false);
      if (state.report.mode !== 'quick') {
        window.location.replace(`analyze?job=${encodeURIComponent(activeJob)}`);
        return;
      }
      showResult(state.report);
      status('Analysis complete. Choose another clip to compare.');
      return;
    }
    if (state.status === 'error') throw new Error(state.message || 'Analysis failed.');
    status(state.message || 'Analyzing video frames…');
    if (state.total) $('progress-fill').style.width = `${Math.max(5, Math.min(96, state.done / state.total * 96))}%`;
    polling = setTimeout(checkStatus, 1200);
  } catch (error) {
    setBusy(false);
    status(error.message, true);
  }
}

function showResult(report) {
  const score = report.score;
  const level = score >= 60 ? 'Higher concern' : score >= 30 ? 'Some concern' : 'Lower concern';
  $('score').textContent = String(score);
  $('result-label').textContent = level;
  $('score-tile').dataset.level = score >= 60 ? 'high' : score >= 30 ? 'medium' : 'low';
  const count = report.path_to_road_crossings;
  const calibrated = report.displacement_status === 'observed_crossing';
  $('result-explanation').textContent = calibrated
    ? `${count} tracked ${count === 1 ? 'exit' : 'exits'} from the footpath into the road. ${report.blocker_frames ? `${report.crossings_with_blockage_nearby} occurred near a detected obstruction.` : 'No path obstruction was detected.'} Red follows the pedestrian movement in the marked video below.`
    : `This upload has no saved path marking, so path-to-road movement was not measured. This ${score}/100 is a general people-near-vehicles screening score. Mark this camera's path in the detailed setup to measure crossings.`;
  $('crossing-count').textContent = calibrated ? `${count} path-to-road ${count === 1 ? 'crossing' : 'crossings'} tracked` : 'Crossings not measured';
  const links = $('event-links');
  links.replaceChildren();
  for (const event of report.movement_events || []) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = `Watch red event at ${event.seconds.toFixed(1)}s`;
    button.addEventListener('click', () => {
      const video = $('result-video');
      video.currentTime = Math.max(0, event.seconds - 0.5);
      video.play();
      $('result-preview').scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    links.append(button);
  }
  if (report.annotated_video) {
    const video = $('result-video');
    video.src = `media/${activeJob}/annotated.mp4`;
    const firstEvent = (report.movement_events || [])[0];
    video.poster = firstEvent?.snapshot ? `media/${activeJob}/${firstEvent.snapshot}` : '';
    $('result-preview').classList.remove('hidden');
  }
  $('details-link').href = `details?job=${encodeURIComponent(activeJob)}`;
  $('result').classList.remove('hidden');
  window.history.replaceState({}, '', `?job=${encodeURIComponent(activeJob)}`);
  $('result').scrollIntoView({ behavior: 'smooth', block: 'center' });
}

$('source-file').addEventListener('change', () => analyzeFile($('source-file').files[0]));
$('upload-form').addEventListener('submit', (event) => event.preventDefault());
document.querySelectorAll('[data-sample]').forEach((button) => button.addEventListener('click', async () => {
  const kind = button.dataset.sample;
  const url = `samples/${kind}.mp4`;
  try {
    setBusy(true);
    status(`Loading ${kind} sample…`);
    const response = await fetch(url);
    if (!response.ok) throw new Error('Could not load the sample video.');
    const blob = await response.blob();
    await analyzeFile(new File([blob], `${kind}.mp4`, { type: 'video/mp4' }));
  } catch (error) {
    setBusy(false);
    status(error.message, true);
  }
}));

const queryJob = new URLSearchParams(window.location.search).get('job');
if (/^[0-9a-f]{32}$/.test(queryJob || '')) {
  activeJob = queryJob;
  setBusy(true);
  status('Loading saved analysis…');
  checkStatus();
}
