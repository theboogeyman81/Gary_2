// Gary laptop companion — UI logic
// Python calls functions on window.gary via pywebview's evaluate_js().
// You can also call them from the browser console while developing.
window.gary = {};

// --- Helpers -----------------------------------------------------------------

function overlay() {
  return document.querySelector('.g-overlay');
}

// Escapes special characters before inserting agent/user text into innerHTML.
function escapeHTML(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Remembers the last card Python sent so the arc can re-open it.
let _lastCard = null;

// True while the card is displayed — state transitions must not replace it.
let _cardVisible = false;
let _autoDismissTimer = null;

// Auto-clear timer for the annotation SVG layer.
let _annotationTimer = null;

function _clearAutoDismiss() {
  if (_autoDismissTimer) { clearTimeout(_autoDismissTimer); _autoDismissTimer = null; }
}

// --- Markup builders ---------------------------------------------------------

// Builds an HTML string for the resting indicator (quarter-circle arc).
// The arc path is a quarter-circle whose centre is the bottom-right corner:
//   start at (0, 200) — bottom-left of the 200×200 box
//   sweep to (200, 0) — top-right of the box
// gary.css positions .g-indicator at right:0; bottom:0, so the arc's centre
// lands exactly in the screen corner.
function indicatorHTML() {
  return `
<div class="g-indicator">
  <div class="g-hint g-eyebrow">tap to open</div>
  <svg class="g-arc" viewBox="0 0 200 200" role="button" tabindex="0" aria-label="Open Gary">
    <path class="g-arc-base" d="M0 200 A200 200 0 0 1 200 0" />
  </svg>
</div>`.trim();
}

// Builds the listening-state markup.
// The base arc dims to 18% (via .g-listen .g-arc-base rule in gary.css) and a
// comet of light travels along the arc path indefinitely.
function listeningHTML() {
  return `
<div class="g-listen">
  <div class="g-status-label">
    <span class="g-eyebrow">listening<span class="g-dot"></span></span>
  </div>
  <svg class="g-arc" viewBox="0 0 200 200" aria-label="Listening">
    <path class="g-arc-base" d="M0 200 A200 200 0 0 1 200 0" />
    <path class="g-arc-comet" d="M0 200 A200 200 0 0 1 200 0" />
  </svg>
</div>`.trim();
}

// Builds the thinking-state markup.
// Three concentric arcs (radii 200 / 150 / 100) breathe with staggered delays
// so the pulse appears to ripple outward from the corner.
function thinkingHTML() {
  return `
<div class="g-think">
  <svg class="g-arc" viewBox="0 0 200 200" aria-label="Thinking">
    <path class="g-arc-base" d="M0 200 A200 200 0 0 1 200 0" />
    <path class="g-think-arc"    d="M0 200 A200 200 0 0 1 200 0" />
    <path class="g-think-arc a2" d="M50 200 A150 150 0 0 1 200 50" />
    <path class="g-think-arc a3" d="M100 200 A100 100 0 0 1 200 100" />
  </svg>
</div>`.trim();
}

// Builds the speaking-state markup.
// Faster ripple arcs (1.2s) than thinking (2.6s) — Gary is talking.
function speakingHTML() {
  return `
<div class="g-speak">
  <div class="g-status-label">
    <span class="g-eyebrow">speaking<span class="g-dot g-dot--speak"></span></span>
  </div>
  <svg class="g-arc" viewBox="0 0 200 200" aria-label="Speaking">
    <path class="g-arc-base" d="M0 200 A200 200 0 0 1 200 0" />
    <path class="g-speak-arc"    d="M0 200 A200 200 0 0 1 200 0" />
    <path class="g-speak-arc a2" d="M50 200 A150 150 0 0 1 200 50" />
    <path class="g-speak-arc a3" d="M100 200 A100 100 0 0 1 200 100" />
  </svg>
</div>`.trim();
}

// Builds toast markup. The check circle + SVG checkmark are from gary.css's
// .g-toast-check spec. is-in starts the entrance animation immediately.
function toastHTML(message) {
  return `
<div class="g-toast is-in">
  <div class="g-toast-check">
    <svg viewBox="0 0 9 9"><polyline points="1.5,4.5 3.5,6.5 7.5,2.5" /></svg>
  </div>
  <span>${escapeHTML(message)}</span>
</div>`.trim();
}

// Builds the permission modal markup.
// Deny is a ghost button; Allow is the accent pill — same hierarchy as gary.css spec.
function modalHTML(title, description) {
  return `
<div class="g-modal g-rise g-fade">
  <div class="g-eyebrow">Permission request</div>
  <h3>${escapeHTML(title)}</h3>
  <p>${escapeHTML(description)}</p>
  <div class="g-modal-foot">
    <button class="g-ghost" id="gary-deny">Deny</button>
    <button class="g-pill"  id="gary-allow">Allow</button>
  </div>
</div>`.trim();
}

// Builds the card markup for a given title and body text.
// data-h triggers the fixed-height rule in gary.css (.g-card[data-h]{height:288px}).
// g-rise + g-fade play together on enter: slide up 20px while fading in (0.42s).
function cardHTML(title, text) {
  return `
<div class="g-card g-rise g-fade" data-h>
  <button class="g-card-x" aria-label="Close">&#x2715;</button>
  <div class="g-card-title">${escapeHTML(title)}</div>
  <div class="g-card-body">${escapeHTML(text)}</div>
  <div class="g-card-foot">
    <button class="g-pill" id="gary-copy">Copy</button>
  </div>
</div>`.trim();
}

// --- Public API --------------------------------------------------------------

// gary.renderIndicator()
// Clears the overlay and shows the resting arc in the bottom-right corner.
// Called by Python when Gary is idle, and by the card's close button.
window.gary.renderIndicator = function () {
  overlay().innerHTML = indicatorHTML();

  const arc = overlay().querySelector('.g-arc');

  function openLastCard() {
    if (_lastCard) {
      window.gary.renderCard(_lastCard.title, _lastCard.text);
    }
  }

  // Mouse click: blur first so the browser doesn't draw a focus ring around
  // the whole SVG element, then open the card.
  arc.addEventListener('click', function () {
    this.blur();
    openLastCard();
  });
  arc.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      openLastCard();
    }
  });
};

