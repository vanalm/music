# music-stack

Drop in a rough demo — an iPhone voice memo, a phone video, a scratch take —
and get back what you need to finish the song: tempo, the arrangement you
actually played, separated stems, the lyric as sung, the notes in that lick,
chord shapes, and sheet music.

**Runs on your machine. Nothing is uploaded.**

```bash
music-stack analyze --input ~/Downloads/vm0043.m4a
```

That is the whole workflow. One command.

Or no command at all — start the drop folder once:

```bash
music-stack watch
```

then **drag voice memos into `dropbox/` from Finder** (or AirDrop straight
into it). Each file is analyzed into `projects/<slug>/` and the original is
filed under `dropbox/done/`. Files that fail move to `dropbox/failed/` with
the reason printed, and a file still copying in is left alone until its bytes
have finished arriving.

## What comes out

`projects/<slug>/brief.md`:

```markdown
# Kaimana Nights

**Source** · alac · 48000 Hz · 1 ch · 1:14

## Structure
- **Tempo** — 84 BPM
- **Arrangement** — intro → verse → chorus → verse

| Section | Start | Length |
|---|---|---|
| intro  | 0:00 | 6.5s  |
| verse  | 0:06 | 24.5s |
| chorus | 0:31 | 21.0s |

**Not present yet:** bridge, outro

## Lyrics as sung
*Transcribed from the isolated vocal stem.*
    walking down to the water line
    thinking how the summer went by

## To finish this
- No bridge. Where would the song benefit from leaving the loop — and what
  does it need to say there that the verses don't?
- It runs 74s. That's a sketch, not an arrangement — which section wants
  extending first?
```

Plus, on disk:

```
projects/kaimana-nights/
├── input/          your original, never modified
├── normalized/     lossless 48k/24-bit working copy
├── analysis/       tempo, beats, labelled sections (JSON)
├── stems/local/    vocals, drums, bass, other
├── notes/lyrics/   transcript as .txt/.json/.srt
├── brief.md        ← the thing to read
├── brief.json      the same, machine-readable
└── report.html     ← the thing to LOOK at — double-click it
```

