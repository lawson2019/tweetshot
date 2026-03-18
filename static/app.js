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

  const resultContainer = document.getElementById('result-container');
  const resultTitle = document.getElementById('result-title');
  const resultSummary = document.getElementById('result-summary');
  const resultActions = document.getElementById('result-actions');
  const gallery = document.getElementById('image-gallery');
  const formStatus = document.getElementById('form-status');

  function setStatus(message, type) {
    formStatus.className = 'status';
    if (type) {
      formStatus.classList.add(type);
    }
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
      const selected = getSelectedValues(groupId);
      if (selected.length === 0) {
        throw new Error('Each advanced filter group must keep at least one active option.');
      }
    }
  }

  function collectPayload() {
    const url = urlInput.value.trim();
    if (!url) {
      throw new Error('Please provide a valid X URL.');
    }

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
      since_date: null,
      since_hours: null,
      count: Number.parseInt(countInput.value, 10),
      sys_types: getSelectedValues('chip-types'),
      sys_media: getSelectedValues('chip-media'),
      sys_links: getSelectedValues('chip-links')
    };

    const mode = batchTargetSelect.value;
    if (mode === 'date') {
      if (!dateInput.value) {
        throw new Error('Please select a since date.');
      }
      payload.count = 500;
      payload.since_date = dateInput.value;
    } else if (mode === 'hours') {
      const hours = Number.parseInt(hoursInput.value, 10);
      if (!Number.isFinite(hours) || hours <= 0) {
        throw new Error('Hours must be a positive integer.');
      }
      payload.count = 500;
      payload.since_hours = hours;
    } else {
      const count = Number.parseInt(countInput.value, 10);
      if (!Number.isFinite(count) || count <= 0) {
        throw new Error('Count must be a positive integer.');
      }
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

  function autoDownloadMetadata(metadata, jobId) {
    const blob = new Blob([JSON.stringify(metadata, null, 2)], { type: 'application/json' });
    const blobUrl = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = `${jobId || 'batch'}_metadata.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(blobUrl);
  }

  function renderZipResult(data) {
    resultTitle.textContent = 'Batch archive ready';
    resultSummary.textContent = `Archive: ${data.filename}`;

    const downloadBtn = makeButton('Download Zip', () => {
      window.location.href = data.url;
    });

    resultActions.appendChild(downloadBtn);
    resultContainer.classList.remove('is-hidden');

    window.location.href = data.url;
  }

  function renderImageResult(data) {
    const images = Array.isArray(data.images) ? data.images : [];
    const timestamp = Date.now();

    resultTitle.textContent = 'Batch gallery';
    resultSummary.textContent = `Generated ${images.length} image(s).`;

    for (const imgObj of images) {
      const srcUrl = typeof imgObj === 'string' ? imgObj : imgObj.url;
      const filename = typeof imgObj === 'string' ? 'image' : (imgObj.filename || 'image');

      const card = document.createElement('article');
      card.className = 'gallery-item';

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
    }

    resultContainer.classList.remove('is-hidden');
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
        renderImageResult(data);
      }

      if (payload.export_json && Array.isArray(data.metadata) && data.metadata.length > 0) {
        autoDownloadMetadata(data.metadata, data.id);
      }

      setStatus('Capture completed successfully.', 'ok');
      resultContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) {
      setStatus(error.message || 'Unexpected error.', 'err');
    } finally {
      setLoading(false);
    }
  }

  batchTargetSelect.addEventListener('change', () => updateBatchMode(batchTargetSelect.value));
  form.addEventListener('submit', submitCapture);

  updateBatchMode(batchTargetSelect.value);
  clearResult();
})();
