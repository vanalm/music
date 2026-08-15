# music-stack

A programmable songwriting pipeline: take a rough demo, get it to a clean
lossless working copy, then run it through **Music.AI** (analysis, stems) and
**Kits AI** (vocal separation, stem splitting, voice conversion) from one
command line, with every output filed into a per-song project folder.

```
demo.m4a ──► normalize ──► 48kHz/24-bit WAV ──┬──► Music.AI  ──► chords / key / stems
                                              ├──► Kits AI   ──► isolated vocal / stems
                                              └──► harmonies ──► (manual Kits export)
```

## Install

Requires **Python 3.9+** and **ffmpeg**. On a Mac with Homebrew already
installed, one command does everything:

```bash
./scripts/bootstrap-macos.sh
```

It installs ffmpeg, creates `.venv`, installs this package, writes a private
`.env` from the template, and runs the test suite. It will **not** silently run
Homebrew's remote installer — if Homebrew is missing it stops and says so.

Doing it by hand is three lines:

```bash
brew install ffmpeg python@3.13
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

### No dependencies, deliberately

`pip install -e .` pulls **nothing** from PyPI. Every HTTP call, multipart
body, and poll loop in this package is Python standard library. That is a
design decision, not an omission — see [docs/architecture.md](docs/architecture.md).
It means the install cannot break because an upstream release was yanked,
renamed, or pinned to an alpha that vanished.

The official vendor SDKs remain available as an *optional* extra
(`pip install -e '.[vendor]'`) if you want to script against their own
abstractions. Nothing in this CLI imports them.

## Configure

```bash
cp .env.example .env      # bootstrap does this for you
$EDITOR .env              # paste your keys
source .venv/bin/activate
music-stack doctor
```

`doctor` reports which credentials are **present** and a short non-reversible
fingerprint of each. It never prints a key, and neither does any other command.

```
Credentials (presence only; values are never displayed)
  music-ai  MUSIC_AI_API_KEY   configured   305fd8a4
  kits      KITS_API_KEY       missing      —
```

Suggested order for opening accounts — cheapest mistake first:

1. **Music.AI** — buy the minimum credits and process one short demo.
2. **Kits** — API access, plus whichever app tier allows harmony exports.
3. **Suno** — last, and only once you can read its authenticated API schema.

`./scripts/open-account-pages-macos.sh` opens all of the signup pages.

> Music.AI *developer* billing and a consumer Moises subscription are separate
> products. Assume they do not share credits unless your own dashboard says so.

## First song

```bash
music-stack project new "Working Title"
cp ~/Desktop/demo.m4a projects/working-title/input/

music-stack audio normalize \
  projects/working-title/input/demo.m4a \
  projects/working-title/normalized/demo-48k-24bit.wav
```

Look before you spend. Workflow slugs are **account-specific**, so list yours
first — this call costs nothing:

```bash
music-stack music-ai workflows --contains stem
music-stack music-ai workflows --contains chord
```

Then run one:

```bash
music-stack music-ai process \
  --workflow 'the-slug-you-just-saw' \
  --input  projects/working-title/normalized/demo-48k-24bit.wav \
  --output projects/working-title/analysis/music-ai/first-pass
```

Kits:

```bash
music-stack kits models
music-stack kits vocals \
  --input  projects/working-title/normalized/demo-48k-24bit.wav \
  --output projects/working-title/stems/kits/vocals
```

Harmony auditioning stays manual on purpose: Kits' published API index covers
voice conversion, voice models, separation and splitting — but **not** the
interactive Harmony Generator. Upload the isolated lead vocal in the Kits web
app and export takes into `projects/<slug>/harmonies/manual-kits/`. Pretending
voice conversion is the same feature would produce quietly wrong results.

## Commands

| Command | What it does | Costs credits |
|---|---|---|
| `doctor` | local tools + credential presence | no |
| `project new/list` | song folder scaffolding | no |
| `audio normalize/inspect` | local ffmpeg conversion + ffprobe | no |
| `music-ai workflows` | list your account's workflows | no |
| `music-ai process` | upload → run → download | **yes** |
| `music-ai job <id>` | fetch one job's status | no |
| `kits models` | list voice models | no |
| `kits vocals / stems / convert` | Kits jobs | **yes** |
| `suno status` | report why Suno is disabled | no |

Read-only commands are kept separate from spending ones so you can always look
before you pay.

## Project layout

Every song gets the same tree, so a file's provenance is obvious from its path:

```
projects/<slug>/
├── input/                 originals, never written to again
├── normalized/            lossless 48k/24-bit working copies
├── analysis/music-ai/     chords, key, tempo, lyrics
├── stems/music-ai/
├── stems/kits/
├── harmonies/manual-kits/ hand-exported from the Kits web app
├── renders/               bounces and mixes
├── notes/
└── project.json           job audit trail: service, workflow, job id, time
```

## Tests

```bash
PYTHONPATH=src:tests python3 -m unittest discover -s tests
```

71 tests, no network, no credentials required. The ffmpeg round-trip tests skip
themselves when ffmpeg is absent, so the suite is green on a fresh checkout and
gains 5 more tests once you have bootstrapped.

## Status of each integration

Honesty about what has been *exercised* versus what is *written to spec*:

| Integration | State |
|---|---|
| ffmpeg normalize / inspect | written to spec; round-trip tests run wherever ffmpeg exists |
| Music.AI | endpoints, auth scheme and job lifecycle match the published REST reference; exercised end-to-end against a mock, **not** against the live API |
| Kits — voice models, voice conversion | paths confirmed against Kits' published reference; mock-tested |
| Kits — vocal separation, stem splitting | paths follow the documented naming pattern but were **not** readable at build time; flagged `verified=False` in `ENDPOINTS` and reported by `doctor` |
| Suno | intentionally inert — no endpoint is guessed |

No live API call has been made from this repository. The first real request
will be yours, and `music-ai workflows` is the cheapest place to make it.

## Documentation

- [architecture.md](docs/architecture.md) — how it fits together and why zero-dependency
- [workflow.md](docs/workflow.md) — the songwriting pipeline end to end
- [security.md](docs/security.md) — credential handling and the storage boundary
- [services-and-costs.md](docs/services-and-costs.md) — accounts, billing, limits
- [troubleshooting.md](docs/troubleshooting.md) — failures and their fixes
- [roadmap.md](docs/roadmap.md) — what is deliberately not built yet
