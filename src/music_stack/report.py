"""A single-file HTML report — the visual surface for a project.

Everything else in this package writes to a terminal or to disk. This writes
one `.html` file you double-click: an audio player whose timeline is divided
into the song's actual sections, so clicking "chorus" jumps there; the lyric
as sung; chord shapes drawn as real diagrams; and links to the stems.

**Self-contained on purpose.** No server, no CDN, no build step. The audio is
transcoded to a compact AAC preview and embedded as a data URI, so the file can
be mailed to a bandmate and still work. If ffmpeg is unavailable or the result
would be too large, it degrades to a relative `src` — which works when the HTML
sits beside the audio, and says so rather than showing a silently dead player.

Generated with string templates and stdlib only, consistent with the rest of
the package having no dependencies.
"""

import base64
import html
import json
import subprocess
from pathlib import Path

from . import audio as audio_mod

#: Above this, embedding produces a file too unwieldy to open or mail.
MAX_EMBED_BYTES = 24 * 1024 * 1024

#: Preview encoding. Quality is irrelevant here -- this is for navigation and
#: reference listening, not mixing.
PREVIEW_BITRATE = "96k"

#: Distinct hues per section type, so the timeline reads at a glance.
SECTION_COLORS = {
    "intro": "#7c8ea3", "verse": "#4f8fd6", "chorus": "#e0724e",
    "bridge": "#9b6bc4", "solo": "#d4a03c", "inst": "#5aa88a",
    "break": "#8a8f98", "outro": "#6b7d94", "start": "#8a8f98",
    "end": "#8a8f98",
}
DEFAULT_COLOR = "#7f8794"