// gary.queuePopup(title, text)
// Auto-shows the card immediately when show_popup arrives on the bus.
window.gary.queuePopup = function (title, text) {
  _lastCard = { title, text };
  window.gary.renderCard(title, text);
};

// gary.showSpaceHold(progress)
// Fills the arc proportionally (0.0–1.0) while the user holds spacebar.
// At progress=0 the arc is its normal accent colour; as it fills it brightens.
// Python calls this every 100ms during the 5s hold. Release before 1.0
// resets to idle.
window.gary.showSpaceHold = function (progress) {
  var pct = Math.max(0, Math.min(1, progress));

  // First call: inject the hold element if it's not already there.
  var el = overlay().querySelector('.g-hold');
  if (!el) {
    overlay().innerHTML = `
<div class="g-hold">
  <svg class="g-arc" viewBox="0 0 200 200" aria-hidden="true">
    <path class="g-arc-base" d="M0 200 A200 200 0 0 1 200 0" />
    <path class="g-arc-fill" d="M0 200 A200 200 0 0 1 200 0" />
  </svg>
</div>`.trim();
    el = overlay().querySelector('.g-hold');
  }

  // Arc quarter-circle total path length ≈ π/2 × 200 ≈ 314.16
  var totalLen = 314.16;
  var fill = overlay().querySelector('.g-arc-fill');
  if (fill) {
    fill.style.strokeDasharray  = (pct * totalLen) + ' ' + totalLen;
    fill.style.strokeDashoffset = '0';
  }
};

// gary.showSpeaking()
// Switches the overlay to the speaking arc state — a faster ripple than
// "thinking", indicating Gary is talking.
window.gary.showSpeaking = function () {
  if (_cardVisible) return;
  overlay().innerHTML = speakingHTML();
};

