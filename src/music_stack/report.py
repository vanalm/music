"""A self-contained HTML report — the closest thing this tool has to a UI.

``analyze`` writes ``report.html`` next to ``brief.md``. Double-click it and
the browser shows the song: an audio player wired to a clickable section
timeline with a live playhead, the lyric as sung, stems, chord shapes as SVG
boxes, and the questions.

Constraints, deliberately:

* **One file, zero dependencies.** Generated with the standard library — no
  frameworks, no CDN, no network requests. It works on an aeroplane and never
  breaks because a host moved.
* **The audio travels with the page when it can.** The player embeds a
  compact AAC preview as a data URI when ffmpeg is present and the result is
  small enough, so the file survives being mailed to a bandmate. Otherwise it
  degrades to a *relative path* into the project folder — and says so.
* **Sparse analysis → sparse page, never a broken one.** Each section renders
  from whatever the brief holds; a missing stage states how to get it.
"""

import base64
import html as _html
import os
import subprocess
import tempfile
from pathlib import Path

from . import audio as audio_mod
from .notes import note_name

#: Section label -> hue, so the timeline is scannable at a glance.
_SECTION_HUES = {
    "intro": 210, "verse": 150, "chorus": 345, "bridge": 45,
    "solo": 280, "inst": 280, "break": 25, "outro": 265,
}


def _esc(text):
    return _html.escape(str(text if text is not None else ""), quote=True)


#: Reference listening, not mixing — keeps a 4-minute song near 3 MB.
PREVIEW_BITRATE = "96k"

#: Cap on the embedded preview before base64 inflation (~4/3 in the page).
MAX_EMBED_BYTES = 12 * 1024 * 1024


def preview_audio(path, *, max_bytes=MAX_EMBED_BYTES):
    """Return ``(data_uri, note)`` for *path*, or ``(None, reason)``.

    Transcodes to AAC first: embedding a 24-bit WAV would produce a page
    hundreds of megabytes wide once base64 inflates it by a third.
    """
    path = Path(path)
    if not path.exists():
        return None, "audio file not found"
    ffmpeg = audio_mod.which("ffmpeg")
    if not ffmpeg:
        return None, "ffmpeg not installed, so no embedded preview"

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "preview.m4a"
        proc = subprocess.run(
            [
                ffmpeg, "-hide_banner", "-loglevel", "error",
                "-nostdin", "-y", "-i", str(path), "-vn",
                "-c:a", "aac", "-b:a", PREVIEW_BITRATE, "-ar", "44100",
                str(out),
            ],
            capture_output=True,
        )
        if proc.returncode != 0 or not out.exists():
            return None, "ffmpeg could not make a preview"
        raw = out.read_bytes()

    if len(raw) > max_bytes:
        return None, "preview is {:.0f} MB, too large to embed".format(
            len(raw) / 1024 / 1024
        )
    return (
        "data:audio/mp4;base64," + base64.b64encode(raw).decode("ascii"),
        "embedded preview ({:.1f} MB)".format(len(raw) / 1024 / 1024),
    )


