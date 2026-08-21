/* score-panel.js — themed chart components for the redesign concepts.
   <score-panel>, <song-timeline>, <chord-cards>. All colors/typography come
   from CSS custom properties (--sp-*) set by the host page. Uses ReportLib. */
(function () {
  if (customElements.get("score-panel")) return;
  var CSS = [
    "score-panel{display:block}",
    "score-panel .sp-rollwrap{position:relative;border:1px solid var(--sp-line);",
    " border-radius:var(--sp-chart-radius,10px);overflow:hidden;cursor:crosshair;",
    " background:var(--sp-chart-bg,#fff)}",
    "score-panel .roll{display:block}",
    "score-panel .roll .octave{stroke:var(--sp-grid,#ece5d4);stroke-width:1}",
    "score-panel .roll .octlabel{fill:var(--sp-muted);font:600 9px var(--sp-sans,sans-serif)}",
    "score-panel .roll .nr{fill:var(--sp-note);cursor:pointer}",
    "score-panel .roll .nr:hover{fill:var(--sp-accent)}",
    "score-panel .sp-now-line{position:absolute;top:0;bottom:0;width:1.5px;",
    " background:var(--sp-accent);pointer-events:none;z-index:2;",
    " box-shadow:0 0 0 2.5px color-mix(in srgb,var(--sp-accent) 14%,transparent)}",
    "score-panel .sp-loop{position:absolute;top:0;bottom:0;pointer-events:none;z-index:1;",
    " background:color-mix(in srgb,var(--sp-accent) 8%,transparent);",
    " border-left:1.5px solid color-mix(in srgb,var(--sp-accent) 55%,transparent);",
    " border-right:1.5px solid color-mix(in srgb,var(--sp-accent) 55%,transparent)}",
    "score-panel .namesline{position:relative;height:3.2rem;margin-top:.2rem}",
    "score-panel .ncol{position:absolute;top:0;transform:translateX(-50%);",
    " display:inline-flex;flex-direction:column;align-items:center;padding:0 .1rem;",
    " font:600 calc(.5rem*var(--sp-scale,1))/1.3 var(--sp-mono,monospace);",
    " color:var(--sp-muted);opacity:.5;cursor:pointer;border-radius:3px;",
    " transition:font-size .12s,opacity .12s}",
    "score-panel .ncol i{font-style:normal}",
    "score-panel .ncol.dim{opacity:.1}",
    "score-panel .ncol:hover{color:var(--sp-accent);opacity:1;z-index:4}",
    "score-panel .ncol.near{font-size:calc(.58rem*var(--sp-scale,1));opacity:.85;",
    " color:var(--sp-ink);z-index:2}",
    "score-panel .ncol.now{font-size:calc(.68rem*var(--sp-scale,1));opacity:1;",
    " color:var(--sp-accent);font-weight:700;z-index:3;",
    " border-bottom:2px solid var(--sp-accent)}",
    "score-panel .words{position:relative;height:2.5rem;margin-top:.3rem}",
    "score-panel .word{position:absolute;top:0;color:var(--sp-ink);opacity:.72;",
    " font:400 calc(.7rem*var(--sp-scale,1))/1.35 var(--sp-sans,sans-serif);",
    " white-space:nowrap;cursor:pointer;padding-top:2px}",
    "score-panel .word::before{content:'';position:absolute;left:0;top:-3px;",
    " width:1.5px;height:5px;background:color-mix(in srgb,var(--sp-ink) 30%,transparent)}",
    "score-panel .word.l1{top:1.2rem}",
    "score-panel .word.l1::before{height:4px}",
    "score-panel .word.clip{opacity:.14}",
    "score-panel .word.clip:hover{opacity:1}",
    "score-panel .word.near{opacity:.85}",
    "score-panel .sp-phrase.live{max-width:none !important;z-index:6;",
    " background:var(--sp-chart-bg,#fff);padding-right:8px;border-radius:4px;",
    " -webkit-mask-image:none;mask-image:none;box-shadow:0 0 0 3px var(--sp-chart-bg,#fff)}",
    "score-panel .sp-phrase{position:absolute;top:0;white-space:nowrap;overflow:hidden;",
    " padding-top:2px;-webkit-mask-image:linear-gradient(90deg,#000 82%,transparent);",
    " mask-image:linear-gradient(90deg,#000 82%,transparent)}",
    "score-panel .sp-phrase.l1{top:1.2rem}",
    "score-panel .sp-phrase::before{content:'';position:absolute;left:0;top:-3px;",
    " width:1.5px;height:5px;background:color-mix(in srgb,var(--sp-ink) 30%,transparent)}",
    "score-panel .sp-phrase .word{position:static;display:inline;padding:0}",
    "score-panel .sp-phrase .word::before{display:none}",
    "score-panel .word:hover{color:var(--sp-accent);opacity:1;z-index:4}",
    "score-panel .word.now{color:var(--sp-accent);opacity:1;font-weight:650;z-index:3;",
    " border-bottom:2px solid var(--sp-accent)}",
    "score-panel .word.now::before{background:var(--sp-accent);height:6px;width:2px}",
    "score-panel .word i{font-style:normal}",
    "score-panel .sp-seqwrap.sp-rollscroll{border:0;background:transparent;border-radius:0}",
    "score-panel .sp-rollinner{position:relative;display:block;min-width:100%}",
    "score-panel .sp-rollinner .sp-now-line{z-index:4}",
    "score-panel .sp-seqwrap{overflow-x:auto;border:1px solid var(--sp-line);",
    " border-radius:var(--sp-chart-radius,10px);background:var(--sp-chart-bg,#fff)}",
    "score-panel .sp-inner{position:relative;display:inline-block;min-width:100%;",
    " padding:var(--sp-seq-pad,.6rem .9rem)}",
    /* The line and shades carry coordinates in the chart's own space:
       px from the SVG origin, or ch of the tab's monospace grid. Offset
       past the padding and adopt the mono font so both units land true. */
    "score-panel .sp-inner .sp-now-line,score-panel .sp-inner .sp-loop{",
    " margin-left:.9rem;",
    " font:400 calc(.78rem*var(--sp-scale,1))/1.5 var(--sp-mono,monospace)}",
    "score-panel .sp-inner .words{margin:.15rem 0 .1rem 0}",
    "score-panel .sp-inner .word{font-family:var(--sp-mono,monospace);",
    " font-size:calc(.78rem*var(--sp-scale,1))}",
    "score-panel .sp-inner .word i{font:500 calc(.66rem*var(--sp-scale,1))/1.4 ",
    " var(--sp-sans,sans-serif)}",
    "score-panel .sp-tab{margin:0;font:400 calc(.78rem*var(--sp-scale,1))/1.5 ",
    " var(--sp-mono,monospace);color:var(--sp-tab-ink,var(--sp-note))}",
    "score-panel .staff{display:block}",
    "score-panel .staff .sline,score-panel .staff .ledger,score-panel .staff .barline",
    " {stroke:var(--sp-staffline,#b9b09b);stroke-width:1}",
    "score-panel .staff .clef{font-size:40px;fill:var(--sp-ink)}",
    "score-panel .staff .bclef{font-size:30px}",
    "score-panel .staff .acc{font-size:10px;fill:var(--sp-ink)}",
    "score-panel .staff .sn{fill:var(--sp-note);cursor:pointer}",
    "score-panel .staff .sn:hover{fill:var(--sp-accent)}",
    "score-panel .staff .sn.open{fill:var(--sp-chart-bg,#fff);stroke:var(--sp-note);stroke-width:1.6}",
    "score-panel .staff .stem{stroke:var(--sp-note);stroke-width:1.4}",
    "score-panel .staff .beam{stroke:var(--sp-note);stroke-width:3.2}",
    "score-panel .staff .flag{stroke:var(--sp-note);stroke-width:1.5}",
    "score-panel .staff .tsig{fill:var(--sp-ink);font:700 15px var(--sp-serif,serif)}",
    "score-panel .sp-chips{display:flex;flex-wrap:wrap;gap:.35rem;margin:0 0 .55rem}",
    "score-panel .sp-chip{font:600 calc(.8rem*var(--sp-scale,1))/1 var(--sp-sans,sans-serif);",
    " padding:.32em .62em;border:1px solid var(--sp-line);border-radius:7px;",
    " color:var(--sp-ink);background:var(--sp-chip-bg,transparent);cursor:pointer;",
    " font-variant-numeric:tabular-nums;transition:all .12s}",
    "score-panel .sp-chip:hover{border-color:var(--sp-accent);color:var(--sp-accent)}",
    "score-panel .sp-chip.now{border-color:var(--sp-accent);color:var(--sp-accent);",
    " background:color-mix(in srgb,var(--sp-accent) 9%,transparent);",
    " box-shadow:inset 0 -2px 0 var(--sp-accent)}",
    "score-panel .sp-empty{border:1px dashed var(--sp-line);border-radius:10px;",
    " padding:1rem 1.2rem;color:var(--sp-muted)}",
    "score-panel .sp-empty em{font:italic 500 .95rem var(--sp-serif,serif);",
    " color:var(--sp-muted)}",
    "score-panel .sp-empty code{display:inline-block;margin-top:.4rem;",
    " font:500 .72rem var(--sp-mono,monospace);color:var(--sp-ink);",
    " background:var(--sp-chip-bg,rgba(0,0,0,.04));padding:.15rem .5rem;border-radius:5px}",
    "song-timeline{display:block}",
    "song-timeline .st{position:relative;display:flex;overflow:hidden;cursor:pointer;",
    " border-radius:var(--st-radius,8px);height:var(--st-h,40px);",
    " border:1px solid var(--sp-line)}",
    "song-timeline .st-seg{position:relative;display:flex;align-items:center;",
    " justify-content:center;min-width:0;overflow:hidden;",
    " background:hsl(var(--h) var(--st-sat,30%) var(--st-lit,93%));",
    " border-right:1px solid color-mix(in srgb,var(--sp-line) 70%,transparent)}",
    "song-timeline .st-seg span{font:650 var(--st-font,.66rem)/1 var(--sp-sans,sans-serif);",
    " letter-spacing:.03em;text-transform:uppercase;white-space:nowrap;overflow:hidden;",
    " text-overflow:ellipsis;padding:0 .3rem;",
    " color:hsl(var(--h) 26% var(--st-text,34%))}",
    "song-timeline .st-seg:hover{filter:brightness(.97)}",
    "song-timeline .st-seg.cur{box-shadow:inset 0 -3px 0 var(--sp-accent);",
    " background:hsl(var(--h) var(--st-sat,30%) calc(var(--st-lit,93%) - 4%))}",
    "song-timeline .st-line{position:absolute;top:0;bottom:0;width:2px;z-index:3;",
    " background:var(--sp-accent);pointer-events:none;",
    " box-shadow:0 0 0 2.5px color-mix(in srgb,var(--sp-accent) 16%,transparent)}",
    "song-timeline .st-loop{position:absolute;top:0;bottom:0;z-index:2;pointer-events:none;",
    " background:color-mix(in srgb,var(--sp-accent) 10%,transparent);",
    " border-left:1.5px solid var(--sp-accent);border-right:1.5px solid var(--sp-accent)}",
    "chord-cards{display:block}",
    "chord-cards .cc{display:grid;gap:var(--cc-gap,.7rem);",
    " grid-template-columns:repeat(auto-fill,minmax(var(--cc-min,96px),1fr))}",
    "chord-cards figure{margin:0;padding:.55rem .3rem .45rem;text-align:center;",
    " background:var(--cc-bg,transparent);border:1px solid var(--sp-line);",
    " border-radius:10px}",
    "chord-cards figure.cur{border-color:var(--sp-accent);",
    " box-shadow:inset 0 -2.5px 0 var(--sp-accent)}",
    "chord-cards figcaption{font:600 .88rem var(--sp-sans,sans-serif);color:var(--sp-ink)}",
    "chord-cards figcaption small{display:block;font:500 .68rem var(--sp-mono,monospace);",
    " color:var(--sp-muted);margin-top:.12rem}",
    "chord-cards .chordbox{width:100%;max-width:var(--cc-box,96px);height:auto}",
    "chord-cards .chordbox .fret,chord-cards .chordbox .string{stroke:var(--sp-grid,#ddd6c4);stroke-width:1}",
    "chord-cards .chordbox .nut{stroke:var(--sp-ink);stroke-width:3}",
    "chord-cards .chordbox .dot{fill:var(--sp-ink)}",
    "chord-cards .chordbox .open{fill:none;stroke:var(--sp-ink);stroke-width:1.5}",
    "chord-cards .chordbox .mark,chord-cards .chordbox .basefret{fill:var(--sp-muted);",
    " font:600 11px var(--sp-sans,sans-serif);text-anchor:middle}",
    "chord-cards .chordbox .basefret{text-anchor:start}"
  ].join("\n");
  function ensureCss() {
    if (document.getElementById("score-panel-css")) return;
    var el = document.createElement("style");
    el.id = "score-panel-css";
    el.textContent = CSS;
    document.head.appendChild(el);
  }
  function lib() { return window.ReportLib; }
  function whenReady(self, fn) {
    var wait = setInterval(function () {
      if (!window.ReportLib) return;
      clearInterval(wait);
      window.ReportLib.loadSong("data/song.json").then(function (song) {
        if (!self.isConnected) return;
        fn(song);
      });
    }, 25);
  }
  // Time scale that guarantees the lyric fits at true positions: px/second
  // is raised until consecutive words on a lane no longer overlap.
  function neededPPS(words, start, end) {
    var lanes = [[], []];
    (words || []).forEach(function (w) {
      if (w.start < end && w.end > start) lanes[(w.line || 0) % 2].push(w);
    });
    var needs = [];
    lanes.forEach(function (lane) {
      lane.sort(function (a, b) { return a.start - b.start; });
      for (var i = 1; i < lane.length; i++) {
        var dt = Math.max(lane[i].start - lane[i - 1].start, 0.15);
        var wpx = lane[i - 1].text.length * 6.4 + 10;
        needs.push(wpx / dt);
      }
    });
    if (!needs.length) return 0;
    needs.sort(function (a, b) { return a - b; });
    return needs[Math.min(needs.length - 1, Math.floor(needs.length * 0.9))];
  }
  // moment); where two words on one lane would print over each other the later
  // one dims instead of sliding — alignment beats at-rest legibility, and the
  // playhead (or hover) re-lights it.
  function batchLayoutWords(row) {
    var words = Array.prototype.slice.call(row.querySelectorAll(".word"));
    var metrics = words.map(function (w) {
      return { el: w, lane: w.classList.contains("l1") ? 1 : 0,
        x: w.offsetLeft, w: w.offsetWidth,
        keep: w.classList.contains("now") || w.classList.contains("near") };
    });
    var lanes = [-1e9, -1e9];
    metrics.forEach(function (m) {
      if (m.keep) { lanes[m.lane] = m.x + m.w; return; }
      if (m.x < lanes[m.lane] + 6) { m.el.classList.add("clip"); return; }
      lanes[m.lane] = m.x + m.w;
    });
  }
  function batchThinNames(row) {
    var cols = Array.prototype.slice.call(row.querySelectorAll(".ncol"));
    var metrics = cols.map(function (col) {
      return { el: col, left: col.offsetLeft - col.offsetWidth / 2, w: col.offsetWidth };
    });
    var right = -1e9;
    metrics.forEach(function (m) {
      var isNow = m.el.classList.contains("now") || m.el.classList.contains("near");
      if (!isNow && m.left < right + 3) { m.el.classList.add("dim"); return; }
      right = m.left + m.w;
    });
  }
  function wordsRowFlow(L, words, start, end, opts) {
    opts = opts || {};
    var inside = (words || []).filter(function (s) {
      return s.start < end && s.end > start;
    });
    if (!inside.length) return "";
    var lines = [];
    inside.forEach(function (w) {
      var last = lines[lines.length - 1];
      if (last && last.line === w.line) { last.words.push(w); return; }
      lines.push({ line: w.line, start: w.start, words: [w] });
    });
    function xOf(t) {
      if (opts.times) {
        var p = L.seqPos(opts.times, opts.xs, t,
          opts.lead == null ? 2 : opts.lead, opts.colw == null ? 4 : opts.colw);
        return { v: p.v, unit: p.unit };
      }
      var span = Math.max(end - start, 0.001);
      return { v: Math.max(0, Math.min((t - start) / span * 100, 100)), unit: "%" };
    }
    var out = lines.map(function (ln, i) {
      var lane = ln.line % 2;
      var a = xOf(ln.start);
      var width = "";
      for (var j = i + 1; j < lines.length; j++) {
        if (lines[j].line % 2 === lane) {
          var b = xOf(lines[j].start);
          if (b.unit === a.unit) {
            width = "max-width:" + Math.max(b.v - a.v - (a.unit === "%" ? 1 : 2), 4).toFixed(1) + a.unit + ";";
          }
          break;
        }
      }
      var inner = ln.words.map(function (w) {
        return '<span class="word" data-start="' + w.start + '" data-end="' + w.end +
          '"><i>' + L.esc(w.text) + "</i></span>";
      }).join(" ");
      return '<span class="sp-phrase' + (lane ? " l1" : "") + '" style="left:' +
        a.v.toFixed(1) + a.unit + ";" + width + '">' + inner + "</span>";
    });
    return '<div class="words wflow">' + out.join("") + "</div>";
  }
  function markNow(rootEl, sel, t) {
    if (t == null) return;
    var els = Array.prototype.slice.call(rootEl.querySelectorAll(sel));
    var activeIdx = -1;
    els.forEach(function (el, i) {
      var s = parseFloat(el.dataset.start), e = parseFloat(el.dataset.end);
      if (t >= s && (isNaN(e) ? i === els.length - 1 : t < e)) activeIdx = i;
      else if (isNaN(e) && s <= t) activeIdx = i;
    });
    els.forEach(function (el, i) {
      el.classList.toggle("now", i === activeIdx);
      el.classList.toggle("near",
        activeIdx >= 0 && (i === activeIdx - 1 || i === activeIdx + 1));
    });
  }

  // ---- <score-panel> ------------------------------------------------------
  var spProto = Object.create(HTMLElement.prototype);
  spProto.connectedCallback = function () {
    ensureCss();
    var self = this;
    whenReady(self, function (song) { self._song = song; self._render(song); });
  };
  spProto.attributeChangedCallback = function (name, _o, newV) {
    var self = this;
    if (name === "playhead" && self._meta) {
      self.update(parseFloat(newV), { follow: true });
      return;
    }
    if (!self._song || self._pending) return;
    self._pending = true;
    requestAnimationFrame(function () {
      self._pending = false;
      if (self._song) self._render(self._song);
    });
  };
  spProto._render = function (song) {
    var L = lib();
    var self = this;
    var view = this.getAttribute("view") || "roll";
    var start = parseFloat(this.getAttribute("start"));
    var end = parseFloat(this.getAttribute("end"));
    var source = this.getAttribute("source") || "inst";
    var T = this.hasAttribute("playhead") ? parseFloat(this.getAttribute("playhead")) : null;
    var inWindow = T != null && T >= start && T < end;
    var loopAttr = (this.getAttribute("loop") || "").split(",").map(parseFloat).filter(isFinite);
    var loop = loopAttr.length === 2 ? loopAttr : null;
    var pos = parseInt(this.getAttribute("pos") || "0", 10);
    var showWords = this.getAttribute("words") !== "0";
    var showNames = this.getAttribute("names") !== "0";
    var rollRow = parseInt(this.getAttribute("rollrow") || "8", 10);
    if (this.getAttribute("force-empty") === "1") {
      this.innerHTML = '<div class="sp-empty"><em>' +
        L.esc(this.getAttribute("empty-title") || "No notes transcribed here") +
        "</em><br><code>" +
        L.esc(this.getAttribute("empty-cmd") || "music-stack local notes") +
        "</code></div>";
      return;
    }
    var pool = source === "voice" ? (song.voiceNotes || []) : song.notes;
    this._seq = null;
    var events = pool.filter(function (e) { return e.start < end && e.end > start; });
    var group = null;
    song.panels.forEach(function (g) {
      if (Math.abs(g.start - start) < 1.5 && Math.abs(g.end - end) < 1.5) group = g;
    });
    var chordEvents = source === "voice"
      ? (group ? (song.voiceBySpan[group.label + "@" + group.start] || []) : [])
      : (group ? group.events : []);
    var words = song.wordsSynced || song.words;
    var lyrMode = this.getAttribute("lyrics") || "synced";
    var self2 = this;
    function wRow(opts) {
      if (!showWords) return "";
      return lyrMode === "flow"
        ? wordsRowFlow(L, words, start, end, opts)
        : L.wordsRow(words, start, end, opts);
    }
    var html = "";
    function shadePct(el0, el1) {
      if (!loop) return "";
      var a = Math.max(loop[0], start), b = Math.min(loop[1], end);
      if (b <= a) return "";
      return '<div class="sp-loop" style="left:' +
        (100 * (a - start) / (end - start)).toFixed(2) + "%;width:" +
        (100 * (b - a) / (end - start)).toFixed(2) + '%"></div>';
    }
    if ((view === "roll" || view === "tab" || view === "staff") && !events.length) {
      var who = source === "voice" ? "voice" : "notes";
      var eTitle = this.getAttribute("empty-title") ||
        (source === "voice" ? "Nothing sung in this section" : "No notes transcribed here");
      var eCmd = this.getAttribute("empty-cmd") ||
        "music-stack local notes — transcribe this stem";
      this.innerHTML = '<div class="sp-empty"><em>' + L.esc(eTitle) + "</em><br>" +
        '<code>' + L.esc(eCmd) + "</code></div>";
      return;
    }
    if (view === "roll") {
      var span = end - start;
      var fitW = Math.max(this.clientWidth || 800, 320);
      var fitPPS = (fitW - 2) / span;
      var pps = Math.min(Math.max(fitPPS, showWords ? neededPPS(words, start, end) : 0), 130);
      var scrolled = pps > fitPPS + 0.5;
      var innerWpx = Math.round(span * (scrolled ? pps : fitPPS));
      var innerW = scrolled ? "width:" + innerWpx + "px;" : "";
      html = '<div class="sp-seqwrap sp-rollscroll"><div class="sp-rollinner" style="' +
        innerW + '">' +
        '<div class="sp-rollwrap">' + L.noteRoll(events, start, end,
          { row: rollRow, fixedHeight: true, width: innerWpx }) +
        "</div>" +
        (showNames ? L.namesRow(events, start, end) : "") + wRow() +
        '<div class="sp-now-line" style="display:none"></div>' + shadePct() +
        "</div></div>";
    } else if (view === "tab") {
      var ordered = events.slice().sort(function (a, b) {
        return a.start - b.start || a.midi - b.midi;
      });
      var seeds = [null, 5, 9];
      var positioned = L.choosePositions(ordered, [1, 2, 3, 4, 5, 6], seeds[pos] || null);
      var tabText = L.renderTab(positioned, [1, 2, 3, 4, 5, 6], 3);
      var times = ordered.map(function (e) { return e.start; });
      var seqShade = "";
      if (loop && times.length && loop[1] > start && loop[0] < end) {
        var pa = L.seqPos(times, null, Math.max(loop[0], times[0]), 2, 4);
        var pb = L.seqPos(times, null, Math.min(loop[1], end), 2, 4);
        seqShade = '<div class="sp-loop" style="left:' + pa.v.toFixed(1) +
          "ch;width:" + Math.max(pb.v - pa.v, 0).toFixed(1) + 'ch"></div>';
      }
      html = '<div class="sp-seqwrap"><div class="sp-inner">' +
        '<pre class="sp-tab">' + L.esc(tabText) + "</pre>" +
        wRow({ times: times }) +
        '<div class="sp-now-line" style="display:none"></div>' + seqShade + "</div></div>";
      this._seq = { times: times, xs: null, lead: 2, colw: 4,
        mids: positioned.map(function (p) { return p.midi != null ? [p.midi] : []; }) };
    } else if (view === "staff") {
      var built = L.staffSvg(events, start, end, {
        beats: song.beats.filter(function (b) { return b >= start - 1 && b < end + 1; }),
        downbeats: song.downbeats.filter(function (d) { return d >= start && d < end; })
      });
      var pxShade = "";
      if (built) {
        if (loop && loop[1] > start && loop[0] < end) {
          var qa = L.seqPos(built.times, built.xs, Math.max(loop[0], built.times[0]));
          var qb = L.seqPos(built.times, built.xs, Math.min(loop[1], end));
          pxShade = '<div class="sp-loop" style="left:' + qa.v.toFixed(1) +
            "px;width:" + Math.max(qb.v - qa.v, 0).toFixed(1) + 'px"></div>';
        }
        html = '<div class="sp-seqwrap sp-staffwrap"><div class="sp-inner">' + built.svg +
          wRow({ times: built.times, xs: built.xs }) +
          '<div class="sp-now-line" style="display:none"></div>' + pxShade + "</div></div>";
        this._seq = { times: built.times, xs: built.xs, lead: 2, colw: 4, mids: built.mids };
      } else {
        html = '<div class="sp-empty"><em>No notes transcribed here.</em></div>';
      }
    } else if (view === "chart") {
      var chips = chordEvents.map(function (ev) {
        return '<span class="sp-chip" data-start="' + ev[1] + '" data-end="' + ev[2] +
          '">' + L.esc(ev[0]) + "</span>";
      }).join("");
      var posLists = chordEvents.map(function (ev) {
        var c = song.canon[ev[0]];
        return c ? c.positions : null;
      });
      var chordTab = L.renderChordTab(posLists, 6);
      var cTimes = chordEvents.map(function (ev) { return ev[1]; });
      var cShade = "";
      if (loop && cTimes.length && loop[1] > start && loop[0] < end) {
        var ca = L.seqPos(cTimes, null, Math.max(loop[0], cTimes[0]), 2, 7);
        var cb = L.seqPos(cTimes, null, Math.min(loop[1], end), 2, 7);
        cShade = '<div class="sp-loop" style="left:' + ca.v.toFixed(1) +
          "ch;width:" + Math.max(cb.v - ca.v, 0).toFixed(1) + 'ch"></div>';
      }
      if (!chordEvents.length) {
        html = '<div class="sp-empty"><em>No chords detected here</em><br>' +
          '<code>music-stack local notes — needs basic-pitch</code></div>';
      } else {
        html = '<div class="sp-chips">' + chips + "</div>" +
          '<div class="sp-seqwrap"><div class="sp-inner">' +
          '<pre class="sp-tab">' + L.esc(chordTab) + "</pre>" +
          '<div class="sp-now-line" style="display:none"></div>' + cShade +
          "</div></div>";
        this._seq = { times: cTimes, xs: null, lead: 2, colw: 7,
          mids: chordEvents.map(function (ev) {
            var c = song.canon[ev[0]];
            return (c ? c.positions : []).map(function (p) {
              return L.STANDARD_TUNING[p.string] + p.fret;
            });
          }) };
      }
    }
    this.innerHTML = html;
    this._meta = {
      start: start, end: end, view: view,
      line: this.querySelector(".sp-now-line"),
      rollwrap: this.querySelector(".sp-rollwrap"),
      seqwrap: this.querySelector(".sp-seqwrap"),
      inner: this.querySelector(".sp-inner"),
      words: Array.prototype.slice.call(this.querySelectorAll(".word")),
      ncols: Array.prototype.slice.call(this.querySelectorAll(".ncol")),
      chips: Array.prototype.slice.call(this.querySelectorAll(".sp-chip")),
      phrases: Array.prototype.slice.call(this.querySelectorAll(".sp-phrase"))
    };
    if (T == null && this._T != null) T = this._T;
    this.update(T, { follow: T != null });
    this.querySelectorAll(".words").forEach(function (row) {
      if (!row.classList.contains("wflow")) batchLayoutWords(row);
    });
    this.querySelectorAll(".namesline").forEach(batchThinNames);
    this._wire();
  };
  // Cheap per-frame path: reposition the now-line, retoggle now/near classes,
  // keep the live phrase expanded, follow horizontally. No DOM rebuilding.
  spProto.update = function (T, opts) {
    var m = this._meta, L = lib();
    if (!m) return;
    this._T = T;
    markNow(this, ".word", T);
    markNow(this, ".ncol", T);
    markNow(this, ".sp-chip", T);
    m.phrases.forEach(function (ph) {
      ph.classList.toggle("live", !!ph.querySelector(".word.now"));
    });
    var line = m.line;
    if (!line) return;
    var show = T != null && T >= m.start && T < m.end;
    var seq = this._seq;
    if (show && seq && (!seq.times.length || T < seq.times[0])) show = false;
    if (!show) { line.style.display = "none"; return; }
    line.style.display = "block";
    var followWrap = m.seqwrap;
    if (seq) {
      var p = L.seqPos(seq.times, seq.xs, T, seq.lead, seq.colw);
      line.style.left = p.v.toFixed(2) + p.unit;
    } else {
      line.style.left = (100 * (T - m.start) / (m.end - m.start)).toFixed(3) + "%";
    }
    if (opts && opts.follow && followWrap && !this._scrubbing &&
        followWrap.scrollWidth > followWrap.clientWidth + 4) {
      followWrap.scrollLeft = Math.max(0, line.offsetLeft - followWrap.clientWidth / 2);
    }
  };
  spProto._timeFromX = function (clientX) {
    var m = this._meta, L = lib();
    if (!m) return null;
    if (this._seq && m.inner) {
      var seq = this._seq;
      if (!seq.times.length) return null;
      var best = 0, i;
      if (seq.xs) {
        // xs live in the SVG's own pixel space: measure from the SVG,
        // not the padded container around it.
        var ref = m.inner.querySelector("svg") || m.inner;
        var x = clientX - ref.getBoundingClientRect().left;
        for (i = 1; i < seq.xs.length; i++) {
          if (Math.abs(seq.xs[i] - x) < Math.abs(seq.xs[best] - x)) best = i;
        }
      } else {
        var pre = m.inner.querySelector(".sp-tab");
        if (!pre) return null;
        if (!this._chpx) {
          var probe = document.createElement("span");
          probe.style.cssText = "position:absolute;visibility:hidden;width:1ch";
          pre.appendChild(probe);
          this._chpx = probe.offsetWidth || 8;
          probe.remove();
        }
        var rect = pre.getBoundingClientRect();
        var xch = (clientX - rect.left) / this._chpx;
        best = Math.round((xch - seq.lead - seq.colw / 2) / seq.colw);
        best = Math.max(0, Math.min(seq.times.length - 1, best));
      }
      return { t: seq.times[best], idx: best };
    }
    if (m.rollwrap) {
      var r = m.rollwrap.getBoundingClientRect();
      var frac = Math.max(0, Math.min(1, (clientX - r.left) / r.width));
      return { t: m.start + frac * (m.end - m.start), idx: null };
    }
    return null;
  };
  spProto._emit = function (name, detail) {
    this.dispatchEvent(new CustomEvent(name, { detail: detail, bubbles: true }));
  };
  spProto._wire = function () {
    if (this._wired) return;
    this._wired = true;
    var self = this, L = lib();
    this.addEventListener("click", function (e) {
      if (self._squelch) { self._squelch = false; return; }
      var timed = e.target.closest ? e.target.closest("[data-start]") : null;
      // closest() walks past this component into the host page, where the
      // section wrapper carries its own data-start — an empty-area click
      // must resolve by pointer position, not to the section's beginning.
      if (timed && !self.contains(timed)) timed = null;
      var note = e.target.closest ? e.target.closest(".nr[data-midi], .sn[data-midi]") : null;
      if (e.altKey && !(e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        if (note) { L.previewTone([parseInt(note.dataset.midi, 10)]); return; }
        var hit = self._timeFromX(e.clientX);
        if (!hit) return;
        var mids = self._seq && self._seq.mids && hit.idx != null
          ? self._seq.mids[hit.idx] : null;
        if (!mids && self._meta.rollwrap) {
          mids = [];
          var bestD = Infinity, bestS = null;
          self._meta.rollwrap.querySelectorAll(".nr[data-start]").forEach(function (n) {
            var d = Math.abs(parseFloat(n.dataset.start) - hit.t);
            if (d < bestD) { bestD = d; bestS = parseFloat(n.dataset.start); }
          });
          if (bestS != null) {
            self._meta.rollwrap.querySelectorAll(".nr[data-start]").forEach(function (n) {
              if (Math.abs(parseFloat(n.dataset.start) - bestS) <= 0.08) {
                mids.push(parseInt(n.dataset.midi, 10));
              }
            });
          }
        }
        if (mids && mids.length) L.previewTone(mids);
        return;
      }
      var t = timed ? parseFloat(timed.dataset.start)
        : (self._timeFromX(e.clientX) || {}).t;
      if (t == null || !isFinite(t)) return;
      if (e.metaKey || e.ctrlKey) {
        e.preventDefault();
        self._emit("sp-loop-point", { t: t });
        return;
      }
      self._emit("sp-seek", { t: t });
    });
    this.addEventListener("pointerdown", function (e) {
      if (e.button !== 0 || e.altKey || e.metaKey || e.ctrlKey) return;
      var inChart = e.target.closest &&
        (e.target.closest(".sp-rollwrap") || e.target.closest(".sp-seqwrap"));
      if (!inChart) return;
      var x0 = e.clientX, active = false;
      function move(ev) {
        if (!active) {
          if (Math.abs(ev.clientX - x0) < 5) return;
          active = true;
          self._scrubbing = true;
          self._emit("sp-scrub-start", {});
        }
        var hit = self._timeFromX(ev.clientX);
        if (hit) self._emit("sp-scrub", { t: hit.t });
      }
      function up() {
        document.removeEventListener("pointermove", move);
        document.removeEventListener("pointerup", up);
        if (active) {
          self._scrubbing = false;
          self._squelch = true;
          self._emit("sp-scrub-end", {});
        }
      }
      document.addEventListener("pointermove", move);
      document.addEventListener("pointerup", up);
    });
  };
  function SP() { return Reflect.construct(HTMLElement, [], SP); }
  SP.prototype = spProto;
  SP.observedAttributes = ["playhead", "loop", "view", "source", "pos",
    "lyrics", "rollrow", "words", "names", "force-empty"];
  Object.setPrototypeOf(SP, HTMLElement);
  customElements.define("score-panel", SP);

  // ---- <song-timeline> ----------------------------------------------------
  var stProto = Object.create(HTMLElement.prototype);
  stProto._render = function () {
    var self = this;
    whenReady(self, function (song) {
      var L = lib();
      var T = self.hasAttribute("playhead") ? parseFloat(self.getAttribute("playhead")) : null;
      var loopAttr = (self.getAttribute("loop") || "").split(",").map(parseFloat).filter(isFinite);
      var loop = loopAttr.length === 2 ? loopAttr : null;
      var labels = self.getAttribute("labels") !== "0";
      var segs = song.sections.map(function (s) {
        var w = 100 * s.seconds / song.duration;
        var hue = L.SECTION_HUES[String(s.label).toLowerCase()] || 200;
        var cur = T != null && T >= s.start && T < s.end;
        return '<div class="st-seg' + (cur ? " cur" : "") + '" data-start="' + s.start +
          '" style="width:' + w.toFixed(3) + "%;--h:" + hue + '" title="' +
          L.esc(s.label) + " · " + L.clock(s.start) + "–" + L.clock(s.end) + '">' +
          (labels ? "<span>" + L.esc(s.label) + "</span>" : "") + "</div>";
      }).join("");
      var line = T != null
        ? '<div class="st-line" style="left:' + (100 * T / song.duration).toFixed(2) + '%"></div>' : "";
      var shade = loop
        ? '<div class="st-loop" style="left:' + (100 * loop[0] / song.duration).toFixed(2) +
          "%;width:" + (100 * (loop[1] - loop[0]) / song.duration).toFixed(2) + '%"></div>' : "";
      self.innerHTML = '<div class="st">' + segs + line + shade + "</div>";
      self._segEls = Array.prototype.slice.call(self.querySelectorAll(".st-seg"));
      self._lineEl = self.querySelector(".st-line");
      self._duration = song.duration;
      self._sections = song.sections;
      if (!self._wired) {
        self._wired = true;
        self.addEventListener("click", function (e) {
          var bar = self.querySelector(".st");
          if (!bar) return;
          var r = bar.getBoundingClientRect();
          var t = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * self._duration;
          self.dispatchEvent(new CustomEvent(
            e.metaKey || e.ctrlKey ? "sp-loop-point" : "sp-seek",
            { detail: { t: t }, bubbles: true }));
        });
      }
    });
  };
  stProto.update = function (T) {
    if (!this._segEls) return;
    var self = this;
    if (this._lineEl && this._duration) {
      this._lineEl.style.display = T == null ? "none" : "block";
      if (T != null) {
        this._lineEl.style.left = (100 * T / this._duration).toFixed(2) + "%";
      }
    } else if (T != null && this._duration) {
      var el = document.createElement("div");
      el.className = "st-line";
      var bar = this.querySelector(".st");
      if (bar) { bar.appendChild(el); this._lineEl = el; this.update(T); return; }
    }
    this._segEls.forEach(function (seg, i) {
      var s = self._sections[i];
      seg.classList.toggle("cur", T != null && s && T >= s.start && T < s.end);
    });
  };
  stProto.connectedCallback = function () {
    ensureCss();
    this._render();
  };
  stProto.attributeChangedCallback = function () {
    var self = this;
    if (self._pending || !self.isConnected) return;
    self._pending = true;
    requestAnimationFrame(function () {
      self._pending = false;
      self._render();
    });
  };
  function ST() { return Reflect.construct(HTMLElement, [], ST); }
  ST.prototype = stProto;
  ST.observedAttributes = ["playhead", "loop", "labels"];
  Object.setPrototypeOf(ST, HTMLElement);
  customElements.define("song-timeline", ST);

  // ---- <chord-cards> ------------------------------------------------------
  var ccProto = Object.create(HTMLElement.prototype);
  ccProto._render = function () {
    var self = this;
    whenReady(self, function (song) {
      var L = lib();
      var want = (self.getAttribute("symbols") || "").split(",").map(function (s) {
        return s.trim();
      }).filter(Boolean);
      if (self.getAttribute("symbols") !== null && !want.length) {
        self.innerHTML = "";
        return;
      }
      var max = parseInt(self.getAttribute("max") || "0", 10);
      var current = self.getAttribute("current") || "";
      var syms = want.length ? want : Object.keys(song.canon).sort();
      if (max > 0) syms = syms.slice(0, max);
      var cards = syms.map(function (sym) {
        var c = song.canon[sym];
        if (!c || !c.positions) return "";
        return '<figure' + (sym === current ? ' class="cur"' : "") + ">" +
          L.chordSvg(c.positions, { width: 104, height: 118, rightPad: 24 }) +
          "<figcaption>" + L.esc(sym) + "<small>" + L.esc(c.short) +
          "</small></figcaption></figure>";
      }).join("");
      self.innerHTML = '<div class="cc">' + cards + "</div>";
    });
  };
  ccProto.connectedCallback = function () {
    ensureCss();
    this._render();
  };
  ccProto.attributeChangedCallback = function () {
    var self = this;
    if (self._pending || !self.isConnected) return;
    self._pending = true;
    requestAnimationFrame(function () {
      self._pending = false;
      self._render();
    });
  };
  function CC() { return Reflect.construct(HTMLElement, [], CC); }
  CC.prototype = ccProto;
  CC.observedAttributes = ["symbols", "current", "max"];
  Object.setPrototypeOf(CC, HTMLElement);
  customElements.define("chord-cards", CC);
})();