// gary.showSpaceHold(progress)
// Called repeatedly by the spacebar-hold loop in main_pywebview.py (0.0 → 1.0).
// Draws a progress arc over the indicator — no state replacement, just a second
// SVG path that fills in. Arc total length for radius 200 quarter-circle ≈ 314 px.
window.gary.showSpaceHold = function (progress) {
  const ARC_LEN = 314;

  // Ensure the indicator is present (first call sets it up).
  if (!overlay().querySelector('.g-indicator')) {
    window.gary.renderIndicator();
  }

  let fill = overlay().querySelector('.g-arc-fill');
  if (!fill) {
    const svg = overlay().querySelector('.g-arc');
    fill = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    fill.classList.add('g-arc-fill');
    fill.setAttribute('d', 'M0 200 A200 200 0 0 1 200 0');
    fill.setAttribute('fill', 'none');
    fill.setAttribute('stroke', 'var(--g-accent)');
    fill.setAttribute('stroke-width', '2.5');
    fill.setAttribute('stroke-linecap', 'round');
    svg.appendChild(fill);
  }

  const filled = Math.max(0, progress) * ARC_LEN;
  fill.style.strokeDasharray = `${filled} ${ARC_LEN}`;
};

// gary.showListening()
// Switches the overlay to the listening arc state.
// Python calls this when the microphone opens. No interaction — Python drives
// the transition out by calling queuePopup() or renderIndicator().
window.gary.showListening = function () {
  if (_cardVisible) return;
  overlay().innerHTML = listeningHTML();
};

// gary.showThinking()
// Switches the overlay to the thinking arc state.
// Python calls this while the agent is processing. Same lifecycle as showListening.
window.gary.showThinking = function () {
  if (_cardVisible) return;
  overlay().innerHTML = thinkingHTML();
};

