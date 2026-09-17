/* ArchHub website interactions: the design's hero canvas, host picker and
   self-heal timeline, ported from ArchHub Website.html onto the markup the
   Cell website renders. This is the only script the site serves; the export
   admits it by its exact sha256. It reads data-* hooks and never fetches. */
(function () {
  'use strict';

  // Hero canvas: drag a node by its head, drag from an output port to wire it.
  (function () {
    var cv = document.querySelector('[data-canvas]');
    if (!cv) return;
    var hint = cv.querySelector('[data-hint]');
    var SIG = { elements: '#5fb3b3', proposal: '#a98cd6', approval: '#7ec18e' };
    var ns = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(ns, 'svg');
    svg.setAttribute('class', 'site-wires');
    svg.setAttribute('aria-hidden', 'true');
    cv.insertBefore(svg, cv.firstChild);
    var wires = [];
    var seed = cv.getAttribute('data-wires') || '';
    seed.split(' ').forEach(function (pair) {
      var ends = pair.split('>');
      if (ends.length !== 2) return;
      wires.push({ from: ends[0].split('.'), to: ends[1].split('.') });
    });
    var nodeEl = function (k) { return cv.querySelector('[data-node="' + k + '"]'); };
    var portEl = function (k, p) {
      var nd = nodeEl(k); if (!nd) return null;
      return nd.querySelector('[data-out="' + p + '"]') || nd.querySelector('[data-in="' + p + '"]');
    };
    var dotAt = function (pe) {
      if (!pe) return null;
      var i = pe.querySelector('.site-node-dot'); if (!i) return null;
      var r = i.getBoundingClientRect(), c = cv.getBoundingClientRect();
      return { x: r.left - c.left + r.width / 2, y: r.top - c.top + r.height / 2, out: pe.hasAttribute('data-out'), sig: pe.getAttribute('data-sig') };
    };
    var path = function (a, b) {
      var dx = Math.max(38, Math.abs(b.x - a.x) * 0.45);
      var s1 = a.out ? 1 : -1, s2 = b.out ? 1 : -1;
      return 'M' + a.x + ',' + a.y + ' C' + (a.x + dx * s1) + ',' + a.y + ' ' + (b.x + dx * s2) + ',' + b.y + ' ' + b.x + ',' + b.y;
    };
    var line = function (d, col, width, opacity, dash) {
      var p = document.createElementNS(ns, 'path');
      p.setAttribute('d', d); p.setAttribute('fill', 'none');
      p.setAttribute('stroke', col); p.setAttribute('stroke-width', width);
      p.setAttribute('opacity', opacity); p.setAttribute('stroke-linecap', 'round');
      if (dash) p.setAttribute('stroke-dasharray', dash);
      svg.appendChild(p);
    };
    function draw(ghost) {
      while (svg.firstChild) svg.removeChild(svg.firstChild);
      wires.forEach(function (w) {
        var a = dotAt(portEl(w.from[0], w.from[1])), b = dotAt(portEl(w.to[0], w.to[1]));
        if (!a || !b) return;
        var col = SIG[a.sig] || '#9b938a';
        line(path(a, b), col, '5', '0.14');
        line(path(a, b), col, '1.6', '0.92');
      });
      if (ghost) line(path(ghost.a, { x: ghost.x, y: ghost.y, out: false }), SIG[ghost.a.sig] || '#d97757', '1.6', '0.85', '4 4');
    }
    var drag = null, wiring = null;
    cv.addEventListener('pointerdown', function (e) {
      var out = e.target.closest('[data-out]');
      if (out) {
        var nd = out.closest('[data-node]');
        wiring = { a: dotAt(out), node: nd.getAttribute('data-node'), port: out.getAttribute('data-out'), sig: out.getAttribute('data-sig') };
        e.preventDefault(); return;
      }
      var head = e.target.closest('.site-node-head');
      if (!head) return;
      var nd2 = head.closest('[data-node]');
      var r = nd2.getBoundingClientRect(), c = cv.getBoundingClientRect();
      drag = { el: nd2, ox: e.clientX - (r.left - c.left), oy: e.clientY - (r.top - c.top) };
      nd2.classList.add('site-node-dragging');
      if (hint) hint.style.opacity = '0';
      e.preventDefault();
    });
    window.addEventListener('pointermove', function (e) {
      var c = cv.getBoundingClientRect();
      if (drag) {
        var w = drag.el.offsetWidth, hh = drag.el.offsetHeight;
        var x = Math.max(4, Math.min(c.width - w - 4, e.clientX - drag.ox));
        var y = Math.max(4, Math.min(c.height - hh - 4, e.clientY - drag.oy));
        drag.el.style.left = x + 'px'; drag.el.style.top = y + 'px';
        draw();
        return;
      }
      if (wiring) {
        var tgt = e.target.closest ? e.target.closest('[data-in]') : null;
        cv.querySelectorAll('[data-node]').forEach(function (n2) { n2.classList.remove('site-wire-ok', 'site-wire-no'); });
        if (tgt) {
          var ok = tgt.getAttribute('data-sig') === wiring.sig;
          tgt.closest('[data-node]').classList.add(ok ? 'site-wire-ok' : 'site-wire-no');
        }
        draw({ a: wiring.a, x: e.clientX - c.left, y: e.clientY - c.top });
      }
    });
    window.addEventListener('pointerup', function (e) {
      if (drag) { drag.el.classList.remove('site-node-dragging'); drag = null; draw(); return; }
      if (!wiring) return;
      var tgt = e.target.closest ? e.target.closest('[data-in]') : null;
      if (tgt && tgt.getAttribute('data-sig') === wiring.sig) {
        var nd = tgt.closest('[data-node]').getAttribute('data-node');
        var pt = tgt.getAttribute('data-in');
        wires = wires.filter(function (w) { return !(w.to[0] === nd && w.to[1] === pt); });
        wires.push({ from: [wiring.node, wiring.port], to: [nd, pt] });
      }
      cv.querySelectorAll('[data-node]').forEach(function (n2) { n2.classList.remove('site-wire-ok', 'site-wire-no'); });
      wiring = null; draw();
    });
    draw();
    window.addEventListener('resize', function () { draw(); });
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { draw(); });
    setTimeout(draw, 120);
  })();

  // Host picker: pick a host to see the operations its adapter carries out.
  (function () {
    var wrap = document.querySelector('[data-hosts]');
    var out = document.querySelector('[data-host-detail]');
    if (!wrap || !out) return;
    var idle = out.textContent;
    var cur = null;
    function span(cls, text) {
      var s = document.createElement('span'); s.className = cls; s.textContent = text; return s;
    }
    function reset() {
      while (out.firstChild) out.removeChild(out.firstChild);
    }
    function show(b) {
      reset();
      var head = document.createElement('div'); head.className = 'site-hd-head';
      var name = b.firstChild ? b.firstChild.nodeValue : '';
      var ops = (b.getAttribute('data-ops') || '').split('|').filter(Boolean);
      head.appendChild(span('site-hd-name', name));
      head.appendChild(span('site-hd-sig', ops.length + (ops.length === 1 ? ' operation' : ' operations')));
      out.appendChild(head);
      var list = document.createElement('div'); list.className = 'site-hd-ops';
      ops.forEach(function (o) { list.appendChild(span('site-hd-op', o)); });
      out.appendChild(list);
    }
    function pick(b) {
      if (cur === b) { b.setAttribute('aria-pressed', 'false'); cur = null; reset(); out.appendChild(span('site-host-idle', idle)); return; }
      if (cur) cur.setAttribute('aria-pressed', 'false');
      b.setAttribute('aria-pressed', 'true'); cur = b; show(b);
    }
    wrap.addEventListener('click', function (e) {
      var b = e.target.closest('[data-ops]'); if (b) pick(b);
    });
    wrap.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      var b = e.target.closest('[data-ops]'); if (!b) return;
      e.preventDefault(); pick(b);
    });
  })();

  // Self-heal timeline: an illustration of a recovery, played on request and
  // once when the panel first scrolls into view.
  (function () {
    var block = document.querySelector('[data-heal]');
    if (!block) return;
    var btn = block.querySelector('[data-heal-play]');
    var statusEl = block.querySelector('[data-heal-status]');
    var logEl = block.querySelector('[data-heal-log]');
    var clockEl = block.querySelector('[data-heal-clock]');
    var kicker = block.querySelector('[data-heal-kicker]');
    if (!btn || !statusEl || !logEl || !clockEl || !kicker) return;
    var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var steps = [
      { t: 0, w: 'WATCH', c: 'warn', mark: '\u25b2 ', m: 'RPC failed to ack heartbeat (3 retries)', status: ['Connection lost', 'err'], before: [1, 'timeout'] },
      { t: 620, w: 'DIAG', c: 'soft', m: 'the host stopped answering on its port', before: [2, 'closed'] },
      { t: 1050, w: 'ACTION', c: 'cyan', mark: '\u2192 ', m: 're-issuing handshake \u00b7 800ms grace', status: ['Recovering', 'warn'], before: [3, 'orphaned'] },
      { t: 2180, w: 'OK', c: 'ok', mark: '\u2713 ', m: 'handshake acknowledged', after: [1, 'ok'] },
      { t: 2560, w: 'RESTORE', c: 'ok', mark: '\u2713 ', m: 'session rebound', after: [2, 'open'], status: ['Recovered', 'ok'] },
      { t: 2900, w: 'USER', c: 'soft', m: 'no notification shown \u00b7 recovery silent', after: [3, 'restored'] }
    ];
    var COL = { warn: 'var(--warn)', ok: 'var(--ok)', cyan: 'var(--cyan)', soft: 'var(--ink-soft)', err: 'var(--err)' };
    var stamp = function (ms) { return '+' + (ms / 1000).toFixed(2) + 's'; };
    var timers = [];
    function span(cls, text, color) {
      var s = document.createElement('span'); s.className = cls; s.textContent = text;
      if (color) s.style.color = color;
      return s;
    }
    function play() {
      timers.forEach(clearTimeout); timers = [];
      while (logEl.firstChild) logEl.removeChild(logEl.firstChild);
      btn.disabled = true; btn.textContent = 'recovering\u2026';
      kicker.style.color = 'var(--ink-soft)';
      Array.prototype.forEach.call(block.querySelectorAll('[data-b],[data-a]'), function (el) {
        el.textContent = '-'; el.className = 'site-diff-value site-dv-pending';
      });
      var speed = reduce ? 0 : 1;
      steps.forEach(function (s) {
        timers.push(setTimeout(function () {
          var row = document.createElement('div');
          row.className = 'site-logline';
          row.appendChild(span('site-lt', stamp(s.t)));
          row.appendChild(span('site-lw', s.w, COL[s.c]));
          var msg = span('site-lm', '');
          if (s.mark) msg.appendChild(span('', s.mark, COL[s.c]));
          msg.appendChild(document.createTextNode(s.m));
          row.appendChild(msg);
          logEl.appendChild(row);
          if (s.status) { statusEl.textContent = s.status[0]; statusEl.style.color = COL[s.status[1]]; }
          if (s.before) { var b = block.querySelector('[data-b="' + s.before[0] + '"]'); if (b) { b.textContent = s.before[1]; b.className = 'site-diff-value site-dv-bad'; } }
          if (s.after) { var a = block.querySelector('[data-a="' + s.after[0] + '"]'); if (a) { a.textContent = s.after[1]; a.className = 'site-diff-value site-dv-good'; } }
          clockEl.textContent = 'illustration \u00b7 ' + stamp(s.t);
        }, s.t * speed));
      });
      timers.push(setTimeout(function () {
        clockEl.textContent = 'illustration \u00b7 recovered without a restart';
        kicker.style.color = 'var(--accent)';
        btn.disabled = false; btn.textContent = 'Break it again \u21ba';
      }, reduce ? 0 : 3150));
    }
    btn.addEventListener('click', play);
    var seen = false;
    if ('IntersectionObserver' in window) {
      var io = new IntersectionObserver(function (es) {
        es.forEach(function (e) { if (e.isIntersecting && !seen) { seen = true; play(); io.disconnect(); } });
      }, { threshold: 0.45 });
      io.observe(block);
    }
  })();
})();