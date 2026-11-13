/* Click sparkles: decoration only.
   generate_html.py inserts this file only when settings.json has "enabled": true,
   and replaces the settings token below with duration_ms and particle_count.
   The page's links and buttons always come first: this script never calls
   preventDefault or stopPropagation, never changes links, and its layer ignores pointers. */
(function () {
  'use strict';
  try {
    var config = __CLICK_SPARKLES_SETTINGS__;
    var DURATION_MS = config.duration_ms;
    var COUNT = config.particle_count;
    var MARKS = ['✨', '⭐', '🌟', '💫', '✦'];
    var MAX_PARTICLES = COUNT * 8;
    var DRAG_PX = 10;
    var layer = null;
    var live = [];
    var press = null;
    var motion = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;

    function removeParticle(particle) {
      var index = live.indexOf(particle);
      if (index < 0) return;
      live.splice(index, 1);
      clearTimeout(particle.timer);
      if (particle.el.parentNode) particle.el.parentNode.removeChild(particle.el);
      if (!live.length && layer) {
        if (layer.parentNode) layer.parentNode.removeChild(layer);
        layer = null;
      }
    }

    function clearAll() {
      while (live.length) removeParticle(live[0]);
      if (layer && layer.parentNode) layer.parentNode.removeChild(layer);
      layer = null;
    }

    function host() {
      if (!layer) {
        layer = document.createElement('div');
        layer.className = 'click-sparkles-layer';
        layer.setAttribute('aria-hidden', 'true');
        document.body.appendChild(layer);
      }
      return layer;
    }

    function wanted(event) {
      // detail 0: keyboard Enter/Space or a script click, which has no pointer position.
      if (event.button !== 0 || !event.detail) return false;
      if (motion && motion.matches) return false;
      if (press && (Math.abs(event.clientX - press.x) > DRAG_PX || Math.abs(event.clientY - press.y) > DRAG_PX)) return false;
      var selection = window.getSelection ? window.getSelection() : null;
      if (selection && !selection.isCollapsed && String(selection).length) return false;
      return true;
    }

    function spawn(x, y) {
      var box = host();
      for (var i = 0; i < COUNT; i++) {
        var el = document.createElement('span');
        el.className = 'click-sparkle';
        el.textContent = MARKS[Math.floor(Math.random() * MARKS.length)];
        var angle = (Math.PI * 2 * i) / COUNT + Math.random() * 0.5;
        var dist = 50 + Math.random() * 60;
        el.style.left = x + 'px';
        el.style.top = y + 'px';
        el.style.fontSize = (12 + Math.random() * 12) + 'px';
        el.style.setProperty('--tx', (Math.cos(angle) * dist) + 'px');
        el.style.setProperty('--ty', (Math.sin(angle) * dist - 80) + 'px');
        el.style.animationDuration = DURATION_MS + 'ms';
        box.appendChild(el);
        var particle = { el: el, timer: 0 };
        particle.timer = setTimeout(removeParticle.bind(null, particle), DURATION_MS);
        live.push(particle);
      }
      while (live.length > MAX_PARTICLES) removeParticle(live[0]);
    }

    document.addEventListener('pointerdown', function (event) {
      try {
        if (event.isPrimary !== false) press = { x: event.clientX, y: event.clientY };
      } catch (ignored) { press = null; }
    }, { capture: true, passive: true });

    document.addEventListener('click', function (event) {
      try {
        if (wanted(event)) spawn(event.clientX, event.clientY);
      } catch (ignored) {
        try { clearAll(); } catch (alsoIgnored) { layer = null; live = []; }
      } finally {
        press = null;
      }
    }, { passive: true });

    window.addEventListener('pagehide', function () {
      try { clearAll(); } catch (ignored) { layer = null; live = []; }
    });
  } catch (ignored) {
    // A decoration failure must never affect the page.
  }
})();