`report.html` is **the Studio** — a two-pane practice room, not a printout.
The score fills the left side: one panel per section, and a single switcher
flips every panel between **piano roll** (every transcribed note, names
aligned beneath), **guitar tab** (with a position selector — the audio
cannot say which string was played, so pick the fingering that fits your
hand), **sheet music** (grand staff with time signature, bar lines, and
beamed rhythms read off allin1's beat grid), and the **chord chart** with
textbook grips. An **Instrument | Voice** toggle flips the same charts
between what was played and what was sung. The right side is a sticky
practice dock: the section timeline and transport, speed pills that slow
the song without changing pitch, the chord under your hand right now with
its grip and what's next, a lyric window that follows playback, and every
shape in the song. Lyrics ride each chart **word by word** at the moment
they're sung; a playhead runs through whichever view is up and flows
section to section.

Everything is playable by hand: space and arrow keys drive playback,
everything clickable seeks, a plain click moves the playhead without
starting playback, **dragging scrubs the recording** through the exact
spot under the pointer, ⌘-click two spots loops a passage (esc clears),
⌥-click a note (or a moment) to hear it, and each section's **▶ tones**
button plays its transcription back as synth at tempo. Light and dark
themes; your view, speed, theme, and position survive reopening. One
self-contained file — audio embedded — so you can mail it to a bandmate.
Regenerate any time with `music-stack report <slug>`.

It is deliberately **plain HTML + vanilla JS, not React** — the report is
an artifact, not an app. It must open from a double-click on `file://`, on
an aeroplane, on a bandmate's laptop with nothing installed, and still
work in ten years. A framework would mean a build step, a runtime
dependency, and a bundle to go stale — the exact failure modes this
project exists to avoid. Web components give it real componentization
anyway; the reasoning is spelled out in
[docs/architecture.md](docs/architecture.md).

Paste `brief.md` into a chat and you are working on the song, not the tooling.

## Install

Requires **Python 3.9+** and **ffmpeg**.

```bash
git clone <this repo> ~/code/music && cd ~/code/music
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
music-stack doctor
```

`pip install -e .` pulls **nothing** from PyPI — the package is standard
library only. That is deliberate: the install cannot break because an upstream
release was yanked or pinned to an alpha that vanished. See
[docs/architecture.md](docs/architecture.md).

On a Mac with Homebrew, `./scripts/bootstrap-macos.sh` does all of the above
plus ffmpeg.

## Optional tools — each adds a section to the brief

None required, and one script installs all of them with the right versions
(some need their own Python — it handles that):

```bash
./scripts/install-ml-tools.sh
```

`music-stack local doctor` shows what you have and how to get the rest by
hand:

| Install | Adds |
|---|---|
| `brew install ffmpeg` | conversion, trimming — **the only real requirement** |
| `pip install -U demucs` | stem separation |
| `pip install -U basic-pitch` | notes and chords — needs Python ≤ 3.11 |
| `pip install -U mlx-whisper` | lyric transcription (Apple Silicon) |
| allin1 (see `install-ml-tools.sh`) | tempo, beats, labelled sections |

Already have a Whisper? It finds `mlx_whisper`, `whisper-cli`, `whisper-cpp`,
or `whisper` and adapts — no need to install another.

If Demucs is present, lyrics are transcribed from the **isolated vocal stem**
rather than the full mix, which is markedly more accurate.

## Bring your own stems

Already separated the song with Moises, Suno, or anything else? Drop the
files into the project and re-run — they are used **instead of** running
demucs, and a cleaner separation improves everything downstream (lyrics,
the sung-melody views, chords):

```bash
mkdir -p projects/<slug>/stems/user
cp ~/Downloads/my-moises-export/*.wav projects/<slug>/stems/user/
music-stack analyze --input projects/<slug>/input/<original>
```

Common naming dialects are recognised automatically: vocals / vocal / vox
for the voice, other / instrumental / guitars / no_vocals for the
instruments.

## Working out a lick

```bash
music-stack lick --input demo.m4a --start 1:23 --end 1:31
```

```
Notes (7): G4 F4 E4 Eb4 D4 C4 A3
Shape: descending over 10 semitones

Tab (high three strings, standard tuning):
e|-3----1----0-----------------------|
B|----------------4----3----1--------|
G|-------------------------------2---|

Most likely scale:
  A   blues (minor)      explains 86% of the notes
  C   blues (major)      explains 86% of the notes
```

Chords work too — `basic-pitch` is polyphonic:

```
Progression: C Am F G

Tab:
e|-0------0------1------3-----|
B|-1------1------1------0-----|
G|-0------2------2------0-----|
D|-2------2------3------0-----|
A|-3------0-------------2-----|
E|----------------------3-----|

  0.00s  C    C3 E3 G3 C4 E4    x32010
  1.00s  Am   A2 E3 A3 C4 E4    x02210
```

With chord boxes for each shape. **Trim tightly** — four seconds transcribes
far better than four minutes. If the part is buried, `--isolate other` pulls
the guitar out first.

### Sheet music

```bash
music-stack lick --input demo.m4a --start 1:23 --end 1:31 --musicxml --bpm 92
```

Writes a `.musicxml` that **MuseScore** (free), Guitar Pro, Dorico, and
Sibelius all open — engraved notation with chord symbols. Add a tab staff in
the editor for notation and tab together.

The MIDI `basic-pitch` writes also opens in MuseScore with no extra flag, and
keeps raw timing. Prefer it when rhythm matters: MusicXML export quantises to a
sixteenth grid, so swing and rubato notate squarer than you played.

## Commands

| Command | Does | Costs |
|---|---|---|
| `analyze --input F` | **everything, one pass** | free |
| `watch` | drop folder — drag files in from Finder | free |
| `report <slug>` | regenerate a project's report.html | free |
| `lick --input F --start T --end T` | notes, chords, tab, scale, score | free |
| `doctor` / `local doctor` | what is installed and configured | free |
| `project new/list` | song folders | free |
| `audio normalize/inspect` | conversion, ffprobe summary | free |
| `local stems/structure/lyrics/notes` | run one stage on its own | free |
| `music-ai *` | Music.AI REST — **enterprise only** | credits |
| `kits *` | Kits AI — self-serve signup exists | credits |
| `moises auth/introspect/query` | Moises GraphQL (legacy) | plan |
| `suno status` | reports why Suno is off | free |

`--dry-run` on any local command prints the exact argv without running it.

## About the hosted services

Worth knowing before you go shopping — all verified by probing the live sites:

- **Music.AI has no self-serve signup.** Its login page offers only "Get
  Enterprise access"; Contact Sales redirects individuals to moises.ai.
  Articles describing a free tier are stale. The adapter is built and correct,
  just dormant.
- **No Moises consumer plan grants an API key** — not Free, Premium, or Pro.
  Don't buy Pro expecting one.
- **Kits AI** does have real self-serve signup, including a free tier.
- **Suno** ships inert by design — no guessed endpoints.

The local path is not a consolation prize. Demucs is the model family Moises'
own separation is built on, and you keep your unreleased demos on your own
disk.

## Tests

```bash
PYTHONPATH=src:tests python3 -m unittest discover -s tests
```

338 tests, no network, no credentials. The ffmpeg round-trips skip themselves
when ffmpeg is absent, so a fresh checkout is green either way.

The hosted-service tests are fully mocked — they verify this code's logic, not
vendor behaviour. **No live API call has ever been made from this repository.**

## Extending it

The seams are deliberate; each has a short recipe in
[CLAUDE.md](CLAUDE.md):

- **A new analysis stage** — register the external tool in
  `local_tools.TOOLS` with an install hint, build its argv in a
  `*_command()` function (so `--dry-run` can print it), wire it into
  `brief.analyze()` guarded by `.which()` so absence skips instead of
  failing, and test the argv — that's the contract with the tool.
- **A new report view** — charts render client-side in
  `src/music_stack/assets/`. Add the renderer to `report-lib.js` as a port
  of a tested Python reference implementation in `report.py` (behaviour
  changes start in Python, in a test), add a branch to `score-panel.js`,
  and a pill to the control row in `report.py`. Setting the panel's
  `_seq = {times, xs, mids}` buys the playhead, click-to-seek, ⌥ audition,
  looping, and lyric alignment for free.
- **A new hosted service** — new module in `adapters/` with its own
  `ALLOWED_HOSTS`, every request through `http.api_request` (never raw
  urllib), and a round-trip test proving the credential never reaches a
  storage host. Unconfirmed endpoint paths are declared
  `verified=False`.

House rules that keep it maintainable: **zero runtime dependencies in the
core** (optional extras only), **never widen a credential allow-list** to
fix an error, **secrets are never printed**, and `input/` is write-once.

## Documentation

- [CLAUDE.md](CLAUDE.md) — orientation for an agent with no context. Start here
  if you are one.
- [docs/workflow.md](docs/workflow.md) — the pipeline end to end
- [docs/architecture.md](docs/architecture.md) — why zero-dependency, and the
  credential boundary
- [docs/troubleshooting.md](docs/troubleshooting.md) — failures and fixes
- [docs/services-and-costs.md](docs/services-and-costs.md) — what is gated
- [docs/security.md](docs/security.md) — credentials and what leaves the machine
- [docs/roadmap.md](docs/roadmap.md) — what is deliberately not built
