(() => {
  const frame = document.getElementById('module3-video-frame');
  const body = document.getElementById('analyzed-ped-rows');
  const note = document.getElementById('analyzed-ped-note');
  const count = document.getElementById('analyzed-ped-count');
  const copyButton = document.getElementById('copy-ped-link');
  if (!frame || !body) return;

  const storageKey = 'pedestrianShieldProposalJobs';
  let selectedIds = [];

  function validIds(value) {
    return Array.isArray(value) ? [...new Set(value.filter((id) => typeof id === 'string' && /^[0-9a-f]{32}$/.test(id)))].slice(-20) : [];
  }
  function savedIds() {
    try { return validIds(JSON.parse(localStorage.getItem(storageKey) || '[]')); }
    catch { return []; }
  }
  function saveIds(ids) {
    selectedIds = validIds(ids);
    localStorage.setItem(storageKey, JSON.stringify(selectedIds));
  }
  function textCell(row, main, detail) {
    const cell = document.createElement('td');
    cell.className = 'num';
    cell.textContent = main;
    if (detail) {
      const small = document.createElement('div');
      small.className = 'module3-row-note';
      small.textContent = detail;
      cell.append(small);
    }
    row.append(cell);
  }
  function number(value, digits = 0) {
    return value == null ? '—' : Number(value).toLocaleString('en-IN', { maximumFractionDigits: digits });
  }
  function renderAnalyzed(rows) {
    body.replaceChildren();
    count.textContent = rows.length ? `${rows.length} analyzed ${rows.length === 1 ? 'site' : 'sites'}` : 'No uploads analyzed yet';
    copyButton.hidden = !rows.length;
    if (!rows.length) {
      const row = document.createElement('tr');
      const cell = document.createElement('td');
      cell.colSpan = 5;
      cell.textContent = 'No analyzed sites yet. Upload a clip above, mark its footpath, and run the detector.';
      row.append(cell);
      body.append(row);
      note.textContent = 'No analyzed video sites yet. Upload a clip above to add one here. The original ten illustrative sites remain in their own table.';
      return;
    }
    rows.forEach((item) => {
      const row = document.createElement('tr');
      const site = document.createElement('td');
      const name = document.createElement('a');
      name.href = 'analyze?job=' + encodeURIComponent(item.job_id);
      name.textContent = item.site_name;
      name.title = 'Open the marked video and review evidence';
      site.append(name);
      const meta = document.createElement('div');
      meta.className = 'module3-row-note';
      const speed = item.speed_kmh == null ? 'speed unavailable' : number(item.speed_kmh, 1) + ' km/h';
      const samples = item.vehicle_speed_samples || 0;
      meta.textContent = number(item.footpath_width_m, 2) + ' m footpath · ' + speed +
        (samples ? ' · ' + samples + ' vehicle speed samples' : '') +
        (item.synthetic ? ' · synthetic' : '');
      site.append(meta);
      row.append(site);
      textCell(row, number(item.peak_flow_per_hour, 1), item.flow_source || 'flow source unavailable');
      textCell(row, item.width_lost_m == null ? '—' : number(item.width_lost_m, 2) + ' m',
        item.width_lost_source || 'width source unavailable');
      textCell(row, number(item.displaced_per_hour, 1), 'FR-23 estimate, people/hour');
      const scoreCell = document.createElement('td');
      scoreCell.className = 'num';
      if (item.relative_exposure_0_100 == null) {
        scoreCell.textContent = 'Inputs needed';
      } else {
        const score = document.createElement('span');
        score.className = 'module3-score';
        const fraction = item.relative_exposure_0_100 / 100;
        score.style.background = fraction > 0.6 ? '#A73B19' : '#F4C5A3';
        score.style.color = fraction > 0.6 ? '#FFF' : '#16211D';
        score.textContent = number(item.relative_exposure_0_100, 1) + '/100';
        scoreCell.append(score);
        const raw = document.createElement('div');
        raw.className = 'module3-row-note';
        raw.textContent = 'Raw index ' + number(item.raw_exposure, 1);
        scoreCell.append(raw);
      }
      row.append(scoreCell);
      body.append(row);
    });
    note.textContent = 'The original ten illustrative sites above remain unchanged. This table ranks only uploaded analyses. FR-23 = pedestrian flow × (width lost ÷ path width). FR-24 weights that estimate by (speed ÷ 30)^1.5. The 0–100 score is relative to the highest uploaded site; a single site is 100 by definition. Vehicle speed samples are evidence for the speed estimate, not a separate score factor. Review detections and input sources before using the ranking.';
  }
  async function showAnalyzed(ids = savedIds()) {
    saveIds(ids);
    try {
      const response = await fetch('api/sites', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ job_ids: selectedIds }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not load the analyzed sites.');
      saveIds(selectedIds.filter((id) => !result.missing.includes(id)));
      renderAnalyzed(result.rows);
    } catch (error) {
      renderAnalyzed([]);
      note.textContent = error.message;
    }
  }

  copyButton.addEventListener('click', async () => {
    const url = new URL(window.location.href);
    url.searchParams.set('sites', selectedIds.join(','));
    try {
      await navigator.clipboard.writeText(url.toString());
      note.textContent = 'Live table link copied. Hosted analysis files expire after 24 hours.';
    } catch {
      window.prompt('Copy live table link', url.toString());
    }
  });
  window.addEventListener('message', (event) => {
    if (event.origin !== window.location.origin || event.source !== frame.contentWindow) return;
    const message = event.data;
    if (!message || typeof message !== 'object') return;
    if (message.type === 'module3:resize' && Number.isFinite(message.height)) {
      frame.style.height = Math.max(320, Math.min(12000, Math.ceil(message.height))) + 'px';
    }
    if (message.type === 'module3:analysis-complete' && /^[0-9a-f]{32}$/.test(message.jobId)) {
      const ids = savedIds().filter((id) => id !== message.jobId);
      ids.push(message.jobId);
      showAnalyzed(ids).then(() => {
        requestAnimationFrame(() => document.getElementById('module3-site-table').scrollIntoView({
          behavior: 'smooth', block: 'start',
        }));
      });
    }
  });
  const sharedIds = new URLSearchParams(window.location.search).get('sites');
  if (sharedIds) showAnalyzed(validIds(sharedIds.split(',')));
  else if (savedIds().length) showAnalyzed();
  else renderAnalyzed([]);
})();