// gary.showToast(message, duration)
// Appends a self-dismissing toast over the current state (does not replace it).
// duration defaults to 3000 ms. Python calls this for lightweight confirmations
// like "Screenshot taken" or "Copied to clipboard".
window.gary.showToast = function (message, duration) {
  duration = duration || 3000;

  const tmp = document.createElement('div');
  tmp.innerHTML = toastHTML(message);
  const toast = tmp.firstChild;
  overlay().appendChild(toast);

  setTimeout(function () {
    toast.classList.replace('is-in', 'is-out');
    // 300 ms > the 260 ms out animation so the element is gone before removal.
    setTimeout(function () {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 300);
  }, duration);
};

// gary.showPermission(title, description)
// Replaces the overlay with the permission modal. Allow/Deny route through the
// Python bridge so the agent gets the answer back on the bus.
window.gary.showPermission = function (title, description) {
  overlay().innerHTML = modalHTML(title, description);

  overlay().querySelector('#gary-allow').addEventListener('click', function () {
    if (window.pywebview) {
      pywebview.api.permission_response(true);
    }
    window.gary.renderIndicator();
  });

  overlay().querySelector('#gary-deny').addEventListener('click', function () {
    if (window.pywebview) {
      pywebview.api.permission_response(false);
    }
    window.gary.renderIndicator();
  });
};

// gary.renderCard(title, text)
// Replaces the overlay with a fixed-height card showing title + scrollable text.
// Auto-dismisses after 10 seconds.
window.gary.renderCard = function (title, text) {
  _lastCard = { title, text };
  _cardVisible = true;
  _clearAutoDismiss();
  overlay().innerHTML = cardHTML(title, text);

  // Auto-dismiss after 10 s — returns to the idle indicator.
  _autoDismissTimer = setTimeout(function () {
    _cardVisible = false;
    _autoDismissTimer = null;
    window.gary.renderIndicator();
  }, 10000);

  const card = overlay().querySelector('.g-card');

  // Close → cancel the timer and go back to idle indicator.
  card.querySelector('.g-card-x').addEventListener('click', function () {
    _cardVisible = false;
    _clearAutoDismiss();
    window.gary.renderIndicator();
  });

  // Copy → always go through the Python bridge; navigator.clipboard is
  // unreliable inside a webview (per pywebview docs).
  card.querySelector('#gary-copy').addEventListener('click', function () {
    const btn = this;

    if (window.pywebview) {
      pywebview.api.copy_to_clipboard(text);
    } else {
      // Dev fallback: running in a plain browser tab.
      navigator.clipboard.writeText(text).catch(() => {});
    }

    // Visual confirmation: pill switches to its "done" ghost style for 2 s.
    btn.textContent = 'Copied';
    btn.classList.add('is-done');
    setTimeout(function () {
      btn.textContent = 'Copy';
      btn.classList.remove('is-done');
    }, 2000);
  });
};

// gary.connectMic(url, token)
// Joins the LiveKit room as a mic-only participant so the voice agent can hear
// the user. Called by Python right after creating the room on spacebar hold.
window.gary.connectMic = async function (url, token) {
  if (window._garyRoom) {
    await window._garyRoom.disconnect();
    window._garyRoom = null;
  }
  try {
    const room = new LivekitClient.Room();

    // Attach any remote audio track (Gary's TTS) to a real <audio> element and play it.
    function attachAudio(track) {
      const el = track.attach();
      el.setAttribute('autoplay', '');
      document.body.appendChild(el);
      el.play().catch(e => console.warn('[gary] audio play blocked:', e));
    }

    // Handle tracks that arrive after we join.
    room.on(LivekitClient.RoomEvent.TrackSubscribed, function (track) {
      if (track.kind === 'audio') attachAudio(track);
    });

    await room.connect(url, token);

    // Handle tracks that were already published before we joined.
    room.remoteParticipants.forEach(function (participant) {
      participant.trackPublications.forEach(function (pub) {
        if (pub.track && pub.track.kind === 'audio') attachAudio(pub.track);
      });
    });

    await room.localParticipant.setMicrophoneEnabled(true);
    window._garyRoom = room;
    console.log('[gary] mic connected to room:', room.name);
  } catch (err) {
    console.error('[gary] connectMic failed:', err);
  }
};

// gary.disconnectMic()
// Leaves the LiveKit room and releases the microphone. Called by Python when
// gary_idle fires on the bus (agent finished speaking).
window.gary.disconnectMic = async function () {
  if (window._garyRoom) {
    await window._garyRoom.disconnect();
    window._garyRoom = null;
    console.log('[gary] mic disconnected');
  }
};

// Builds a full-viewport SVG with one annotation group (outer ring + inner dot +
// label) per point. Coordinates are pixel-precise using window dimensions so
// normalized 0–1 floats map correctly without SVG viewBox distortion.
// Builds the annotation layer as percentage-positioned divs so Gemini's
// normalised 0–1 coords map directly to CSS left/top — no pixel maths needed.
function annotationsHTML(points) {
  var pins = points.map(function (p) {
    var left = (p.x * 100).toFixed(3) + '%';
    var top  = (p.y * 100).toFixed(3) + '%';
    var label = escapeHTML(p.label || '');
    return (
      '<div class="g-annotation-point" style="left:' + left + ';top:' + top + '">' +
        '<div class="g-annotation-ring--outer"></div>' +
        '<div class="g-annotation-ring--inner"></div>' +
        '<span class="g-annotation-label">' + label + '</span>' +
      '</div>'
    );
  }).join('');
  return '<div id="g-annotations-layer" class="g-annotations">' + pins + '</div>';
}

// gary.showAnnotations(points)
// Appends a full-screen SVG annotation layer to the overlay without replacing
// the existing card or indicator. Rings auto-clear after 12 seconds.
window.gary.showAnnotations = function (points) {
  window.gary.clearAnnotations();
  if (!points || points.length === 0) return;
  overlay().insertAdjacentHTML('beforeend', annotationsHTML(points));
  _annotationTimer = setTimeout(window.gary.clearAnnotations, 12000);
};

// gary.clearAnnotations()
// Removes the annotation SVG layer and cancels the auto-clear timer.
window.gary.clearAnnotations = function () {
  if (_annotationTimer) { clearTimeout(_annotationTimer); _annotationTimer = null; }
  var layer = document.getElementById('g-annotations-layer');
  if (layer) layer.parentNode.removeChild(layer);
};

// --- Boot --------------------------------------------------------------------
// Show the idle arc immediately so the overlay is never a blank transparent pane.
// ?dev in the URL paints the page background so you can see what you're doing
// in a normal browser tab without the pywebview transparent window.
if (new URLSearchParams(location.search).has('dev')) {
  document.documentElement.style.background = '#0c0c0c';
}
window.gary.renderIndicator();
