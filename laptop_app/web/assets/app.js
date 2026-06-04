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
// Stores payload and shows the idle arc — used when show_popup arrives on the bus.
window.gary.queuePopup = function (title, text) {
  _lastCard = { title, text };
  window.gary.renderIndicator();
};

// gary.renderCard(title, text)
// Replaces the overlay with a fixed-height card showing title + scrollable text.
window.gary.renderCard = function (title, text) {
  _lastCard = { title, text };
  overlay().innerHTML = cardHTML(title, text);

  const card = overlay().querySelector('.g-card');

  // Close → back to idle indicator.
  card.querySelector('.g-card-x').addEventListener('click', function () {
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

// --- Boot --------------------------------------------------------------------
// Show the idle arc immediately so the overlay is never a blank transparent pane.
// ?dev in the URL paints the page background so you can see what you're doing
// in a normal browser tab without the pywebview transparent window.
if (new URLSearchParams(location.search).has('dev')) {
  document.documentElement.style.background = '#0c0c0c';
}
window.gary.renderIndicator();
