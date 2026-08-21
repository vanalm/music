# CLAUDE.md — orientation for an agent with no prior context

Read this first. It is the map; `README.md` is the user-facing pitch and
`docs/` holds the detail.

## What this is

A local-first play-along toolchain (with a songwriting side). You give it a
song — any recording you want to learn to play, or a rough demo of your own
— and it returns the things you need to play it: chords as played, guitar
tab, sheet music, the sung melody, word-synced lyrics, separated stems, and
the Studio play-along page. **The goal is playing, not transcribing for its
own sake** — features that put a song under the user's hands come first.
When the input is a half-written sketch, the same pass also writes a
songwriting brief: tempo, the arrangement as played, missing sections, and
derived questions.

**It runs on the user's machine. Nothing is uploaded unless a hosted service is
explicitly invoked, and the hosted services are mostly unusable (see below).**

## The one command

```bash
music-stack analyze --input ~/Downloads/vm0043.m4a
```

Scaffolds a project, preserves the original, transcodes a lossless working
copy, runs every analysis stage the machine supports, silently skips the rest,
and writes `projects/<slug>/brief.md` — a one-page songwriting brief with
tempo, arrangement, missing sections, chords as played, lyrics, and derived
questions — plus `report.html`, **the Studio**: a self-contained two-pane
play-along page. Score on the left (one panel per section, switchable
between piano roll, guitar tab with neck positions, grand-staff sheet music
with time signature/bar lines/beamed rhythms from allin1's beat grid, and
chord chart — for the instruments or the sung melody via an
Instrument | Voice toggle); a sticky practice dock on the right (section
timeline, transport, speed pills that slow playback without changing pitch,
the chord under the hand right now with its grip and what's next, a lyric
window that follows playback, the song's shapes). Lyrics ride every chart
word by word — real Whisper word timestamps when present, onset-snapped
interpolation otherwise. Click moves the playhead without autoplay, drag
scrubs the recording through the spot under the pointer, ⌘-click ×2 loops
a passage, ⌥-click sounds a note or moment, ▶ tones plays a section's
transcription as synth at tempo, and a light/dark toggle plus
view/speed/position state persist across openings (localStorage).
The page renders its charts client-side from one inline `window.SONG`
payload; `report.py` inlines `assets/report-lib.js` (chart renderers —
faithful ports of the tested Python reference implementations in
`report.py`) and `assets/score-panel.js` (the `<score-panel>`,
`<song-timeline>`, `<chord-cards>` custom elements). The report embeds a
compact AAC preview as a data URI when ffmpeg is present and small enough;
otherwise it degrades to a relative src and says so.

A machine with only ffmpeg still produces a brief. Each optional tool installed
adds a section.

**Bring your own stems.** Audio files dropped into `<project>/stems/user/`
(from Moises, Suno, anywhere) are used instead of running demucs —
`brief.pick_stem()` recognises the common naming dialects (vocals/vocal/vox,
other/instrumental/guitars/no_vocals) — and a cleaner hosted separation
improves lyrics, the voice trace, and chords downstream. Re-run `analyze`
after dropping them in.

## Command surface

| Command | Needs | Costs |
|---|---|---|
| `doctor` | — | free |
| `local doctor` | — | free |
| `analyze --input F` | ffmpeg; more tools = more sections | free |
| `watch [--once]` | polls `dropbox/`, analyzes drops, files to done/failed | free |
| `report <slug>` | a prior `analyze` run | free |
| `project new/list` | — | free |
| `audio normalize/inspect` | ffmpeg | free |
| `lick --input F --start T --end T` | ffmpeg + basic-pitch | free |
| `local stems` | demucs | free |
| `local structure` | allin1 | free |
| `local lyrics` | any Whisper | free |
| `local notes` | basic-pitch | free |
| `music-ai *` | `MUSIC_AI_API_KEY` | **credits** |
| `kits *` | `KITS_API_KEY` | **credits** |
| `moises auth/introspect/query` | `MOISES_API_KEY` | plan |
| `suno status` | — | free |

Every `local *` and `lick` command takes `--dry-run`, which prints the exact
argv without executing. Use it when a flag might have drifted.

## External tools: detected, never imported

The package has **zero third-party runtime dependencies**. `pip install -e .`
pulls nothing. Heavy ML tools are external programs looked up on `PATH` at call
time (`shutil.which`), exactly like ffmpeg. A missing tool yields an install
hint, never an `ImportError`.

`./scripts/install-ml-tools.sh` installs everything below with the right
versions and Pythons — run it once, re-running is safe. The per-tool detail:

| Tool | Gives | Install |
|---|---|---|
| ffmpeg | conversion, trimming | `brew install ffmpeg` |
| demucs | stems | `pip install -U demucs` |
| allin1 | tempo, beats, labelled sections | madmom from git + `natten==0.14.6`, Python ≤ 3.11 — use the script |
| Whisper | lyrics | any of `mlx_whisper`, `whisper-cli`, `whisper-cpp`, `whisper` |
| basic-pitch | notes and chords | `pip install -U basic-pitch` — **Python ≤ 3.11 only** (pins numpy<1.24) |

Tools that need an older Python live in one shared venv
(`~/.venvs/music-tools`, Python 3.11) with their binaries symlinked onto
PATH — the package never imports them, so where they live is irrelevant.

`local_tools.find_whisper()` detects whichever Whisper packaging is present and
emits the right flag dialect for it. Do not assume `openai-whisper`.

**Never add a runtime dependency to the core.** Optional extras only.

## Hosted services are mostly closed — do not send the user shopping

Verified by probing the live endpoints:

- **Music.AI** has no self-serve signup. Its login page offers only "Get
  Enterprise access"; Contact Sales redirects individuals to moises.ai.
  Third-party articles describing a free tier are **stale**. The REST adapter
  is built, tested, and correct (`Authorization: <key>`, raw, no `Bearer` —
  confirmed empirically) but dormant.
- **No Moises consumer plan grants an API key.** Not Free, not Premium, not
  Pro. Do not recommend buying Pro for API access.
- The Moises **GraphQL** endpoint (`api.moises.ai/graphql`) is live but legacy.
  `moises introspect` asks the server for its own schema rather than guessing.
- **Kits AI** does have genuine self-serve signup including a free tier. Two of
  its endpoint paths are flagged `verified=False` in `adapters/kits.py`.
- **Suno** ships inert by design. No guessed endpoints, ever.

The local path is the answer. Reach for a hosted service only if the user
explicitly asks.

## Invariants — do not break these

1. **Zero runtime dependencies in the core.** Optional extras only.
2. **The credential boundary.** `http.api_request` attaches credentials and
   refuses any host outside the calling adapter's `ALLOWED_HOSTS`;
   `storage_request`/`upload_file`/`download_file` attach none, ever. Both
   vendors hand out signed storage URLs, and a shared session with a default
   `Authorization` header would leak the key to Google Cloud Storage. Host
   matching is dot-anchored. Never widen an allow-list to fix a
   `CredentialLeakError` — it means an adapter is pointed somewhere wrong.
3. **Secrets are never printed.** `doctor` shows presence and an 8-char SHA-256
   fingerprint. There is a test asserting output never contains the key.
4. **No guessed endpoints.** Unverified paths carry `verified=False` and a 404
   on one names the line to fix. Unofficial wrappers, cookie extraction, and
   captcha workarounds are out of scope permanently.
5. **`input/` is write-once.** The original take is never modified.

## Musical decisions that look arbitrary but are not

- **Chord grouping needs two thresholds.** A six-string strum is ~100 ms wide
  end to end, so measuring against the group's first onset drops the last
  string; measuring only against the previous note lets a scale run chain into
  one chord. Both apply, and `max_width` defaults to 2.5× `window`.
- **Chord naming leans on the bass.** `A C E G` is *exactly* Am7 and *exactly*
  C6. The note set cannot separate them; only the lowest note can.
- **Scale matching returns a ranked list, not a verdict.** A minor pentatonic
  and its relative major share every note. Scoring uses Jaccard fit — not just
  coverage — because a 7-note scale contains a 5-note one and would always win
  on coverage alone.
- **Voicings are descriptive.** They finger the notes actually detected, not a
  textbook shape, and return `None` when the notes cannot be one hand position.
- **…except in song-level charts, which prefer textbook grips.** The lick path
  keeps descriptive voicings (you asked what was played); the report and brief
  swap in `chords.textbook_shape()` for common chords, because transcription
  noise fingered literally looks like nothing a player would grab. Oddball
  chords still fall back to the detected voicing.
- **MusicXML quantises to a sixteenth grid.** Rubato, swing, and triplets
  notate squarer than played. The MIDI keeps raw timing — prefer it when rhythm
  matters more than reading.

## Testing

```bash
PYTHONPATH=src:tests python3 -m unittest discover -s tests
```

338 tests, no network, no credentials. The ffmpeg round-trips skip themselves
when ffmpeg is absent, so a fresh checkout is green either way.

`tests/fakes.py` fakes **only the socket** — it reuses the real host allow-list
check and the real poll loop, so adapter tests exercise the genuine security
boundary. If you weaken the allow-list, adapter tests fail too.

The suite is fully mocked against the hosted services: it verifies this code's
logic, not vendor behaviour. **No live API call has ever been made from this
repository.** If a real response shape differs from a fixture, fix the adapter
and the fixture together.

## Where to look

| File | Holds |
|---|---|
| `src/music_stack/cli.py` | every command, argparse surface |
| `src/music_stack/brief.py` | the `analyze` pipeline and brief rendering |
| `src/music_stack/local_tools.py` | external tool detection and argv building |
| `src/music_stack/notes.py` | pitch naming, fretboard, scale matching |
| `src/music_stack/chords.py` | grouping, chord naming, voicings, diagrams |
| `src/music_stack/musicxml.py` | sheet-music export |
| `src/music_stack/report.py` | the Studio: payload, page chrome, reference renderers |
| `src/music_stack/assets/` | report-lib.js + score-panel.js, inlined into the page |
| `src/music_stack/http.py` | the credential boundary |
| `docs/architecture.md` | why zero-dependency, how the boundary works |
| `docs/workflow.md` | the songwriting pipeline end to end |
| `docs/troubleshooting.md` | failures and fixes |
| `docs/services-and-costs.md` | what is gated and what is not |

## Adding a stage

1. External tool → register in `local_tools.TOOLS` with an install hint.
2. Build argv in a separate `*_command()` function so `--dry-run` can show it.
3. Wire into `brief.analyze()` guarded by `.which()` so absence skips, not fails.
4. Test the argv — that is the contract with the tool, and a flag change should
   fail a diff rather than a 1am run.

## Adding a report view

Charts render client-side: `<score-panel>` in `assets/score-panel.js` owns
the views. A fifth view is (1) a renderer in `assets/report-lib.js`, ported
from a tested Python reference implementation you add to `report.py` first
— behaviour changes start in Python, in a test, and are mirrored into the
asset; (2) a branch in `score-panel.js`'s `_render` that builds the HTML
and sets `this._seq = {times, xs, mids}` for sequence-spaced charts (that
one field buys the playhead, click-to-seek, ⌥ audition, loop shading, and
lyric alignment); (3) a pill in `report.py`'s control row — the app script
drives every panel from the pills via attributes. `_seq_x` (Python) /
`seqPos` (JS) are the single time→x mappers — never a second copy. All
component theming flows through the `--sp-*` custom properties set on the
page root.