def _esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def preview_audio(path, *, max_bytes=MAX_EMBED_BYTES):
    """Return ``(data_uri, note)`` for *path*, or ``(None, reason)``.

    Transcodes to AAC first: embedding a 24-bit WAV would produce a file
    hundreds of megabytes wide once base64 inflates it by a third.
    """
    path = Path(path)
    if not path.exists():
        return None, "audio file not found"
    if not audio_mod.which("ffmpeg"):
        return None, "ffmpeg not installed, so no embedded preview"

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "preview.m4a"
        proc = subprocess.run(
            [
                audio_mod.which("ffmpeg"), "-hide_banner", "-loglevel", "error",
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
        "embedded ({:.1f} MB)".format(len(raw) / 1024 / 1024),
    )


def chord_svg(positions, *, width=104, height=132):
    """Draw a chord box as inline SVG. *positions* is a voicing's list."""
    by_string = {p["string"]: p["fret"] for p in positions}
    fretted = [f for f in by_string.values() if f > 0]
    start = min(fretted) if fretted and max(fretted) > 4 else 1
    frets = 5

    left, top = 22, 26
    cell_w = (width - left - 8) / 5.0
    cell_h = (height - top - 16) / float(frets)

    parts = ['<svg viewBox="0 0 {} {}" class="chord">'.format(width, height)]
    # Six vertical string lines, low E on the left as a player looks down.
    for i in range(6):
        x = left + i * cell_w
        parts.append(
            '<line x1="{x}" y1="{t}" x2="{x}" y2="{b}" class="grid"/>'.format(
                x=x, t=top, b=top + frets * cell_h
            )
        )
    for j in range(frets + 1):
        y = top + j * cell_h
        cls = "nut" if (j == 0 and start == 1) else "grid"
        parts.append(
            '<line x1="{l}" y1="{y}" x2="{r}" y2="{y}" class="{c}"/>'.format(
                l=left, r=left + 5 * cell_w, y=y, c=cls
            )
        )
    if start > 1:
        parts.append(
            '<text x="{x}" y="{y}" class="fretno">{n}</text>'.format(
                x=left - 8, y=top + cell_h * 0.7, n=start
            )
        )

    for index, string in enumerate(range(6, 0, -1)):
        x = left + index * cell_w
        fret = by_string.get(string)
        if fret is None:
            parts.append(
                '<text x="{x}" y="{y}" class="mark">x</text>'.format(x=x, y=top - 8)
            )
        elif fret == 0:
            parts.append(
                '<circle cx="{x}" cy="{y}" r="4" class="open"/>'.format(
                    x=x, y=top - 12
                )
            )
        else:
            offset = fret - start
            if 0 <= offset < frets:
                parts.append(
                    '<circle cx="{x}" cy="{y}" r="6.5" class="dot"/>'.format(
                        x=x, y=top + (offset + 0.5) * cell_h
                    )
                )
    parts.append("</svg>")
    return "".join(parts)


def build(data, *, audio_path=None, chords=None, title=None):
    """Render the report. *data* is a ``brief.json`` payload."""
    stages = data.get("stages") or {}
    structure = (stages.get("structure") or {}).get("summary") or {}
    lyrics = (stages.get("lyrics") or {}).get("text") or ""
    stems = (stages.get("stems") or {}).get("files") or []
    source = (stages.get("normalize") or {}).get("summary") or {}
    sections = structure.get("sections") or []
    title = title or data.get("title") or "Untitled"

    src, audio_note = (None, "no audio")
    if audio_path:
        src, audio_note = preview_audio(audio_path)
        if src is None:
            # Fall back to a sibling path; honest about the caveat.
            src = _esc(Path(audio_path).name)

    total = structure.get("duration_seconds") or source.get("duration_seconds") or 0

    facts = []
    if structure.get("bpm"):
        facts.append(("Tempo", "{} BPM".format(structure["bpm"])))
    if total:
        facts.append(("Length", "{:d}:{:02d}".format(int(total // 60), int(total % 60))))
    if structure.get("section_count"):
        facts.append(("Sections", structure["section_count"]))
    if source.get("sample_rate"):
        facts.append(
            ("Source", "{} · {} Hz".format(source.get("codec", "?"),
                                           source["sample_rate"]))
        )

    return _TEMPLATE.format(
        title=_esc(title),
        facts=_facts_html(facts),
        player=_player_html(src, audio_note),
        timeline=_timeline_html(sections, total),
        sections=_sections_html(sections),
        missing=_missing_html(structure.get("missing") or []),
        lyrics=_lyrics_html(lyrics, (stages.get("lyrics") or {}).get(
            "from_isolated_vocal")),
        chords=_chords_html(chords or []),
        stems=_stems_html(stems),
        legend=_legend_html(sections),
    )


def _facts_html(facts):
    if not facts:
        return ""
    return "".join(
        '<div class="fact"><span class="k">{}</span>'
        '<span class="v">{}</span></div>'.format(_esc(k), _esc(v))
        for k, v in facts
    )


def _player_html(src, note):
    if not src:
        return '<p class="muted">No audio available for this report.</p>'
    return (
        '<audio id="player" controls preload="metadata" src="{src}"></audio>'
        '<p class="muted">{note}</p>'.format(src=src, note=_esc(note))
    )


def _timeline_html(sections, total):
    if not sections or not total:
        return '<p class="muted">No section analysis — install allin1 to get one.</p>'
    blocks = []
    for index, s in enumerate(sections):
        left = 100.0 * s["start"] / total
        width = max(0.4, 100.0 * s["seconds"] / total)
        colour = SECTION_COLORS.get((s["label"] or "").lower(), DEFAULT_COLOR)
        blocks.append(
            '<button class="seg" style="left:{l:.3f}%;width:{w:.3f}%;'
            'background:{c}" data-start="{start}" title="{label} — {clock}">'
            "<span>{label}</span></button>".format(
                l=left, w=width, c=colour, start=s["start"],
                label=_esc(s["label"]), clock=_clock(s["start"]),
            )
        )
    return (
        '<div class="timeline" id="timeline">{blocks}'
        '<div class="playhead" id="playhead"></div></div>'.format(
            blocks="".join(blocks)
        )
    )


def _legend_html(sections):
    labels = []
    for s in sections:
        label = (s.get("label") or "").lower()
        if label and label not in labels:
            labels.append(label)
    if not labels:
        return ""
    return "".join(
        '<span class="lg"><i style="background:{c}"></i>{l}</span>'.format(
            c=SECTION_COLORS.get(l, DEFAULT_COLOR), l=_esc(l)
        )
        for l in labels
    )


def _sections_html(sections):
    if not sections:
        return ""
    rows = "".join(
        '<tr class="row" data-start="{start}"><td><i style="background:{c}"></i>'
        "{label}</td><td>{clock}</td><td>{secs}s</td></tr>".format(
            start=s["start"],
            c=SECTION_COLORS.get((s["label"] or "").lower(), DEFAULT_COLOR),
            label=_esc(s["label"]), clock=_clock(s["start"]), secs=s["seconds"],
        )
        for s in sections
    )
    return (
        "<table><thead><tr><th>Section</th><th>Start</th><th>Length</th>"
        "</tr></thead><tbody>{}</tbody></table>".format(rows)
    )


def _missing_html(missing):
    if not missing:
        return ""
    chips = "".join('<span class="chip">{}</span>'.format(_esc(m)) for m in missing)
    return (
        '<div class="missing"><strong>Not present yet</strong>{}</div>'.format(chips)
    )


def _lyrics_html(text, from_stem):
    if not text:
        return ""
    note = (
        "Transcribed from the isolated vocal stem."
        if from_stem
        else "Transcribed from the full mix — expect errors where instruments "
        "mask the vocal."
    )
    return (
        '<section><h2>Lyrics as sung</h2><p class="muted">{note}</p>'
        "<pre>{text}</pre></section>".format(note=_esc(note), text=_esc(text))
    )


def _chords_html(chords):
    if not chords:
        return ""
    seen, cards = set(), []
    for c in chords:
        shorthand = c.get("shorthand")
        positions = c.get("positions")
        symbol = c.get("symbol") or "?"
        if not positions or shorthand in seen:
            continue
        seen.add(shorthand)
        cards.append(
            '<figure class="card"><figcaption>{sym}<code>{sh}</code>'
            "</figcaption>{svg}</figure>".format(
                sym=_esc(symbol), sh=_esc(shorthand), svg=chord_svg(positions)
            )
        )
    if not cards:
        return ""
    progression = " ".join(
        _esc(c.get("symbol") or "?") for c in chords
    )
    return (
        "<section><h2>Chords</h2>"
        '<p class="prog">{prog}</p><div class="cards">{cards}</div>'
        "</section>".format(prog=progression, cards="".join(cards))
    )


def _stems_html(stems):
    if not stems:
        return ""
    items = "".join(
        '<li><a href="{href}">{name}</a></li>'.format(
            href=_esc(Path(s).name), name=_esc(Path(s).stem)
        )
        for s in stems
    )
    return (
        "<section><h2>Stems</h2><ul class=\"stems\">{}</ul>"
        '<p class="muted">Links are relative — keep this file beside the stems, '
        "or open them from the project folder.</p></section>".format(items)
    )


def _clock(seconds):
    seconds = int(seconds or 0)
    return "{:d}:{:02d}".format(seconds // 60, seconds % 60)


_TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
:root{{--bg:#faf9f7;--fg:#1c1e21;--muted:#6b7280;--line:#e2e0dc;--card:#fff;
--accent:#4f8fd6}}
@media(prefers-color-scheme:dark){{:root{{--bg:#16181c;--fg:#e8e6e3;
--muted:#9aa1ab;--line:#2c2f36;--card:#1e2126}}}}
*{{box-sizing:border-box}}
body{{margin:0;padding:2rem 1.25rem 4rem;background:var(--bg);color:var(--fg);
font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{max-width:820px;margin:0 auto}}
h1{{font-size:2.1rem;margin:0 0 .4rem;letter-spacing:-.02em}}
h2{{font-size:1.05rem;text-transform:uppercase;letter-spacing:.08em;
color:var(--muted);margin:2.5rem 0 .8rem;font-weight:600}}
.facts{{display:flex;flex-wrap:wrap;gap:1.5rem;margin:0 0 1.75rem;
padding-bottom:1.25rem;border-bottom:1px solid var(--line)}}
.fact .k{{display:block;font-size:.72rem;text-transform:uppercase;
letter-spacing:.07em;color:var(--muted)}}
.fact .v{{font-size:1.15rem;font-variant-numeric:tabular-nums}}
audio{{width:100%;margin:.5rem 0}}
.timeline{{position:relative;height:52px;border-radius:8px;overflow:hidden;
background:var(--line);margin:.75rem 0 .5rem}}
.seg{{position:absolute;top:0;height:100%;border:0;cursor:pointer;padding:0;
color:#fff;font:inherit;font-size:.72rem;opacity:.88;transition:opacity .12s}}
.seg:hover{{opacity:1}}
.seg span{{position:absolute;left:6px;top:50%;transform:translateY(-50%);
white-space:nowrap;overflow:hidden;text-shadow:0 1px 2px rgba(0,0,0,.35)}}
.playhead{{position:absolute;top:0;width:2px;height:100%;background:var(--fg);
left:0;pointer-events:none;transition:left .1s linear}}
.legend{{display:flex;gap:1rem;flex-wrap:wrap;font-size:.8rem;
color:var(--muted)}}
.lg i,td i{{display:inline-block;width:10px;height:10px;border-radius:2px;
margin-right:.4rem;vertical-align:baseline}}
table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}}
th{{text-align:left;font-size:.72rem;text-transform:uppercase;
letter-spacing:.06em;color:var(--muted);padding:.4rem 0}}
td{{padding:.45rem 0;border-top:1px solid var(--line)}}
tr.row{{cursor:pointer}}
tr.row:hover td{{color:var(--accent)}}
.missing{{margin-top:1rem;font-size:.9rem}}
.chip{{display:inline-block;margin-left:.4rem;padding:.15rem .6rem;
border:1px dashed var(--muted);border-radius:99px;font-size:.8rem;
color:var(--muted)}}
pre{{white-space:pre-wrap;background:var(--card);border:1px solid var(--line);
border-radius:8px;padding:1rem;font:15px/1.7 ui-monospace,SFMono-Regular,
Menlo,monospace}}
.prog{{font:1.25rem ui-monospace,SFMono-Regular,Menlo,monospace;
letter-spacing:.05em}}
.cards{{display:flex;flex-wrap:wrap;gap:1rem}}
.card{{margin:0;background:var(--card);border:1px solid var(--line);
border-radius:10px;padding:.75rem}}
figcaption{{font-weight:600;margin-bottom:.35rem;display:flex;gap:.5rem;
align-items:baseline}}
figcaption code{{font-size:.78rem;color:var(--muted)}}
.chord{{width:104px;height:132px;display:block}}
.chord .grid{{stroke:var(--muted);stroke-width:1;opacity:.55}}
.chord .nut{{stroke:var(--fg);stroke-width:3.5}}
.chord .dot{{fill:var(--fg)}}
.chord .open{{fill:none;stroke:var(--fg);stroke-width:1.5}}
.chord .mark,.chord .fretno{{fill:var(--muted);font-size:11px;
text-anchor:middle;font-family:inherit}}
.stems{{list-style:none;padding:0;display:flex;gap:.75rem;flex-wrap:wrap}}
.stems a{{display:inline-block;padding:.35rem .8rem;border:1px solid var(--line);
border-radius:99px;text-decoration:none;color:var(--fg);background:var(--card)}}
.muted{{color:var(--muted);font-size:.85rem}}
</style></head><body><main>
<h1>{title}</h1>
<div class="facts">{facts}</div>
<section>{player}{timeline}<div class="legend">{legend}</div></section>
<section><h2>Structure</h2>{sections}{missing}</section>
{lyrics}
{chords}
{stems}
</main>
<script>
(function(){{
  var player=document.getElementById('player');
  var head=document.getElementById('playhead');
  function seek(t){{ if(!player) return;
    player.currentTime=parseFloat(t)||0;
    player.play().catch(function(){{}});
  }}
  document.querySelectorAll('.seg,tr.row').forEach(function(el){{
    el.addEventListener('click',function(){{ seek(el.dataset.start); }});
  }});
  if(player&&head){{
    player.addEventListener('timeupdate',function(){{
      var d=player.duration;
      if(d&&isFinite(d)) head.style.left=(100*player.currentTime/d)+'%';
    }});
  }}
}})();
</script>
</body></html>
"""
