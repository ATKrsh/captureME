/**
 * captureME Mobile & Android Web App Engine
 * Audio-reactive canvas rendering, screen capture, and touch interactions.
 */

(function () {
  // DOM Elements
  const canvas = document.getElementById('orbCanvas');
  const ctx = canvas.getContext('2d');
  const btnScreenshot = document.getElementById('btn-screenshot');
  const btnRecord = document.getElementById('btn-record');
  const recBtnText = document.getElementById('rec-btn-text');
  const micPermBtn = document.getElementById('mic-perm-btn');
  const settingsToggleBtn = document.getElementById('settings-toggle-btn');
  const closeSettingsBtn = document.getElementById('close-settings-btn');
  const settingsDrawer = document.getElementById('settings-drawer');
  const toast = document.getElementById('toast');
  const toastMsg = document.getElementById('toast-msg');
  const flashOverlay = document.getElementById('flash-overlay');

  // Sliders & Toggles
  const sliderOpacity = document.getElementById('slider-opacity');
  const sliderGlowOp = document.getElementById('slider-glow-op');
  const sliderGlowSz = document.getElementById('slider-glow-sz');
  const sliderOrbSz = document.getElementById('slider-orb-sz');
  const toggleBreathing = document.getElementById('toggle-breathing');
  const toggleAudioReactive = document.getElementById('toggle-audio-reactive');

  // Value Display Elements
  const valOpacity = document.getElementById('val-opacity');
  const valGlowOp = document.getElementById('val-glow-op');
  const valGlowSz = document.getElementById('val-glow-sz');
  const valOrbSz = document.getElementById('val-orb-sz');

  // State Configuration
  const config = {
    opacity: 0.9,
    glow_opacity: 0.9,
    glow_size_pct: 50,
    size_percent: 50,
    breathing: true,
    audio_reactive: true,
    pos_x: 0,
    pos_y: 0,
  };

  // State Variables
  let isRecording = false;
  let mediaRecorder = null;
  let recordedChunks = [];
  let screenStream = null;

  let audioCtx = null;
  let analyser = null;
  let audioDataArray = null;
  let currentVolume = 0.0;
  let currentFrequency = 0.0;

  let breathPhase = 0.0;
  let currentGlowIntensity = 0.0;
  let currentGlowSizeFactor = 0.0;
  let currentIconScaleFactor = 0.0;

  let isDragging = false;
  let dragOffset = { x: 0, y: 0 };
  let lastTouchPos = { x: 0, y: 0 };
  let lastTouchTime = performance.now();
  let smoothAccel = 0.0;
  let lastMouseSpeed = 0.0;

  // Initialize Canvas Size
  function resizeCanvas() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    if (config.pos_x === 0 && config.pos_y === 0) {
      config.pos_x = canvas.width / 2;
      config.pos_y = canvas.height / 2;
    }
  }

  window.addEventListener('resize', resizeCanvas);
  resizeCanvas();

  // Toast Notification Helper
  function showToast(msg) {
    toastMsg.textContent = msg;
    toast.classList.remove('hidden');
    setTimeout(() => {
      toast.classList.add('hidden');
    }, 2400);
  }

  // Flash Effect Helper
  function triggerFlash() {
    flashOverlay.classList.add('active');
    setTimeout(() => {
      flashOverlay.classList.remove('active');
    }, 180);
  }

  // Web Audio API Setup
  async function initAudio() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const source = audioCtx.createMediaStreamSource(stream);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);

      audioDataArray = new Uint8Array(analyser.frequencyBinCount);
      micPermBtn.classList.add('active');
      showToast('Microphone audio spectrum enabled!');
    } catch (err) {
      console.warn('Audio permission denied or unavailable:', err);
      showToast('Audio spectrum mode inactive (using simulated breath)');
    }
  }

  micPermBtn.addEventListener('click', () => {
    if (!audioCtx) {
      initAudio();
    } else if (audioCtx.state === 'suspended') {
      audioCtx.resume();
      micPermBtn.classList.add('active');
    }
  });

  // Process Audio Spectrum Data
  function processAudio() {
    if (!analyser || !config.audio_reactive) {
      currentVolume += (0.0 - currentVolume) * 0.1;
      currentFrequency += (0.0 - currentFrequency) * 0.1;
      return;
    }

    analyser.getByteFrequencyData(audioDataArray);
    
    // 1. RMS Volume Calculation
    let sum = 0;
    for (let i = 0; i < audioDataArray.length; i++) {
      sum += audioDataArray[i] * audioDataArray[i];
    }
    let rms = Math.sqrt(sum / audioDataArray.length) / 255.0;
    let targetVol = Math.min(1.0, rms * 3.5);

    if (targetVol > currentVolume) {
      currentVolume = targetVol;
    } else {
      currentVolume += (targetVol - currentVolume) * 0.35;
    }

    // 2. Dominant Frequency Calculation
    let maxBin = 0;
    let maxVal = 0;
    for (let i = 2; i < audioDataArray.length; i++) {
      if (audioDataArray[i] > maxVal) {
        maxVal = audioDataArray[i];
        maxBin = i;
      }
    }
    let normFreq = maxVal > 10 ? Math.min(1.0, maxBin / (audioDataArray.length * 0.6)) : 0.0;
    if (normFreq > currentFrequency) {
      currentFrequency = normFreq;
    } else {
      currentFrequency += (normFreq - currentFrequency) * 0.30;
    }
  }

  // Canvas Render Loop
  function render(time) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    processAudio();

    // Breathing sine wave
    if (config.breathing) {
      breathPhase += 0.04;
    }
    const sineVal = (Math.sin(breathPhase) + 1.0) / 2.0;

    let targetGlowIntensity, targetGlowSize, targetIconScale;
    if (config.breathing) {
      targetGlowIntensity = 0.25 + sineVal * 0.25 + currentVolume * 0.85;
      targetGlowSize = 0.20 + sineVal * 0.15 + currentFrequency * 0.80;
      targetIconScale = sineVal * 2.0 + smoothAccel * 18.0;
    } else {
      targetGlowIntensity = 0.2 + currentVolume * 0.8;
      targetGlowSize = 0.2 + currentFrequency * 0.8;
      targetIconScale = smoothAccel * 12.0;
    }

    currentGlowIntensity += (targetGlowIntensity - currentGlowIntensity) * 0.35;
    currentGlowSizeFactor += (targetGlowSize - currentGlowSizeFactor) * 0.35;
    currentIconScaleFactor += (targetIconScale - currentIconScaleFactor) * 0.25;

    // Dimensions
    const baseSize = 40 + 120 * (config.size_percent / 100.0);
    const dSize = baseSize + currentIconScaleFactor;
    const cx = config.pos_x;
    const cy = config.pos_y;

    const intensity = Math.min(1.0, Math.max(0.0, currentGlowIntensity));
    const glowUserOp = config.glow_opacity;
    const glowAlpha = Math.min(0.95, (0.2 + 0.75 * intensity) * glowUserOp);

    const freqFactor = Math.min(1.0, Math.max(0.0, currentGlowSizeFactor));
    const glowSzScale = config.glow_size_pct / 100.0;
    const glowBaseExt = 5.0 + 45.0 * glowSzScale;
    const glowAudioExt = freqFactor * (5.0 + 65.0 * glowSzScale);
    const glowRadius = dSize / 2.0 + glowBaseExt + glowAudioExt;

    // Color definitions
    const mainHue = isRecording ? '355, 100%, 58%' : '190, 100%, 50%';

    // 1. Outer Ambient Aura
    const outerRadius = glowRadius + 18.0;
    const gradOuter = ctx.createRadialGradient(cx, cy, 0, cx, cy, outerRadius);
    gradOuter.addColorStop(0, `hsla(${mainHue}, ${glowAlpha * 0.45})`);
    gradOuter.addColorStop(0.6, `hsla(${mainHue}, ${glowAlpha * 0.15})`);
    gradOuter.addColorStop(1, `hsla(${mainHue}, 0)`);

    ctx.fillStyle = gradOuter;
    ctx.beginPath();
    ctx.arc(cx, cy, outerRadius, 0, Math.PI * 2);
    ctx.fill();

    // 2. Inner Core Glow
    const gradInner = ctx.createRadialGradient(cx, cy, 0, cx, cy, glowRadius);
    gradInner.addColorStop(0, `hsla(${mainHue}, ${glowAlpha})`);
    gradInner.addColorStop(0.65, `hsla(${mainHue}, ${glowAlpha * 0.45})`);
    gradInner.addColorStop(1, `hsla(${mainHue}, 0)`);

    ctx.fillStyle = gradInner;
    ctx.beginPath();
    ctx.arc(cx, cy, glowRadius, 0, Math.PI * 2);
    ctx.fill();

    // 3. Main Card Body
    const bodyAlpha = 0.86 * config.opacity;
    ctx.fillStyle = `rgba(20, 24, 34, ${bodyAlpha})`;
    ctx.strokeStyle = `rgba(255, 255, 255, ${(0.2 + 0.7 * intensity) * config.opacity})`;
    ctx.lineWidth = 2.0;

    ctx.beginPath();
    ctx.arc(cx, cy, dSize / 2.0, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();

    // 4. Center Trigger Button
    const chkRadius = dSize * 0.18;
    ctx.fillStyle = isRecording
      ? `rgba(255, 40, 40, ${config.opacity})`
      : `rgba(35, 42, 58, ${0.8 * config.opacity})`;
    ctx.strokeStyle = isRecording
      ? `rgba(255, 180, 180, ${config.opacity})`
      : `rgba(0, 210, 255, ${0.7 * config.opacity})`;
    ctx.lineWidth = 2.0;

    ctx.beginPath();
    ctx.arc(cx, cy, chkRadius, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();

    if (isRecording) {
      const sqW = chkRadius * 0.8;
      ctx.fillStyle = `rgba(255, 255, 255, ${config.opacity})`;
      ctx.fillRect(cx - sqW / 2, cy - sqW / 2, sqW, sqW);
    } else {
      const dotR = chkRadius * 0.35;
      ctx.fillStyle = `rgba(0, 210, 255, ${(0.6 + 0.4 * intensity) * config.opacity})`;
      ctx.beginPath();
      ctx.arc(cx, cy, dotR, 0, Math.PI * 2);
      ctx.fill();
    }

    requestAnimationFrame(render);
  }

  requestAnimationFrame(render);

  // Touch & Pointer Interaction
  function getEventPos(e) {
    if (e.touches && e.touches.length > 0) {
      return { x: e.touches[0].clientX, y: e.touches[0].clientY };
    }
    return { x: e.clientX, y: e.clientY };
  }

  function handleStart(e) {
    const pos = getEventPos(e);
    const baseSize = 40 + 120 * (config.size_percent / 100.0);
    const dist = Math.hypot(pos.x - config.pos_x, pos.y - config.pos_y);

    if (dist <= baseSize + 30) {
      isDragging = true;
      dragOffset = { x: pos.x - config.pos_x, y: pos.y - config.pos_y };
      lastTouchPos = pos;
      lastTouchTime = performance.now();
    }
  }

  function handleMove(e) {
    if (!isDragging) return;
    const pos = getEventPos(e);
    const now = performance.now();
    const dt = Math.max(1, now - lastTouchTime) / 1000.0;

    const dx = pos.x - lastTouchPos.x;
    const dy = pos.y - lastTouchPos.y;
    const speed = Math.hypot(dx, dy) / dt;
    const accel = Math.abs(speed - lastMouseSpeed) / dt;
    const normAccel = Math.min(1.0, accel / 10000.0);

    smoothAccel += (normAccel - smoothAccel) * 0.2;
    lastMouseSpeed = speed;
    lastTouchPos = pos;
    lastTouchTime = now;

    config.pos_x = Math.max(50, Math.min(canvas.width - 50, pos.x - dragOffset.x));
    config.pos_y = Math.max(50, Math.min(canvas.height - 50, pos.y - dragOffset.y));
  }

  function handleEnd(e) {
    if (!isDragging) return;
    isDragging = false;
    smoothAccel = 0.0;
  }

  canvas.addEventListener('mousedown', handleStart);
  canvas.addEventListener('mousemove', handleMove);
  canvas.addEventListener('mouseup', handleEnd);

  canvas.addEventListener('touchstart', handleStart, { passive: true });
  canvas.addEventListener('touchmove', handleMove, { passive: true });
  canvas.addEventListener('touchend', handleEnd, { passive: true });

  // Handle Canvas Click (Tap on Orb)
  canvas.addEventListener('click', (e) => {
    const pos = getEventPos(e);
    const baseSize = 40 + 120 * (config.size_percent / 100.0);
    const chkRadius = baseSize * 0.18;
    const dist = Math.hypot(pos.x - config.pos_x, pos.y - config.pos_y);

    if (dist <= chkRadius * 1.6) {
      toggleRecording();
    } else if (dist <= baseSize) {
      takeScreenshot();
    }
  });

  // Screen Recording Logic
  async function toggleRecording() {
    if (!isRecording) {
      try {
        if (!screenStream || !screenStream.active) {
          screenStream = await navigator.mediaDevices.getDisplayMedia({
            video: { mediaSource: 'screen' },
            audio: true,
          });
        }

        recordedChunks = [];
        mediaRecorder = new MediaRecorder(screenStream, { mimeType: 'video/webm' });
        mediaRecorder.ondataavailable = (event) => {
          if (event.data.size > 0) recordedChunks.push(event.data);
        };
        mediaRecorder.onstop = saveRecording;
        mediaRecorder.start(1000);

        isRecording = true;
        btnRecord.classList.add('recording');
        recBtnText.textContent = 'Stop Recording';
        showToast('Screen recording started!');
      } catch (err) {
        console.error('Screen recording failed:', err);
        showToast('Screen capture permission cancelled or unsupported');
      }
    } else {
      if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop();
      }
      isRecording = false;
      btnRecord.classList.remove('recording');
      recBtnText.textContent = 'Record Screen';
    }
  }

  function saveRecording() {
    const blob = new Blob(recordedChunks, { type: 'video/webm' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.style.display = 'none';
    a.href = url;
    const timestamp = new Date().toISOString().replace(/[-:T.]/g, '').slice(0, 15);
    a.download = `captureME_recording_${timestamp}.webm`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }, 100);
    showToast('Video recording saved to downloads!');
  }

  // Screenshot Logic
  async function takeScreenshot() {
    triggerFlash();
    try {
      if (!screenStream || !screenStream.active) {
        screenStream = await navigator.mediaDevices.getDisplayMedia({
          video: { mediaSource: 'screen' },
        });
      }

      const video = document.createElement('video');
      video.srcObject = screenStream;
      await video.play();

      const tempCanvas = document.createElement('canvas');
      tempCanvas.width = video.videoWidth || canvas.width;
      tempCanvas.height = video.videoHeight || canvas.height;
      const tCtx = tempCanvas.getContext('2d');
      tCtx.drawImage(video, 0, 0, tempCanvas.width, tempCanvas.height);

      const timestamp = new Date().toISOString().replace(/[-:T.]/g, '').slice(0, 15);
      const a = document.createElement('a');
      a.href = tempCanvas.toDataURL('image/png');
      a.download = `captureME_screenshot_${timestamp}.png`;
      a.click();
      showToast('Screenshot saved!');
    } catch (err) {
      console.warn('Screenshot capture fallback:', err);
      // Fallback: capture canvas frame itself
      const timestamp = new Date().toISOString().replace(/[-:T.]/g, '').slice(0, 15);
      const a = document.createElement('a');
      a.href = canvas.toDataURL('image/png');
      a.download = `captureME_orb_${timestamp}.png`;
      a.click();
      showToast('Orb screenshot saved!');
    }
  }

  btnScreenshot.addEventListener('click', takeScreenshot);
  btnRecord.addEventListener('click', toggleRecording);

  // Settings Drawer Toggle
  settingsToggleBtn.addEventListener('click', () => {
    settingsDrawer.classList.toggle('hidden');
  });

  closeSettingsBtn.addEventListener('click', () => {
    settingsDrawer.classList.add('hidden');
  });

  // Slider Event Listeners
  sliderOpacity.addEventListener('input', (e) => {
    config.opacity = e.target.value / 100.0;
    valOpacity.textContent = `${e.target.value}%`;
  });

  sliderGlowOp.addEventListener('input', (e) => {
    config.glow_opacity = e.target.value / 100.0;
    valGlowOp.textContent = `${e.target.value}%`;
  });

  sliderGlowSz.addEventListener('input', (e) => {
    config.glow_size_pct = parseInt(e.target.value, 10);
    valGlowSz.textContent = `${e.target.value}%`;
  });

  sliderOrbSz.addEventListener('input', (e) => {
    config.size_percent = parseInt(e.target.value, 10);
    valOrbSz.textContent = `${e.target.value}%`;
  });

  toggleBreathing.addEventListener('change', (e) => {
    config.breathing = e.target.checked;
  });

  toggleAudioReactive.addEventListener('change', (e) => {
    config.audio_reactive = e.target.checked;
  });
})();