def _clock(seconds):
    seconds = int(float(seconds or 0))
    return "{:d}:{:02d}".format(seconds // 60, seconds % 60)


# -- chord boxes -----------------------------------------------------------


def chord_svg(positions, *, width=110, height=132):
    """Draw a chord box as inline SVG from voice_chord() positions.

    Strings are vertical lines (low E left), frets horizontal. Fretted notes
    are dots, open strings circles above the nut, unused strings an ``x``.
    """
    by_string = {p["string"]: p["fret"] for p in positions}
    fretted = [f for f in by_string.values() if f and f > 0]
    base = min(fretted) if fretted and min(fretted) > 1 else 1
    # Wide enough for the widest voicing — a detected shape can span more
    # than a textbook's five frets, and must draw rather than crash.
    n_frets = max(5, (max(fretted) - base + 1) if fretted else 5)

    left, top, right, bottom = 18, 26, width - 12, height - 10
    string_x = {
        s: left + (right - left) * (6 - s) / 5.0 for s in range(1, 7)
    }
    fret_y = [
        top + (bottom - top) * i / float(n_frets) for i in range(n_frets + 1)
    ]

    parts = [
        '<svg class="chordbox" viewBox="0 0 {w} {h}" '
        'xmlns="http://www.w3.org/2000/svg">'.format(w=width, h=height)
    ]
    # nut or base-fret label
    if base == 1:
        parts.append(
            '<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" class="nut"/>'.format(
                x1=left, x2=right, y=top
            )
        )
    else:
        parts.append(
            '<text x="{x}" y="{y}" class="basefret">{n}fr</text>'.format(
                x=right + 2, y=top + 12, n=base
            )
        )
    for y in fret_y:
        parts.append(
            '<line x1="{x1}" y1="{y:.1f}" x2="{x2}" y2="{y:.1f}" '
            'class="fret"/>'.format(x1=left, x2=right, y=y)
        )
    for s, x in string_x.items():
        parts.append(
            '<line x1="{x:.1f}" y1="{y1}" x2="{x:.1f}" y2="{y2}" '
            'class="string"/>'.format(x=x, y1=top, y2=bottom)
        )
    for s in range(6, 0, -1):
        x = string_x[s]
        fret = by_string.get(s)
        if fret is None:
            parts.append(
                '<text x="{x:.1f}" y="{y}" class="mark">x</text>'.format(
                    x=x, y=top - 8
                )
            )
        elif fret == 0:
            parts.append(
                '<circle cx="{x:.1f}" cy="{y}" r="4.5" class="open"/>'.format(
                    x=x, y=top - 11
                )
            )
        else:
            row = fret - base
            cy = (fret_y[row] + fret_y[row + 1]) / 2.0
            parts.append(
                '<circle cx="{x:.1f}" cy="{cy:.1f}" r="6.5" '
                'class="dot"/>'.format(x=x, cy=cy)
            )
    parts.append("</svg>")
    return "".join(parts)


def note_roll(events, start, end, *, width=1000, row=8):
    """A piano roll of every note in ``[start, end)`` — the licks included.

    Time runs left to right across the section, pitch bottom to top, one
    rectangle per transcribed note. This is the accuracy-first view: no
    string-assignment guessing, just what was detected, when, at what
    pitch. Hover a note for its name and time; the page script drives a
    playhead across it in sync with the audio.
    """
    span = max(float(end) - float(start), 0.001)
    notes = [
        e for e in events or []
        if float(e["start"]) < end and float(e["end"]) > start
    ]
    if not notes:
        return ""
    lo = min(n["midi"] for n in notes) - 1
    hi = max(n["midi"] for n in notes) + 1
    height = (hi - lo + 1) * row
    parts = [
        '<svg class="roll" viewBox="0 0 {w} {h}" width="100%" '
        'preserveAspectRatio="none" '
        'xmlns="http://www.w3.org/2000/svg">'.format(w=width, h=height)
    ]
    # Octave guide lines with a label at each C.
    for midi in range(lo, hi + 1):
        if midi % 12 != 0:
            continue
        y = (hi - midi) * row
        parts.append(
            '<line x1="0" y1="{y}" x2="{w}" y2="{y}" class="octave"/>'
            '<text x="4" y="{ty}" class="octlabel">{name}</text>'.format(
                y=y, w=width, ty=y - 2, name=note_name(midi)
            )
        )
    for n in notes:
        t0 = max(float(n["start"]), start)
        t1 = min(float(n["end"]), end)
        x = (t0 - start) / span * width
        w = max((t1 - t0) / span * width, 3.0)
        y = (hi - n["midi"]) * row
        velocity = n.get("velocity")
        opacity = 0.85
        if velocity is not None:
            opacity = 0.35 + 0.65 * max(0.0, min(float(velocity) / 127.0, 1.0))
        parts.append(
            '<rect class="nr" x="{x:.1f}" y="{y}" width="{w:.1f}" '
            'height="{h}" rx="2" opacity="{o:.2f}">'
            "<title>{name} · {t}s</title></rect>".format(
                x=x, y=y + 1, w=w, h=row - 2, o=opacity,
                name=_esc(note_name(n["midi"])),
                t=round(float(n["start"]), 1),
            )
        )
    parts.append("</svg>")
    return "".join(parts)


# -- page ------------------------------------------------------------------


def build(result, *, audio_path=None, chords=None):
    """Render an ``analyze`` result (the ``brief.json`` shape) as one page."""
    from . import brief as brief_mod

    stages = result.get("stages") or {}
    structure = (stages.get("structure") or {}).get("summary") or {}
    lyrics = stages.get("lyrics") or {}
    stems = stages.get("stems") or {}
    norm = (stages.get("normalize") or {}).get("summary") or {}
    sections = structure.get("sections") or []
    duration = structure.get("duration_seconds") or norm.get("duration_seconds") or 0

    # -- audio ------------------------------------------------------------
    if audio_path:
        data_uri, note = preview_audio(audio_path)
        if data_uri:
            audio_html = (
                '<audio id="player" controls preload="metadata" '
                'src="{}"></audio>'.format(data_uri)
            )
        else:
            # Fall back to a relative path: report.html sits in the project
            # dir, the normalized WAV one level down. If the exact relative
            # path cannot be derived, the bare filename is still the best
            # guess -- browsers resolve it against the page, and a wrong
            # guess degrades to a silent player, not a broken page.
            audio_src = os.path.basename(str(audio_path))
            project = result.get("project")
            if project:
                try:
                    audio_src = str(Path(audio_path).relative_to(project))
                except ValueError:
                    pass
            audio_html = (
                '<audio id="player" controls preload="metadata" src="{src}">'
                '</audio>'
                '<p class="note">Audio is not embedded ({why}); playback '
                'needs this file to stay next to its project folder.</p>'
            ).format(src=_esc(audio_src), why=_esc(note))
    else:
        audio_html = '<p class="note">No audio available for playback.</p>'

    # -- timeline ---------------------------------------------------------
    if sections and duration:
        seg_parts = []
        for s in sections:
            width = 100.0 * float(s["seconds"]) / float(duration)
            hue = _SECTION_HUES.get(str(s["label"]).lower(), 200)
            seg_parts.append(
                '<div class="seg" data-start="{start}" '
                'style="width:{w:.3f}%;--hue:{h}" '
                'title="{label} · {t0}–{t1}"><span>{label}</span></div>'.format(
                    start=s["start"], w=width, h=hue, label=_esc(s["label"]),
                    t0=_clock(s["start"]), t1=_clock(s["end"]),
                )
            )
        timeline_html = (
            '<div class="timeline" id="timeline">{segs}'
            '<div id="playhead"></div></div>'.format(segs="".join(seg_parts))
        )
    else:
        timeline_html = (
            '<p class="note">No structure analysis yet — install allin1 '
            "(<code>music-stack local doctor</code> has the steps) and re-run "
            "<code>music-stack analyze</code>.</p>"
            '<div style="display:none" id="playhead"></div>'
        )

    # -- facts ------------------------------------------------------------
    facts = []
    if structure.get("bpm"):
        facts.append("<b>{}</b> BPM".format(_esc(structure["bpm"])))
    if duration:
        facts.append("<b>{}</b>".format(_clock(duration)))
    if norm.get("codec"):
        facts.append("{} · {} Hz".format(_esc(norm["codec"]),
                                         _esc(norm.get("sample_rate", "?"))))
    facts_html = " &nbsp;·&nbsp; ".join(facts)

    missing = structure.get("missing") or []
    missing_html = ""
    if missing:
        chips = "".join('<span class="chip">{}</span>'.format(_esc(m))
                        for m in missing)
        missing_html = '<p class="missing">Not present yet: {}</p>'.format(chips)

    # -- lyrics -----------------------------------------------------------
    lyrics_html = ""
    if lyrics.get("text"):
        provenance = (
            "transcribed from the isolated vocal stem"
            if lyrics.get("from_isolated_vocal")
            else "transcribed from the full mix — expect errors where "
                 "instruments mask the vocal"
        )
        lyrics_html = (
            "<h2>Lyrics as sung</h2>"
            '<p class="note">{}</p>'
            '<div class="card-block"><pre class="lyrics">{}</pre>'
            "</div>".format(_esc(provenance), _esc(lyrics["text"]))
        )

    # -- stems ------------------------------------------------------------
    stems_html = ""
    stem_files = stems.get("files") or []
    if stem_files:
        items = "".join(
            '<li><a href="{name}">{name}</a></li>'.format(
                name=_esc(Path(f).name)
            )
            for f in stem_files
        )
        stems_html = '<h2>Stems</h2><ul class="stems">{}</ul>'.format(items)

    # -- chords -----------------------------------------------------------
    if chords is None:
        chords = (stages.get("chords") or {}).get("chords")
    chords_html = ""
    if chords:
        from . import chords as chords_mod

        canon = {
            sym: (short, positions)
            for sym, short, positions in brief_mod.canonical_shapes(chords)
        }
        panels = []
        shown = set()
        norm_file = (stages.get("normalize") or {}).get("file")
        all_notes = (stages.get("chords") or {}).get("notes") or []
        for label, s_start, s_end, events in brief_mod.progression_events(
            chords, sections
        ):
            symbols = [sym for sym, _t0, _t1 in events]
            shown.update(symbols)
            # Chips: one per chord as played — click to hear it, and the
            # one currently sounding lights up during playback.
            chips = "".join(
                '<span class="chip" data-start="{t0}" data-end="{t1}">'
                "{sym}</span>".format(t0=t0, t1=t1, sym=_esc(sym))
                for sym, t0, t1 in events
            )
            roll = note_roll(all_notes, s_start, s_end)
            roll_html = ""
            if roll:
                roll_html = (
                    '<div class="rollwrap" data-start="{t0}" '
                    'data-end="{t1}">{roll}'
                    '<div class="roll-line"></div></div>'.format(
                        t0=s_start, t1=s_end, roll=roll
                    )
                )
            tab = chords_mod.render_chord_tab(
                [
                    {"voicing": {"positions": canon[sym][1]}}
                    if canon.get(sym) and canon[sym][1] else {"voicing": None}
                    for sym in symbols
                ]
            )
            lick = ""
            if norm_file:
                lick = (
                    '<div class="lickrow"><code class="lick">music-stack '
                    "lick --input {} --start {} --end {}</code>"
                    '<button class="copy" type="button">copy</button>'
                    "</div>".format(
                        _esc(norm_file), _clock(s_start), _clock(s_end),
                    )
                )
            hue = _SECTION_HUES.get(str(label or "").lower(), 210)
            panels.append(
                '<details class="panel" data-start="{t0}" data-end="{t1}" '
                'open><summary><span class="seclabel" style="--hue:{hue}">'
                "{label}</span>"
                '<span class="range">{c0}–{c1}</span>'
                '<span class="prog-mini">{mini}</span></summary>'
                '<div class="chips">{chips}</div>'
                "{roll}"
                '<details class="tabfold"><summary>Chord tab chart'
                "</summary><pre class=\"tab\">{tab}</pre></details>"
                "{lick}</details>".format(
                    t0=s_start, t1=s_end, hue=hue,
                    label=_esc(label or "all"),
                    c0=_clock(s_start), c1=_clock(s_end),
                    mini=_esc(" · ".join(symbols[:8])
                              + (" …" if len(symbols) > 8 else "")),
                    chips=chips, roll=roll_html, tab=_esc(tab), lick=lick,
                )
            )
        prog_html = ""
        if panels:
            prog_html = '<div class="progression">{}</div>'.format(
                "".join(panels)
            )
        # One box per chord, the most frequently detected fingering — a
        # hand learning the song wants one shape, not every strum variant.
        cards = []
        for sym in sorted(shown or canon):
            short, positions = canon.get(sym, (None, None))
            if not positions:
                continue
            cards.append(
                '<figure class="card">{svg}<figcaption>{sym}'
                "<small>{short}</small></figcaption></figure>".format(
                    svg=chord_svg(positions),
                    sym=_esc(sym),
                    short=_esc(short),
                )
            )
        if cards or prog_html:
            chords_html = (
                "<h2>Play along</h2>"
                '<p class="note">Chords and every transcribed note, section '
                "by section. Click anywhere in a roll to hear that moment; "
                "hover a note for its name.</p>{prog}"
                "<h3>Chord shapes</h3><div class=\"cards\">{cards}</div>"
            ).format(prog=prog_html, cards="".join(cards))

    # -- questions --------------------------------------------------------
    questions_html = "".join(
        "<li>{}</li>".format(_esc(q)) for q in brief_mod.questions(result)
    )

    skipped = result.get("skipped") or []
    skipped_html = ""
    if skipped:
        skipped_html = (
            '<p class="note">Stages skipped (tool not installed): {}. Run '
            "<code>music-stack local doctor</code>.</p>".format(
                _esc(", ".join(skipped))
            )
        )

    return _TEMPLATE.format(
        title=_esc(result.get("title", "Untitled")),
        facts=facts_html,
        audio=audio_html,
        timeline=timeline_html,
        arrangement=_esc(structure.get("arrangement") or ""),
        missing=missing_html,
        lyrics=lyrics_html,
        stems=stems_html,
        chords=chords_html,
        questions=questions_html,
        skipped=skipped_html,
    )


def write(result, project_dir, *, audio_path=None, chords=None):
    """Write ``report.html`` into *project_dir*; returns its path."""
    project_dir = Path(project_dir)
    out = project_dir / "report.html"
    out.write_text(
        build(result, audio_path=audio_path, chords=chords), encoding="utf-8"
    )
    return out


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  /* A deliberately light, editorial surface: white cards on a warm gray
     page, one indigo accent, hairline borders instead of heavy shadows. */
  :root {{
    --bg: #f6f7f9; --card: #ffffff; --fg: #16181d; --muted: #667085;
    --line: #e4e7ec; --accent: #4f46e5; --accent-soft: #eef0fe;
    --panel: #f2f4f7;
  }}
  * {{ box-sizing: border-box; }}
  html {{ scroll-behavior: smooth; }}
  body {{
    font: 15px/1.6 -apple-system, BlinkMacSystemFont, "SF Pro Text",
      Inter, "Segoe UI", Roboto, sans-serif;
    margin: 0; background: var(--bg); color: var(--fg);
    -webkit-font-smoothing: antialiased;
  }}
  main {{ max-width: 54rem; margin: 0 auto; padding: 1.4rem 1.2rem 4rem; }}
  h1 {{ font-size: 1.55rem; letter-spacing: -.02em; margin: .4rem 0 .1rem; }}
  h2 {{ font-size: .8rem; letter-spacing: .09em; text-transform: uppercase;
        color: var(--muted); margin: 2.6rem 0 .8rem; }}
  h3 {{ font-size: .8rem; letter-spacing: .09em; text-transform: uppercase;
        color: var(--muted); margin: 2rem 0 .8rem; }}
  .facts {{ color: var(--muted); font-size: .88rem; margin-bottom: 1rem; }}
  .facts b {{ color: var(--fg); }}

  .playerbar {{
    position: sticky; top: 0; z-index: 10; background: var(--card);
    border: 1px solid var(--line); border-radius: 14px;
    padding: .8rem 1rem .9rem; margin: 1rem 0 1.6rem;
    box-shadow: 0 1px 2px rgb(16 24 40 / .04),
                0 8px 24px -18px rgb(16 24 40 / .25);
  }}
  audio {{ width: 100%; height: 40px; }}
  .keys {{ color: var(--muted); font-size: .75rem; margin-top: .45rem; }}
  .keys kbd {{
    border: 1px solid var(--line); border-bottom-width: 2px;
    border-radius: 5px; padding: 0 .35rem; font: inherit;
    background: var(--panel);
  }}

  .timeline {{
    position: relative; display: flex; height: 2.6rem; margin-top: .7rem;
    border-radius: 9px; overflow: hidden; cursor: pointer;
  }}
  .seg {{
    display: flex; align-items: center; justify-content: center;
    min-width: 1.4rem; font-size: .68rem; font-weight: 650; color: #fff;
    background: hsl(var(--hue,210) 48% 52%);
    border-right: 1px solid rgb(255 255 255 / .4);
  }}
  .seg:hover {{ filter: brightness(1.12); }}
  .seg span {{ overflow: hidden; text-overflow: ellipsis;
               white-space: nowrap; padding: 0 .3rem; }}
  #playhead {{
    position: absolute; top: 0; bottom: 0; left: 0; width: 2px;
    background: #fff; box-shadow: 0 0 0 1px rgb(16 24 40 / .35);
    pointer-events: none; transition: left .2s linear;
  }}
  .arrangement {{ color: var(--muted); font-size: .82rem; margin-top: .6rem; }}
  .missing {{ font-size: .85rem; color: var(--muted); margin-top: .3rem; }}
  .missing .chip {{ background: #fef3f2; color: #b42318;
    border: 1px solid #fecdca; }}

  .card-block {{
    background: var(--card); border: 1px solid var(--line);
    border-radius: 14px; padding: 1.1rem 1.3rem;
  }}
  .lyrics {{ white-space: pre-wrap; font-size: .92rem; column-gap: 2.4rem;
    margin: 0; font-family: inherit; }}
  @media (min-width: 660px) {{ .lyrics {{ columns: 2; }} }}
  .note {{ font-size: .84rem; color: var(--muted); }}
  .stems {{ columns: 2; padding-left: 1.2rem; margin: 0; }}
  .stems a {{ color: var(--accent); text-decoration: none; }}
  .stems a:hover {{ text-decoration: underline; }}

  .progression .panel {{
    background: var(--card); border: 1px solid var(--line);
    border-radius: 14px; margin: .8rem 0; padding: .9rem 1.1rem;
    transition: border-color .15s, box-shadow .15s;
  }}
  .progression .panel.now {{
    border-color: var(--accent);
    box-shadow: 0 0 0 3px var(--accent-soft);
  }}
  .progression summary {{
    cursor: pointer; display: flex; align-items: baseline; gap: .6rem;
    list-style: none; flex-wrap: wrap;
  }}
  .progression summary::-webkit-details-marker {{ display: none; }}
  .seclabel {{
    font-size: .72rem; font-weight: 700; letter-spacing: .04em;
    text-transform: uppercase; color: #fff; padding: .12rem .6rem;
    border-radius: 999px; background: hsl(var(--hue,210) 48% 52%);
  }}
  .range {{ color: var(--muted); font-size: .8rem;
    font-variant-numeric: tabular-nums; }}
  .prog-mini {{ color: var(--muted); font-size: .8rem; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }}

  .chips {{ margin: .7rem 0 .5rem; display: flex; flex-wrap: wrap;
    gap: .3rem; }}
  .chip {{
    padding: .12rem .6rem; border-radius: 999px; cursor: pointer;
    background: var(--panel); border: 1px solid var(--line);
    font-size: .8rem; font-weight: 600; transition: all .12s;
  }}
  .chip:hover {{ border-color: var(--accent); color: var(--accent); }}
  .chip.now {{ background: var(--accent); border-color: var(--accent);
    color: #fff; }}

  .rollwrap {{ position: relative; margin: .6rem 0; cursor: crosshair;
    border: 1px solid var(--line); border-radius: 9px; overflow: hidden;
    background: linear-gradient(180deg, #fcfcfd, #f8f9fb); }}
  .roll {{ display: block; }}
  .roll .octave {{ stroke: var(--line); stroke-width: 1; }}
  .roll .octlabel {{ fill: var(--muted); font: 600 9px sans-serif; }}
  .roll .nr {{ fill: var(--accent); }}
  .roll .nr:hover {{ fill: #16181d; }}
  .roll-line {{
    position: absolute; top: 0; bottom: 0; left: 0; width: 1.5px;
    background: #e11d48; display: none; pointer-events: none;
  }}

  .tabfold {{ margin: .5rem 0 0; }}
  .tabfold summary {{ cursor: pointer; color: var(--muted);
    font-size: .8rem; }}
  .tab {{ overflow-x: auto; font-size: .78rem; line-height: 1.4;
    margin: .5rem 0 0; background: var(--panel); padding: .7rem .9rem;
    border-radius: 9px; }}
  .lickrow {{ display: flex; gap: .5rem; align-items: center;
    margin-top: .6rem; }}
  .lickrow .lick {{ flex: 1; min-width: 0; overflow-x: auto;
    white-space: nowrap; font-size: .74rem; color: var(--muted); }}
  .copy {{
    border: 1px solid var(--line); background: var(--card);
    border-radius: 7px; padding: .15rem .6rem; font-size: .74rem;
    cursor: pointer; color: var(--muted);
  }}
  .copy:hover {{ border-color: var(--accent); color: var(--accent); }}

  .cards {{ display: grid; gap: .8rem;
    grid-template-columns: repeat(auto-fill, minmax(112px, 1fr)); }}
  .card {{
    margin: 0; padding: .7rem .4rem .5rem; background: var(--card);
    border: 1px solid var(--line); border-radius: 12px; text-align: center;
  }}
  .card figcaption {{ font-weight: 700; font-size: .92rem; }}
  .card small {{ display: block; font-weight: 500; color: var(--muted);
    font-size: .72rem; margin-top: .1rem; }}
  .chordbox {{ width: 100%; max-width: 110px; height: auto; }}
  .chordbox .fret, .chordbox .string {{ stroke: #d0d5dd; stroke-width: 1; }}
  .chordbox .nut {{ stroke: var(--fg); stroke-width: 3; }}
  .chordbox .dot {{ fill: var(--fg); }}
  .chordbox .open {{ fill: none; stroke: var(--fg); stroke-width: 1.5; }}
  .chordbox .mark, .chordbox .basefret {{
    fill: var(--muted); font: 600 11px sans-serif; text-anchor: middle;
  }}
  .chordbox .basefret {{ text-anchor: start; }}
  ul {{ padding-left: 1.2rem; }}
  li {{ margin: .45rem 0; }}
  code {{ background: var(--panel); padding: .1rem .35rem;
          border-radius: 5px; font-size: .85em; }}
</style>
</head>
<body>
<main>
<h1>{title}</h1>
<div class="facts">{facts}</div>
<div class="playerbar">
{audio}
{timeline}
<div class="keys"><kbd>space</kbd> play / pause &nbsp; <kbd>←</kbd>
<kbd>→</kbd> scrub 1s &nbsp; click a section, chord, or note to jump
there</div>
</div>
<div class="arrangement">{arrangement}</div>
{missing}
{chords}
{lyrics}
{stems}
<h2>To finish this</h2>
<ul>{questions}</ul>
{skipped}
</main>
<script>
  (function () {{
    var player = document.getElementById("player");
    var playhead = document.getElementById("playhead");
    var timeline = document.getElementById("timeline");
    if (!player) return;
    document.querySelectorAll(".seg[data-start], .chip[data-start]")
      .forEach(function (el) {{
        el.addEventListener("click", function () {{
          player.currentTime = parseFloat(el.dataset.start);
          player.play();
        }});
      }});
    var timed = document.querySelectorAll(
      ".panel[data-start], .chip[data-start]"
    );
    var rolls = document.querySelectorAll(".rollwrap[data-start]");
    rolls.forEach(function (wrap) {{
      wrap.addEventListener("click", function (e) {{
        var rect = wrap.getBoundingClientRect();
        var frac = (e.clientX - rect.left) / rect.width;
        var t0 = parseFloat(wrap.dataset.start);
        var t1 = parseFloat(wrap.dataset.end);
        player.currentTime = t0 + frac * (t1 - t0);
        player.play();
      }});
    }});
    player.addEventListener("timeupdate", function () {{
      if (playhead && timeline && player.duration) {{
        playhead.style.left =
          (100 * player.currentTime / player.duration) + "%";
      }}
      var t = player.currentTime;
      timed.forEach(function (el) {{
        var on = t >= parseFloat(el.dataset.start) &&
                 t < parseFloat(el.dataset.end);
        el.classList.toggle("now", on);
      }});
      rolls.forEach(function (wrap) {{
        var t0 = parseFloat(wrap.dataset.start);
        var t1 = parseFloat(wrap.dataset.end);
        var line = wrap.querySelector(".roll-line");
        if (!line) return;
        if (t >= t0 && t < t1) {{
          line.style.display = "block";
          line.style.left = (100 * (t - t0) / (t1 - t0)) + "%";
        }} else {{
          line.style.display = "none";
        }}
      }});
    }});
    document.querySelectorAll(".copy").forEach(function (btn) {{
      btn.addEventListener("click", function () {{
        var code = btn.parentElement.querySelector(".lick");
        if (!code || !navigator.clipboard) return;
        navigator.clipboard.writeText(code.textContent).then(function () {{
          btn.textContent = "copied";
          setTimeout(function () {{ btn.textContent = "copy"; }}, 1400);
        }});
      }});
    }});
    document.addEventListener("keydown", function (e) {{
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.code === "Space") {{
        e.preventDefault();
        if (player.paused) player.play(); else player.pause();
      }} else if (e.code === "ArrowRight") {{
        e.preventDefault();
        player.currentTime = Math.min(
          player.duration || player.currentTime + 1,
          player.currentTime + 1
        );
      }} else if (e.code === "ArrowLeft") {{
        e.preventDefault();
        player.currentTime = Math.max(0, player.currentTime - 1);
      }}
    }});
  }})();
</script>
</body>
</html>
"""
