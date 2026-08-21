/* report-lib.js — faithful JS port of music_stack/report.py renderers
   (note_roll, staff_svg, chord_svg, tab, name/word rows) + data loader.
   Classic script: window.ReportLib. */
(function () {
  var SHARP = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"];
  var FLAT  = ["C","Db","D","Eb","E","F","Gb","G","Ab","A","Bb","B"];
  function noteName(midi, flats) {
    var n = (flats ? FLAT : SHARP)[((midi % 12) + 12) % 12];
    return n + (Math.floor(midi / 12) - 1);
  }
  function clock(t) {
    t = Math.max(0, Math.floor(+t || 0));
    return Math.floor(t / 60) + ":" + ("0" + (t % 60)).slice(-2);
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;")
      .replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  var SECTION_HUES = { intro: 210, verse: 150, chorus: 345, bridge: 45,
    solo: 280, inst: 280, "break": 25, outro: 265, start: 200 };
  var STANDARD_TUNING = { 1: 64, 2: 59, 3: 55, 4: 50, 5: 45, 6: 40 };
  var CANON = {"A5":"x022xx","A7":"5752xx","A7sus4":"x000x0","Am":"x0221x",
    "Asus4":"x00755","B":"7xxx07","C5":"x3x01x","C5/G":"33x0xx","C6/G":"3x2215",
    "Csus2/D":"xx001x","Csus4":"x3301x","D":"xx077x","D/F":"153x32","D5":"xx023x",
    "D5/A":"x002xx","D7/A":"55753x","D7sus4/A":"5555x5","Dm7/A":"5535xx",
    "Dsus2/E":"0002xx","Dsus4/A":"5552xx","F":"13321x","F/C":"x3x21x",
    "F5":"133xxx","Fmaj7":"133210","Fsus2":"13301x","G":"35543x","G5":"3x00xx",
    "G5/D":"xx0x33","Gadd9/D":"x5520x","Gsus2":"3x52xx","Gsus4":"35553x"};
  function shorthandPositions(short) {
    var out = [];
    for (var i = 0; i < 6; i++) {
      var ch = short[i];
      if (ch === "x" || ch == null) continue;
      out.push({ string: 6 - i, fret: parseInt(ch, 10) });
    }
    return out;
  }

  // -- chord box SVG (port of chord_svg) --------------------------------
  function chordSvg(positions, opts) {
    opts = opts || {};
    var width = opts.width || 110, height = opts.height || 132;
    var rightPad = opts.rightPad || 12;
    var byString = {}, fretted = [];
    positions.forEach(function (p) {
      byString[p.string] = p.fret;
      if (p.fret > 0) fretted.push(p.fret);
    });
    var base = fretted.length && Math.min.apply(null, fretted) > 1
      ? Math.min.apply(null, fretted) : 1;
    var nFrets = Math.max(5, fretted.length
      ? (Math.max.apply(null, fretted) - base + 1) : 5);
    var left = 18, top = 26, right = width - rightPad, bottom = height - 10;
    var stringX = {}, s;
    for (s = 1; s <= 6; s++) stringX[s] = left + (right - left) * (6 - s) / 5;
    var fretY = [];
    for (var i = 0; i <= nFrets; i++) fretY.push(top + (bottom - top) * i / nFrets);
    var p = ['<svg class="chordbox" viewBox="0 0 ' + width + " " + height +
      '" xmlns="http://www.w3.org/2000/svg">'];
    if (base === 1) {
      p.push('<line x1="' + left + '" y1="' + top + '" x2="' + right +
        '" y2="' + top + '" class="nut"/>');
    } else {
      p.push('<text x="' + (right + 2) + '" y="' + (top + 12) +
        '" class="basefret">' + base + "fr</text>");
    }
    fretY.forEach(function (y) {
      p.push('<line x1="' + left + '" y1="' + y.toFixed(1) + '" x2="' + right +
        '" y2="' + y.toFixed(1) + '" class="fret"/>');
    });
    for (s = 1; s <= 6; s++) {
      p.push('<line x1="' + stringX[s].toFixed(1) + '" y1="' + top + '" x2="' +
        stringX[s].toFixed(1) + '" y2="' + bottom + '" class="string"/>');
    }
    for (s = 6; s >= 1; s--) {
      var x = stringX[s], fret = byString[s];
      if (fret === undefined) {
        p.push('<text x="' + x.toFixed(1) + '" y="' + (top - 8) +
          '" class="mark">x</text>');
      } else if (fret === 0) {
        p.push('<circle cx="' + x.toFixed(1) + '" cy="' + (top - 11) +
          '" r="4.5" class="open"/>');
      } else {
        var row = fret - base;
        var cy = (fretY[row] + fretY[row + 1]) / 2;
        p.push('<circle cx="' + x.toFixed(1) + '" cy="' + cy.toFixed(1) +
          '" r="6.5" class="dot"/>');
      }
    }
    p.push("</svg>");
    return p.join("");
  }

  // -- piano roll (port of note_roll) ------------------------------------
  function noteRoll(events, start, end, opts) {
    opts = opts || {};
    var width = opts.width || 1000, row = opts.row || 8;
    var span = Math.max(end - start, 0.001);
    var notes = (events || []).filter(function (e) {
      return e.start < end && e.end > start;
    });
    if (!notes.length) return "";
    var lo = Math.min.apply(null, notes.map(function (n) { return n.midi; })) - 1;
    var hi = Math.max.apply(null, notes.map(function (n) { return n.midi; })) + 1;
    var height = (hi - lo + 1) * row;
    var p = ['<svg class="roll" viewBox="0 0 ' + width + " " + height +
      '" width="100%"' + (opts.fixedHeight ? ' height="' + height + '"' : "") +
      ' preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">'];
    for (var m = lo; m <= hi; m++) {
      if (m % 12 !== 0) continue;
      var y = (hi - m) * row;
      p.push('<line x1="0" y1="' + y + '" x2="' + width + '" y2="' + y +
        '" class="octave"/><text x="4" y="' + (y - 2) + '" class="octlabel">' +
        noteName(m) + "</text>");
    }
    notes.forEach(function (n) {
      var t0 = Math.max(n.start, start), t1 = Math.min(n.end, end);
      var x = (t0 - start) / span * width;
      var w = Math.max((t1 - t0) / span * width, 3);
      var y2 = (hi - n.midi) * row;
      var op = n.velocity == null ? 0.85
        : 0.35 + 0.65 * Math.max(0, Math.min(n.velocity / 127, 1));
      p.push('<rect class="nr" data-midi="' + n.midi + '" data-start="' +
        round2(n.start) + '" data-dur="' +
        Math.max(round2(n.end - n.start), 0.05) + '" x="' + x.toFixed(1) +
        '" y="' + (y2 + 1) + '" width="' + w.toFixed(1) + '" height="' +
        (row - 2) + '" rx="2" opacity="' + op.toFixed(2) + '"><title>' +
        esc(noteName(n.midi)) + " · " + (Math.round(n.start * 10) / 10) +
        "s</title></rect>");
    });
    p.push("</svg>");
    return p.join("");
  }
  function round2(x) { return Math.round(x * 100) / 100; }

  // -- name columns (port of name_columns / _names_row) ------------------
  function nameColumns(events, windowS) {
    windowS = windowS == null ? 0.08 : windowS;
    var sorted = (events || []).slice().sort(function (a, b) {
      return a.start - b.start || a.midi - b.midi;
    });
    var cols = [];
    sorted.forEach(function (e) {
      if (cols.length && e.start - cols[cols.length - 1].start <= windowS) {
        cols[cols.length - 1].midis.push(e.midi);
        cols[cols.length - 1].end = Math.max(cols[cols.length - 1].end, e.end);
      } else {
        cols.push({ start: e.start, end: e.end, midis: [e.midi] });
      }
    });
    return cols;
  }
  function namesRow(events, start, end) {
    var cols = nameColumns(events);
    if (!cols.length) return "";
    var span = Math.max(end - start, 0.001);
    var out = cols.map(function (col) {
      var names = col.midis.slice().sort(function (a, b) { return b - a; })
        .map(function (m) { return "<i>" + esc(noteName(m, true)) + "</i>"; })
        .join("");
      var left = Math.max(0, Math.min((col.start - start) / span * 100, 100));
      return '<span class="ncol" style="left:' + left.toFixed(2) +
        '%" data-start="' + round2(col.start) + '" data-end="' +
        round2(col.end) + '">' + names + "</span>";
    });
    return '<div class="names namesline">' + out.join("") + "</div>";
  }

  // -- seq mapping (port of _seq_x / seqPos) ------------------------------
  function seqPos(times, xs, t, lead, colw) {
    lead = lead == null ? 2 : lead; colw = colw == null ? 4 : colw;
    var idx = 0;
    for (var i = 0; i < times.length; i++) {
      if (times[i] <= t) idx = i; else break;
    }
    var frac = 0;
    if (idx + 1 < times.length && times[idx + 1] > times[idx]) {
      frac = Math.max(0, Math.min(1, (t - times[idx]) / (times[idx + 1] - times[idx])));
    }
    if (xs && xs.length === times.length) {
      var x = xs[idx];
      if (idx + 1 < xs.length) x += frac * (xs[idx + 1] - xs[idx]);
      return { v: x, unit: "px" };
    }
    return { v: lead + colw / 2 + (idx + frac) * colw, unit: "ch" };
  }

  // -- word timing (port of word_segments / _words_row) -------------------
  function wordSegments(segments, onsets, snap) {
    snap = snap == null ? 0.55 : snap;
    onsets = (onsets || []).map(Number).sort(function (a, b) { return a - b; });
    var out = [];
    (segments || []).forEach(function (seg, lineNo) {
      if (seg.words && seg.words.length) {
        seg.words.forEach(function (w) {
          out.push({ start: w.start, end: w.end, text: w.text, line: lineNo });
        });
        return;
      }
      var words = String(seg.text || "").split(/\s+/).filter(Boolean);
      if (!words.length) return;
      var start = +seg.start, end = +seg.end;
      if (!isFinite(start) || !isFinite(end)) return;
      var lineOn = onsets.filter(function (o) { return o >= start && o <= end; });
      var sungEnd = end;
      if (lineOn.length) {
        sungEnd = Math.min(end, Math.max(lineOn[lineOn.length - 1] + 0.6, start + 0.5));
      }
      var span = Math.max(sungEnd - start, 0);
      var weights = words.map(function (w) { return w.length + 1; });
      var total = weights.reduce(function (a, b) { return a + b; }, 0);
      var starts = [], t = start;
      weights.forEach(function (w) { starts.push(t); t += span * w / total; });
      if (lineOn.length) {
        var floor = start;
        starts = starts.map(function (est) {
          var near = lineOn.reduce(function (a, o) {
            return Math.abs(o - est) < Math.abs(a - est) ? o : a;
          }, lineOn[0]);
          if (Math.abs(near - est) <= snap) est = near;
          est = Math.max(est, floor);
          floor = est + 0.01;
          return est;
        });
      }
      words.forEach(function (w, i) {
        var wEnd = i + 1 < words.length ? starts[i + 1] : sungEnd;
        out.push({ start: round2(starts[i]),
          end: round2(Math.max(wEnd, starts[i] + 0.05)), text: w, line: lineNo });
      });
    });
    return out;
  }
  // Word timing synced to the sung performance. Line-level Whisper spans are
  // often padded with instrumental time on either side, and the vocal-stem
  // transcription carries instrumental bleed. So per line: (1) shrink the span
  // to a window sized by text length, slid to where sustained vocal-range
  // notes are densest (duration-weighted, biased late); (2) spread words by
  // character weight inside it; (3) snap each word to the nearest real vocal
  // attack, kept monotonic.
  function wordSegmentsSynced(segments, voiceNotes) {
    var clean = (voiceNotes || []).filter(function (n) {
      return n.midi >= 45 && n.midi <= 84 &&
        (n.velocity == null || n.velocity >= 50) && (n.end - n.start) >= 0.09;
    }).sort(function (a, b) { return a.start - b.start; });
    var onsets = clean.map(function (n) { return n.start; });
    function sungWeight(a, b) {
      var acc = 0;
      clean.forEach(function (n) {
        if (n.start >= a && n.start <= b) acc += Math.min(n.end - n.start, 1);
      });
      return acc;
    }
    var out = [];
    var floorT = 0;
    (segments || []).forEach(function (seg, lineNo) {
      if (seg.words && seg.words.length) {
        seg.words.forEach(function (w) {
          out.push({ start: w.start, end: w.end, text: w.text, line: lineNo });
        });
        floorT = seg.words[seg.words.length - 1].start + 0.2;
        return;
      }
      var words = String(seg.text || "").split(/\s+/).filter(Boolean);
      if (!words.length) return;
      var rawStart = +seg.start, rawEnd = +seg.end;
      if (!isFinite(rawStart) || !isFinite(rawEnd)) return;
      var lo = Math.max(rawStart, floorT), hi = Math.max(rawEnd, lo + 0.6);
      var dur = Math.min(Math.max(String(seg.text).length / 11, 2.2), hi - lo);
      if (hi - lo - dur > 1.5) {
        // grossly padded span: slide a text-sized window to the densest
        // stretch of sustained vocal notes (bias late — padding is usually
        // leading silence or trailing ring-out)
        var cands = [lo].concat(onsets.filter(function (o) {
          return o >= lo && o <= hi - dur;
        }));
        var best = lo, bestScore = -1;
        cands.forEach(function (c) {
          var sc = sungWeight(c, c + dur) + ((c - lo) / (hi - dur - lo)) * 0.8;
          if (sc > bestScore + 1e-9) { bestScore = sc; best = c; }
        });
        lo = best;
        hi = best + dur;
      }
      var on = onsets.filter(function (o) { return o >= lo - 0.1 && o <= hi; });
      var sungStart = lo, sungEnd = hi;
      if (on.length) {
        sungStart = Math.max(lo, on[0] - 0.05);
        sungEnd = Math.min(hi + 0.3, on[on.length - 1] + 0.65);
      }
      var weights = words.map(function (w) { return w.length + 1; });
      var total = weights.reduce(function (a, b) { return a + b; }, 0);
      var span = Math.max(sungEnd - sungStart, 0.5);
      var starts = [], t = sungStart;
      weights.forEach(function (w) { starts.push(t); t += span * w / total; });
      var fl = sungStart - 0.01;
      starts = starts.map(function (est) {
        if (on.length) {
          var near = on.reduce(function (a, o) {
            return Math.abs(o - est) < Math.abs(a - est) ? o : a;
          }, on[0]);
          if (Math.abs(near - est) <= 0.45) est = near;
        }
        est = Math.max(est, fl + 0.01);
        fl = est;
        return est;
      });
      words.forEach(function (w, i) {
        var wEnd = i + 1 < words.length ? starts[i + 1]
          : Math.min(sungEnd + 0.25, starts[i] + 0.9);
        out.push({ start: round2(starts[i]),
          end: round2(Math.max(wEnd, starts[i] + 0.05)), text: w, line: lineNo });
      });
      floorT = starts[starts.length - 1] + 0.2;
    });
    return out;
  }
  function wordsRow(segments, start, end, opts) {
    opts = opts || {};
    var span = Math.max(end - start, 0.001);
    var inside = (segments || []).filter(function (s) {
      return s.start < end && s.end > start;
    });
    if (!inside.length) return "";
    var out = inside.map(function (seg) {
      var left;
      if (opts.times) {
        var pos = seqPos(opts.times, opts.xs, seg.start,
          opts.lead == null ? 2 : opts.lead, opts.colw == null ? 4 : opts.colw);
        left = pos.v.toFixed(1) + pos.unit;
      } else {
        left = Math.max(0, Math.min((seg.start - start) / span * 100, 100))
          .toFixed(2) + "%";
      }
      return '<span class="word' + ((seg.line || 0) % 2 ? " l1" : "") +
        '" style="left:' + left + '" data-start="' + seg.start +
        '" data-end="' + seg.end + '"><i>' + esc(seg.text) + "</i></span>";
    });
    return '<div class="words">' + out.join("") + "</div>";
  }

  // -- grand staff (port of staff_svg, incl. rhythm layer) ----------------
  var PC_DIATONIC = { 0: [0, ""], 1: [1, "♭"], 2: [1, ""], 3: [2, "♭"],
    4: [2, ""], 5: [3, ""], 6: [4, "♭"], 7: [4, ""], 8: [5, "♭"], 9: [5, ""],
    10: [6, "♭"], 11: [6, ""] };
  function diatonic(midi) {
    var la = PC_DIATONIC[((midi % 12) + 12) % 12];
    return [(Math.floor(midi / 12) - 1) * 7 + la[0], la[1]];
  }
  function durClass(b) {
    if (b >= 3.5) return "whole";
    if (b >= 1.5) return "half";
    if (b >= 0.75) return "quarter";
    if (b >= 0.375) return "eighth";
    return "sixteenth";
  }
  function median(a) {
    var s = a.slice().sort(function (x, y) { return x - y; });
    var m = Math.floor(s.length / 2);
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }
  function mode(a) {
    var c = {}, best = a[0];
    a.forEach(function (v) {
      c[v] = (c[v] || 0) + 1;
      if (c[v] > (c[best] || 0)) best = v;
    });
    return best;
  }
  function bisectRight(arr, t) {
    var lo = 0, hi = arr.length;
    while (lo < hi) {
      var mid = (lo + hi) >> 1;
      if (t < arr[mid]) hi = mid; else lo = mid + 1;
    }
    return lo;
  }
  function staffSvg(events, start, end, opts) {
    opts = opts || {};
    var colStep = opts.colStep || 26, gutter = opts.gutter || 48;
    var cols = nameColumns((events || []).filter(function (e) {
      return e.start < end && e.end > start;
    }));
    if (!cols.length) return null;
    var beats = (opts.beats || []).map(Number);
    var downbeats = (opts.downbeats || []).map(Number);
    var rhythm = null;
    if (beats.length >= 2) {
      var diffs = [];
      for (var i = 1; i < beats.length; i++) {
        if (beats[i] > beats[i - 1]) diffs.push(beats[i] - beats[i - 1]);
      }
      var beatLen = diffs.length ? median(diffs) : 0;
      if (beatLen > 0) {
        var perBar = null;
        if (downbeats.length >= 2) {
          var counts = [];
          for (var d = 1; d < downbeats.length; d++) {
            var c = beats.filter(function (b) {
              return b >= downbeats[d - 1] && b < downbeats[d];
            }).length;
            if (c > 0) counts.push(c);
          }
          if (counts.length) perBar = mode(counts);
        }
        rhythm = { beatLen: beatLen, perBar: perBar };
      }
    }
    var step = 4;
    var trebleLines = [30, 32, 34, 36, 38], bassLines = [18, 20, 22, 24, 26];
    var allD = [];
    cols.forEach(function (col) {
      col.midis.forEach(function (m) { allD.push(diatonic(m)[0]); });
    });
    var dHi = Math.max(38, Math.max.apply(null, allD)) + 2;
    var dLo = Math.min(18, Math.min.apply(null, allD)) - 2;
    function y(d) { return 8 + (dHi - d) * step; }
    var tsWidth = rhythm && rhythm.perBar ? 18 : 0;
    var xs = cols.map(function (_c, i) { return gutter + 18 + tsWidth + i * colStep; });
    var width = xs[xs.length - 1] + 30;
    var height = y(dLo) + 8;
    var times = cols.map(function (c) { return c.start; });
    var classes = [], measures = [];
    if (rhythm) {
      times.forEach(function (t, i) {
        var nxt = i + 1 < times.length ? times[i + 1]
          : Math.min(end, t + rhythm.beatLen);
        classes.push(durClass((nxt - t) / rhythm.beatLen));
        measures.push(bisectRight(downbeats, t));
      });
    }
    var p = ['<svg class="staff" viewBox="0 0 ' + width + " " + height +
      '" width="' + width + '" height="' + height +
      '" xmlns="http://www.w3.org/2000/svg">'];
    trebleLines.concat(bassLines).forEach(function (d) {
      p.push('<line x1="8" y1="' + y(d) + '" x2="' + (width - 8) + '" y2="' +
        y(d) + '" class="sline"/>');
    });
    p.push('<line x1="8" y1="' + y(38) + '" x2="8" y2="' + y(18) +
      '" class="sline"/>');
    p.push('<text x="10" y="' + (y(30) + 2) + '" class="clef">\uD834\uDD1E</text>');
    p.push('<text x="12" y="' + (y(22) + 1) + '" class="clef bclef">\uD834\uDD22</text>');
    cols.forEach(function (col, ci) {
      var x = xs[ci];
      var headClass = "sn";
      if (rhythm && (classes[ci] === "whole" || classes[ci] === "half")) {
        headClass = "sn open";
      }
      col.midis.forEach(function (midi) {
        var da = diatonic(midi), d = da[0], acc = da[1];
        var ny = y(d), L;
        if (d >= 29) {
          if (d < 30) {
            p.push('<line x1="' + (x - 8) + '" y1="' + y(28) + '" x2="' +
              (x + 8) + '" y2="' + y(28) + '" class="ledger"/>');
          }
          for (L = 40; L <= d; L += 2) {
            p.push('<line x1="' + (x - 8) + '" y1="' + y(L) + '" x2="' +
              (x + 8) + '" y2="' + y(L) + '" class="ledger"/>');
          }
        } else {
          for (L = 28; L >= d; L -= 2) {
            if (L > 26) {
              p.push('<line x1="' + (x - 8) + '" y1="' + y(L) + '" x2="' +
                (x + 8) + '" y2="' + y(L) + '" class="ledger"/>');
            }
          }
          for (L = 16; L >= d; L -= 2) {
            p.push('<line x1="' + (x - 8) + '" y1="' + y(L) + '" x2="' +
              (x + 8) + '" y2="' + y(L) + '" class="ledger"/>');
          }
        }
        if (acc) {
          p.push('<text x="' + (x - 13) + '" y="' + (ny + 3.5) +
            '" class="acc">' + acc + "</text>");
        }
        p.push('<ellipse class="' + headClass + '" data-midi="' + midi +
          '" data-start="' + round2(col.start) + '" cx="' + x.toFixed(1) +
          '" cy="' + ny + '" rx="4.6" ry="3.4"><title>' +
          esc(noteName(midi, true)) + " · " +
          (Math.round(col.start * 10) / 10) + "s</title></ellipse>");
      });
    });
    if (rhythm) {
      if (rhythm.perBar) {
        [[34, 30], [22, 18]].forEach(function (pair) {
          p.push('<text x="' + (gutter + 2) + '" y="' + (y(pair[0]) - 1) +
            '" class="tsig">' + rhythm.perBar + "</text>" +
            '<text x="' + (gutter + 2) + '" y="' + (y(pair[1]) - 1) +
            '" class="tsig">4</text>');
        });
      }
      for (var bi = 1; bi < cols.length; bi++) {
        if (measures[bi] !== measures[bi - 1]) {
          var bx = (xs[bi - 1] + xs[bi]) / 2;
          p.push('<line x1="' + bx.toFixed(1) + '" y1="' + y(38) + '" x2="' +
            bx.toFixed(1) + '" y2="' + y(18) + '" class="barline"/>');
        }
      }
      [[function (d) { return d >= 29; }, 34],
       [function (d) { return d < 29; }, 22]].forEach(function (layer) {
        var pred = layer[0], middle = layer[1];
        var stems = {};
        cols.forEach(function (col, i) {
          var ds = col.midis.map(function (m) { return diatonic(m)[0]; })
            .filter(pred);
          if (!ds.length || classes[i] === "whole") return;
          var ys = ds.map(y);
          var up = ds.reduce(function (a, b) { return a + b; }, 0) / ds.length < middle;
          stems[i] = up
            ? [xs[i] + 4.4, Math.max.apply(null, ys) - 1, Math.min.apply(null, ys) - 24, true]
            : [xs[i] - 4.4, Math.min.apply(null, ys) + 1, Math.max.apply(null, ys) + 24, false];
        });
        var keys = Object.keys(stems).map(Number).sort(function (a, b) { return a - b; });
        var runs = [], cur = [];
        function plainStem(i) {
          var s = stems[i];
          p.push('<line x1="' + s[0].toFixed(1) + '" y1="' + s[1].toFixed(1) +
            '" x2="' + s[0].toFixed(1) + '" y2="' + s[2].toFixed(1) +
            '" class="stem"/>');
        }
        keys.forEach(function (i) {
          if (classes[i] !== "eighth" && classes[i] !== "sixteenth") {
            if (cur.length) { runs.push(cur); cur = []; }
            plainStem(i);
            return;
          }
          var joinable = cur.length && i === cur[cur.length - 1] + 1 &&
            measures[i] === measures[cur[cur.length - 1]] &&
            stems[i][3] === stems[cur[cur.length - 1]][3] &&
            (times[i] - times[cur[cur.length - 1]]) < 0.75 * rhythm.beatLen;
          if (joinable) cur.push(i);
          else { if (cur.length) runs.push(cur); cur = [i]; }
        });
        if (cur.length) runs.push(cur);
        runs.forEach(function (run) {
          var up = stems[run[0]][3];
          if (run.length === 1) {
            var i = run[0], s = stems[i];
            plainStem(i);
            var flip = up ? 1 : -1;
            var flags = classes[i] === "sixteenth" ? 2 : 1;
            for (var k = 0; k < flags; k++) {
              p.push('<line x1="' + s[0].toFixed(1) + '" y1="' +
                (s[2] + flip * k * 5).toFixed(1) + '" x2="' +
                (s[0] + 6.5).toFixed(1) + '" y2="' +
                (s[2] + flip * (k * 5 + 8)).toFixed(1) + '" class="flag"/>');
            }
            return;
          }
          var tips = run.map(function (i) { return stems[i][2]; });
          var beamY = up ? Math.min.apply(null, tips) : Math.max.apply(null, tips);
          run.forEach(function (i) {
            var s = stems[i];
            p.push('<line x1="' + s[0].toFixed(1) + '" y1="' + s[1].toFixed(1) +
              '" x2="' + s[0].toFixed(1) + '" y2="' + beamY.toFixed(1) +
              '" class="stem"/>');
          });
          var x0 = stems[run[0]][0], x1 = stems[run[run.length - 1]][0];
          p.push('<line x1="' + x0.toFixed(1) + '" y1="' + beamY.toFixed(1) +
            '" x2="' + x1.toFixed(1) + '" y2="' + beamY.toFixed(1) +
            '" class="beam"/>');
          var all16 = run.every(function (i) { return classes[i] === "sixteenth"; });
          if (all16) {
            var y2 = beamY + (up ? 5 : -5);
            p.push('<line x1="' + x0.toFixed(1) + '" y1="' + y2.toFixed(1) +
              '" x2="' + x1.toFixed(1) + '" y2="' + y2.toFixed(1) +
              '" class="beam"/>');
          }
        });
      });
    }
    p.push("</svg>");
    return { svg: p.join(""), times: times, xs: xs,
      mids: cols.map(function (c) { return c.midis.slice(); }) };
  }

  // -- guitar tab (port of notes.choose_positions / render_tab) -----------
  function guitarPositions(midi, strings) {
    var out = [];
    strings.forEach(function (s) {
      var fret = midi - STANDARD_TUNING[s];
      if (fret >= 0 && fret <= 15) out.push({ string: s, fret: fret });
    });
    return out.sort(function (a, b) { return a.fret - b.fret; });
  }
  function choosePositions(events, strings, preferFret) {
    var chosen = [], anchor = preferFret == null ? null : preferFret;
    events.forEach(function (e) {
      var options = guitarPositions(e.midi, strings);
      if (!options.length) {
        chosen.push({ midi: e.midi, start: e.start, string: null, fret: null });
        return;
      }
      var pick;
      if (anchor === null) {
        pick = options[0];
        if (pick.fret) anchor = pick.fret;
      } else {
        var lo = anchor - 1, hi = anchor + 4;
        pick = options.reduce(function (a, pOpt) {
          function reach(q) {
            var away = (q.fret === 0 || (q.fret >= lo && q.fret <= hi)) ? 0
              : (q.fret < lo ? lo - q.fret : q.fret - hi);
            return [away, Math.abs(q.fret - anchor), q.fret];
          }
          var ra = reach(a), rb = reach(pOpt);
          for (var i = 0; i < 3; i++) {
            if (rb[i] < ra[i]) return pOpt;
            if (rb[i] > ra[i]) return a;
          }
          return a;
        });
        if (pick.fret && !(pick.fret >= lo && pick.fret <= hi)) {
          anchor = pick.fret > hi ? pick.fret - 4 : pick.fret + 1;
        }
      }
      chosen.push({ midi: e.midi, start: e.start, string: pick.string, fret: pick.fret });
    });
    return chosen;
  }
  var STRING_LABELS = { 1: "e", 2: "B", 3: "G", 4: "D", 5: "A", 6: "E" };
  function renderTab(positioned, strings, width) {
    width = width || 3;
    var ordered = strings.slice().sort(function (a, b) { return a - b; });
    var lines = {};
    ordered.forEach(function (s) { lines[s] = STRING_LABELS[s] + "|"; });
    positioned.forEach(function (note) {
      ordered.forEach(function (s) {
        var cell = repeat("-", width);
        if (note.string === s && note.fret != null) {
          var t = String(note.fret);
          cell = "-" + t + repeat("-", width - 1 - t.length);
        }
        lines[s] += cell + "-";
      });
    });
    return ordered.map(function (s) { return lines[s] + "|"; }).join("\n");
  }
  function renderChordTab(positionLists, width) {
    width = width || 6;
    var rows = {};
    for (var s = 1; s <= 6; s++) rows[s] = STRING_LABELS[s] + "|";
    positionLists.forEach(function (positions) {
      var byString = {};
      (positions || []).forEach(function (pp) { byString[pp.string] = pp.fret; });
      for (var s2 = 1; s2 <= 6; s2++) {
        var fret = byString[s2];
        var cell = fret == null ? repeat("-", width)
          : "-" + fret + repeat("-", width - 1 - String(fret).length);
        rows[s2] += cell + "-";
      }
    });
    var out = [];
    for (var s3 = 1; s3 <= 6; s3++) out.push(rows[s3] + "|");
    return out.join("\n");
  }
  function repeat(ch, n) { return new Array(Math.max(n, 0) + 1).join(ch); }

  // -- progression grouping (port of brief.progression_events) ------------
  function rootOf(sym) {
    var m = /^([A-G][#b]?)/.exec(sym || "");
    return m ? m[1] : sym;
  }
  function progressionEvents(chords, sections) {
    if (!chords || !chords.length) return [];
    var spans = (sections || []).map(function (s) {
      return [s.label, +s.start, +s.end];
    });
    if (!spans.length) spans = [[null, 0, Infinity]];
    var grouped = [];
    spans.forEach(function (span) {
      var label = span[0], start = span[1], end = span[2];
      var runs = [];
      chords.forEach(function (c) {
        if (c.start == null || !c.symbol) return;
        var t0 = +c.start, t1 = +(c.end || c.start);
        if (t0 >= start && t0 < end) {
          var root = rootOf(c.symbol);
          if (runs.length && runs[runs.length - 1][0] === root) {
            runs[runs.length - 1][1].push(c.symbol);
            runs[runs.length - 1][3] = Math.max(runs[runs.length - 1][3], t1);
          } else {
            runs.push([root, [c.symbol], t0, t1]);
          }
        }
      });
      var events = runs.map(function (run) {
        var counts = {}, best = run[1][0];
        run[1].forEach(function (sym) {
          counts[sym] = (counts[sym] || 0) + 1;
          if (counts[sym] > counts[best]) best = sym;
        });
        return [best, run[2], run[3]];
      });
      if (events.length) {
        grouped.push({ label: label, start: start,
          end: end === Infinity ? events[events.length - 1][2] : end,
          events: events });
      }
    });
    return grouped;
  }
  function canonicalShapes(chords) {
    // Textbook grips from the brief when known; else most frequent detected.
    var counts = {}, sample = {};
    (chords || []).forEach(function (c) {
      if (!c.symbol || !c.short) return;
      var key = c.symbol + "\u0000" + c.short;
      counts[key] = (counts[key] || 0) + 1;
      if (!sample[key] && c.pos) {
        sample[key] = c.pos.map(function (t) { return { string: t[0], fret: t[1] }; });
      }
    });
    var best = {};
    Object.keys(counts).forEach(function (key) {
      var parts = key.split("\u0000");
      if (!best[parts[0]] || counts[key] > best[parts[0]].n) {
        best[parts[0]] = { short: parts[1], n: counts[key], key: key };
      }
    });
    var out = {};
    Object.keys(best).forEach(function (sym) {
      if (CANON[sym]) {
        out[sym] = { short: CANON[sym], positions: shorthandPositions(CANON[sym]) };
      } else {
        out[sym] = { short: best[sym].short,
          positions: sample[best[sym].key] || shorthandPositions(best[sym].short) };
      }
    });
    return out;
  }

  // -- data loading --------------------------------------------------------
  var songPromise = null;
  function loadSong(url) {
    if (songPromise) return songPromise;
    // Integration path: a generated report embeds the payload inline as
    // window.SONG = {...}; the fetch is only for the prototype environment.
    var src = window.SONG
      ? Promise.resolve(window.SONG)
      : fetch(url || "data/song.json").then(function (r) { return r.json(); });
    songPromise = src.then(function (raw) {
      function normNotes(list) {
        return (list || []).map(function (n) {
          return { start: n[0], end: n[1], midi: n[2], velocity: n[3] };
        });
      }
      function normChords(list) {
        return (list || []).map(function (c) {
          return { symbol: c.symbol, start: c.start, end: c.end, short: c.short,
            pos: c.pos };
        });
      }
      var song = {
        title: raw.title, bpm: raw.bpm, duration: raw.duration,
        codec: raw.codec, sampleRate: raw.sample_rate, channels: raw.channels,
        arrangement: raw.arrangement, missing: raw.missing || [],
        sections: raw.sections || [], beats: raw.beat_times || [],
        downbeats: raw.downbeat_times || [],
        lyricSegments: raw.lyric_segments || [],
        fromIsolatedVocal: raw.from_isolated_vocal,
        chords: normChords(raw.chords), notes: normNotes(raw.notes),
        voiceNotes: raw.voice_notes ? normNotes(raw.voice_notes) : null,
        voiceChords: normChords(raw.voice_chords),
        stems: raw.stems || [], skipped: raw.skipped || []
      };
      // Prefer the server-computed canon: Python's textbook_shape() covers
      // arbitrary chords, while the local CANON table is only a snapshot.
      if (raw.canon) {
        var canon = {};
        Object.keys(raw.canon).forEach(function (sym) {
          var c = raw.canon[sym];
          canon[sym] = { short: c.short,
            positions: (c.pos || []).map(function (t) {
              return { string: t[0], fret: t[1] };
            }) };
        });
        song.canon = canon;
      } else {
        song.canon = canonicalShapes(song.chords);
      }
      song.panels = progressionEvents(song.chords, song.sections);
      var voiceBySpan = {};
      progressionEvents(song.voiceChords, song.sections).forEach(function (g) {
        voiceBySpan[g.label + "@" + g.start] = g.events;
      });
      song.voiceBySpan = voiceBySpan;
      var onsets = (song.voiceNotes || []).map(function (n) { return n.start; });
      song.words = wordSegments(song.lyricSegments, onsets);
      song.wordsSynced = wordSegmentsSynced(song.lyricSegments, song.voiceNotes || []);
      song.questions = raw.questions || [];
      song.normFile = raw.norm_file || null;
      return song;
    });
    return songPromise;
  }

  // -- simulated transport + synth (WebAudio) ------------------------------
  function SimPlayer(duration) {
    this.duration = duration;
    this._t = 0;
    this.paused = true;
    this.playbackRate = 1;
    this.preservesPitch = true;
    this._listeners = {};
    this._last = null;
  }
  SimPlayer.prototype = {
    _tick: function (now) {
      var self = this;
      if (self.paused) { self._last = null; return; }
      if (self._last != null) {
        self._t += (now - self._last) / 1000 * self.playbackRate;
        if (self._t >= self.duration) { self._t = self.duration; self.paused = true; }
        self._emit("timeupdate");
      }
      self._last = now;
      requestAnimationFrame(function (n) { self._tick(n); });
    },
    play: function () {
      if (!this.paused) return;
      this.paused = false;
      this._last = null;
      var self = this;
      requestAnimationFrame(function (n) { self._tick(n); });
      this._emit("play");
    },
    pause: function () { this.paused = true; this._emit("pause"); },
    addEventListener: function (ev, fn) {
      (this._listeners[ev] = this._listeners[ev] || []).push(fn);
    },
    _emit: function (ev) {
      (this._listeners[ev] || []).forEach(function (fn) { fn(); });
    }
  };
  Object.defineProperty(SimPlayer.prototype, "currentTime", {
    get: function () { return this._t; },
    set: function (v) {
      this._t = Math.max(0, Math.min(this.duration, +v || 0));
      this._emit("timeupdate");
    }
  });

  var audioCtx = null;
  function ctx() {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === "suspended") audioCtx.resume();
    return audioCtx;
  }
  function previewTone(midis) {
    var ac;
    try { ac = ctx(); } catch (err) { return; }
    var now = ac.currentTime;
    midis.forEach(function (m, i) {
      var at = now + i * 0.035;
      var osc = ac.createOscillator(), filter = ac.createBiquadFilter(),
        gain = ac.createGain();
      osc.type = "triangle";
      osc.frequency.value = 440 * Math.pow(2, (m - 69) / 12);
      filter.type = "lowpass"; filter.frequency.value = 2400;
      gain.gain.setValueAtTime(0.0001, at);
      gain.gain.exponentialRampToValueAtTime(0.28 / Math.sqrt(midis.length), at + 0.012);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + 1.5);
      osc.connect(filter); filter.connect(gain); gain.connect(ac.destination);
      osc.start(at); osc.stop(at + 1.6);
    });
  }
  // Renders the transcription as synth in sync with a SimPlayer clock.
  function SynthFollow(player, notes, opts) {
    opts = opts || {};
    var horizon = 0.25, timer = null, scheduled = {}, comp = null, lastT = -1;
    function bus(ac) {
      if (!comp) {
        comp = ac.createDynamicsCompressor();
        var g = ac.createGain(); g.gain.value = opts.gain || 0.6;
        comp.connect(g); g.connect(ac.destination);
      }
      return comp;
    }
    function loop() {
      if (player.paused) return;
      if (opts.enabled && !opts.enabled()) return;
      var ac;
      try { ac = ctx(); } catch (err) { return; }
      var t = player.currentTime, rate = player.playbackRate || 1;
      if (t < lastT - 0.05) scheduled = {};   // seek back: allow re-strike
      lastT = t;
      notes.forEach(function (n, i) {
        if (n.start < t - 0.02 || n.start > t + horizon * rate) return;
        if (scheduled[i]) return;
        scheduled[i] = true;
        var at = ac.currentTime + Math.max(0, (n.start - t) / rate);
        var dur = Math.max((n.end - n.start) / rate, 0.1);
        var osc = ac.createOscillator(), filter = ac.createBiquadFilter(),
          gain = ac.createGain();
        osc.type = opts.wave || "triangle";
        osc.frequency.value = 440 * Math.pow(2, (n.midi - 69) / 12);
        filter.type = "lowpass"; filter.frequency.value = 2400;
        var vel = 0.05 + 0.13 * ((n.velocity == null ? 100 : n.velocity) / 127);
        gain.gain.setValueAtTime(0.0001, at);
        gain.gain.exponentialRampToValueAtTime(vel, at + 0.012);
        gain.gain.setValueAtTime(vel, at + Math.max(dur - 0.08, 0.02));
        gain.gain.exponentialRampToValueAtTime(0.0001, at + dur + 0.12);
        osc.connect(filter); filter.connect(gain); gain.connect(bus(ac));
        osc.start(at); osc.stop(at + dur + 0.2);
      });
    }
    player.addEventListener("play", function () {
      if (timer) clearInterval(timer);
      timer = setInterval(loop, 60);
      loop();
    });
    player.addEventListener("pause", function () {
      if (timer) { clearInterval(timer); timer = null; }
    });
    player.addEventListener("timeupdate", function () {
      var t = player.currentTime;
      if (t < lastT - 0.05) { scheduled = {}; lastT = t; }
    });
  }

  window.ReportLib = {
    noteName: noteName, clock: clock, esc: esc, SECTION_HUES: SECTION_HUES,
    wordSegmentsSynced: wordSegmentsSynced,
    STANDARD_TUNING: STANDARD_TUNING, chordSvg: chordSvg, noteRoll: noteRoll,
    nameColumns: nameColumns, namesRow: namesRow, wordSegments: wordSegments,
    wordsRow: wordsRow, staffSvg: staffSvg, seqPos: seqPos,
    choosePositions: choosePositions, renderTab: renderTab,
    renderChordTab: renderChordTab, progressionEvents: progressionEvents,
    canonicalShapes: canonicalShapes, shorthandPositions: shorthandPositions,
    loadSong: loadSong, SimPlayer: SimPlayer, SynthFollow: SynthFollow,
    previewTone: previewTone, ctx: ctx
  };
})();
