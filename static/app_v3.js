(function () {
  const form = document.getElementById('capture-form');
  const urlInput = document.getElementById('tweet-url');
  const submitBtn = document.getElementById('submit-btn');
  const btnText = submitBtn.querySelector('.btn-text');
  const spinner = document.getElementById('btn-spinner');

  const batchTargetSelect = document.getElementById('batch-target-select');
  const countSetting = document.getElementById('count-setting');
  const dateSetting = document.getElementById('date-setting');
  const hoursSetting = document.getElementById('hours-setting');

  const countInput = document.getElementById('count-input');
  const dateInput = document.getElementById('date-input');
  const hoursInput = document.getElementById('hours-input');
  const themeSelect = document.getElementById('theme-select');
  const scaleSelect = document.getElementById('scale-select');
  const zipInput = document.getElementById('zip-input');
  const jsonInput = document.getElementById('json-input');
  const headedToggle = document.getElementById('headed-toggle');
  const cookieInput = document.getElementById('cookie-input');
  const authStatusBar = document.getElementById('auth-status-bar');
  const authStatusText = document.getElementById('auth-status-text');
  const authDot = document.getElementById('auth-dot');
  const authPanel = document.getElementById('auth-panel');

  const resultContainer = document.getElementById('result-container');
  const resultTitle = document.getElementById('result-title');
  const resultSummary = document.getElementById('result-summary');
  const resultActions = document.getElementById('result-actions');
  const gallery = document.getElementById('image-gallery');
  const formStatus = document.getElementById('form-status');

  function setStatus(message, type) {
    formStatus.className = 'status';
    if (type) formStatus.classList.add(type);
    formStatus.textContent = message || '';
  }

  function setLoading(loading) {
    submitBtn.disabled = loading;
    btnText.style.display = loading ? 'none' : 'inline-block';
    spinner.style.display = loading ? 'inline-block' : 'none';
  }

  function updateBatchMode(mode) {
    countSetting.classList.toggle('is-hidden', mode !== 'count');
    dateSetting.classList.toggle('is-hidden', mode !== 'date');
    hoursSetting.classList.toggle('is-hidden', mode !== 'hours');
  }

  function toggleAuthPanel(forceExpand) {
    const expanded = typeof forceExpand === 'boolean'
      ? forceExpand
      : authStatusBar.getAttribute('aria-expanded') !== 'true';
    authStatusBar.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    authPanel.classList.toggle('is-hidden', !expanded);
  }

  function isAuthPanelOpen() {
    return authStatusBar.getAttribute('aria-expanded') === 'true';
  }

  async function refreshAuthStatus() {
    try {
      const resp = await fetch('/api/auth/status', { method: 'GET' });
      const data = await resp.json();
      if (data && data.logged_in) {
        authStatusText.textContent = 'Logged in';
        authDot.classList.remove('bad');
        authDot.classList.add('ok');
      } else if (data && data.has_auth_file) {
        authStatusText.textContent = 'Auth file invalid';
        authDot.classList.remove('ok');
        authDot.classList.add('bad');
      } else {
        authStatusText.textContent = 'Not logged in';
        authDot.classList.remove('ok');
        authDot.classList.add('bad');
      }
    } catch (_) {
      authStatusText.textContent = 'Login status unavailable';
      authDot.classList.remove('ok');
      authDot.classList.add('bad');
    }
  }

  function getSelectedValues(containerId) {
    return Array.from(document.querySelectorAll(`#${containerId} input:checked`)).map((cb) => cb.value);
  }

  function clearResult() {
    resultTitle.textContent = 'Result';
    resultSummary.textContent = '';
    resultActions.innerHTML = '';
    gallery.innerHTML = '';
    resultContainer.classList.add('is-hidden');
  }

  function ensureValidFilters() {
    const groups = ['chip-types', 'chip-media', 'chip-links'];
    for (const groupId of groups) {
      if (getSelectedValues(groupId).length === 0) {
        throw new Error('Each advanced filter group must keep at least one active option.');
      }
    }
  }

  function collectPayload() {
    const url = urlInput.value.trim();
    if (!url) throw new Error('Please provide a valid X URL.');

    ensureValidFilters();

    const payload = {
      url,
      theme: themeSelect.value,
      scale_factor: Number.parseFloat(scaleSelect.value),
      img_format: 'png',
      padding: 0,
      bg_color: 'transparent',
      zip_output: zipInput.value === 'true',
      export_json: jsonInput.value === 'true',
      headed: !!headedToggle.checked,
      cookie_string: (cookieInput.value || '').trim() || null,
      since_date: null,
      since_hours: null,
      count: Number.parseInt(countInput.value, 10),
      sys_types: getSelectedValues('chip-types'),
      sys_media: getSelectedValues('chip-media'),
      sys_links: getSelectedValues('chip-links')
    };

    const mode = batchTargetSelect.value;
    if (mode === 'date') {
      if (!dateInput.value) throw new Error('Please select a since date.');
      payload.count = 500;
      payload.since_date = dateInput.value;
    } else if (mode === 'hours') {
      const hours = Number.parseInt(hoursInput.value, 10);
      if (!Number.isFinite(hours) || hours <= 0) throw new Error('Hours must be a positive integer.');
      payload.count = 500;
      payload.since_hours = hours;
    } else {
      const count = Number.parseInt(countInput.value, 10);
      if (!Number.isFinite(count) || count <= 0) throw new Error('Count must be a positive integer.');
      payload.count = count;
    }

    return payload;
  }

  function makeButton(label, onClick) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn';
    btn.textContent = label;
    btn.addEventListener('click', onClick);
    return btn;
  }


  function renderZipResult(data) {
    resultTitle.textContent = 'Batch archive ready';
    resultSummary.textContent = `Archive: ${data.filename}`;

    const downloadBtn = makeButton('Download Zip', () => {
      window.location.href = data.url;
    });

    resultActions.appendChild(downloadBtn);
    resultContainer.classList.remove('is-hidden');
  }

  function renderImageResult(data) {
    const images = Array.isArray(data.images) ? data.images : [];
    const timestamp = Date.now();

    resultTitle.textContent = 'Batch gallery';
    resultSummary.textContent = `Generated ${images.length} image(s).`;
    resultContainer.classList.remove('is-hidden');

    const total = images.length;
    if (total === 0) return Promise.resolve();

    let shown = 0;
    const chunkSize = 1;

    const appendCard = (imgObj, index) => {
      const srcUrl = typeof imgObj === 'string' ? imgObj : imgObj.url;
      const filename = typeof imgObj === 'string' ? 'image' : (imgObj.filename || 'image');

      const card = document.createElement('article');
      card.className = 'gallery-item';
      card.style.animationDelay = `${Math.min(index * 20, 260)}ms`;

      const img = document.createElement('img');
      img.loading = 'lazy';
      img.alt = filename;
      img.src = `${srcUrl}${srcUrl.includes('?') ? '&' : '?'}t=${timestamp}`;

      const caption = document.createElement('div');
      caption.className = 'gallery-caption';
      caption.textContent = filename;

      card.appendChild(img);
      card.appendChild(caption);
      gallery.appendChild(card);
    };

    const tick = () => new Promise((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(resolve));
    });

    return (async () => {
      for (let i = 0; i < total; i += 1) {
        appendCard(images[i], i);
        shown += 1;
        resultSummary.textContent = `Streaming ${shown}/${total} image(s)...`;

        if (shown % chunkSize === 0) {
          await tick();
        }
      }
      resultSummary.textContent = `Generated ${total} image(s).`;
    })();
  }

  async function submitCapture(event) {
    event.preventDefault();
    clearResult();

    let payload;
    try {
      payload = collectPayload();
    } catch (error) {
      setStatus(error.message, 'warn');
      return;
    }

    setLoading(true);
    setStatus('Capturing tweets in batch mode...', null);

    try {
      const response = await fetch('/api/screenshot/batch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      const data = await response.json();
      if (!response.ok) {
        const detail = data && data.detail ? data.detail : 'Batch capture failed.';
        throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
      }

      if (data.is_zip) {
        renderZipResult(data);
      } else {
        await renderImageResult(data);
      }


      if (data.is_zip && data.url) {
        // Trigger zip download
        setTimeout(() => {
          window.location.href = data.url;
        }, 120);
      }

      await refreshAuthStatus();

      setStatus('Capture completed successfully.', 'ok');
      resultContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) {
      setStatus(error.message || 'Unexpected error.', 'err');
    } finally {
      setLoading(false);
    }
  }

  batchTargetSelect.addEventListener('change', () => updateBatchMode(batchTargetSelect.value));
  authStatusBar.addEventListener('click', (e) => {
    e.stopPropagation();
    toggleAuthPanel();
  });
  authPanel.addEventListener('click', (e) => e.stopPropagation());
  document.addEventListener('click', () => {
    if (isAuthPanelOpen()) toggleAuthPanel(false);
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && isAuthPanelOpen()) toggleAuthPanel(false);
  });
  form.addEventListener('submit', submitCapture);

  updateBatchMode(batchTargetSelect.value);
  toggleAuthPanel(false);
  refreshAuthStatus();
  clearResult();
})();
