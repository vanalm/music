# The songwriting workflow

The pipeline assumes one input — a rough demo, phone voice memo, or scratch
take — and walks it to the point where you have clean stems, harmony guides,
and a chord/lyric map to write against.

## 1. Start a project

```bash
music-stack project new "Working Title"
cp ~/Desktop/demo.m4a projects/working-title/input/
```

`input/` is write-once. Nothing in this tool ever modifies it again, so the
original take is always recoverable no matter what goes wrong downstream.

## 2. Normalize before anything else

```bash
music-stack audio normalize \
  projects/working-title/input/demo.m4a \
  projects/working-title/normalized/demo-48k-24bit.wav
```

This is a *format* conversion, not loudness normalisation — no gain is applied.
It produces lossless 48 kHz / 24-bit WAV, strips metadata and cover art.

Do it even when a service would accept the original. Every later stage then
sees identical sample rate and bit depth, which means a stem from Music.AI and
a stem from Kits line up sample-for-sample instead of drifting. Re-encoding a
lossy file repeatedly through different services compounds artefacts; going to
lossless once does not.

Check what you got:

```bash
music-stack audio inspect projects/working-title/normalized/demo-48k-24bit.wav
```

## 3. Understand the song — Music.AI

Workflow slugs are specific to your account, so list yours before spending
anything:

```bash
music-stack music-ai workflows                  # everything
music-stack music-ai workflows --contains chord
music-stack music-ai workflows --contains lyric
music-stack music-ai workflows --contains stem
```

Then run the one you want:

```bash
music-stack music-ai process \
  --workflow 'the-slug-you-just-saw' \
  --input  projects/working-title/normalized/demo-48k-24bit.wav \
  --output projects/working-title/analysis/music-ai/first-pass
```

Analysis workflows return inline JSON rather than audio links; those land as
`.json` files in the output directory. Stem workflows return signed URLs and
land as audio. Both are recorded in `project.json` with the job id.

**Start with a 30-second excerpt.** A full arrangement costs the same per
attempt as a snippet, and the first run of any new workflow is the one most
likely to be wrong.

## 4. Isolate and split — Kits

```bash
music-stack kits models
music-stack kits vocals \
  --input  projects/working-title/normalized/demo-48k-24bit.wav \
  --output projects/working-title/stems/kits/vocals
```

Kits' alpha API allows roughly one job-creating POST per account per minute.
The client spaces requests automatically rather than letting you trip a 429 —
so a batch will *look* slow and that is correct behaviour. Set
`KITS_MIN_POST_INTERVAL=0` if your plan lifts the limit.

Result links from Kits expire quickly, which is why outputs download the
instant a job resolves instead of waiting for a separate command.

## 5. Harmonies — manual, on purpose

Kits' published API index covers voice conversion, voice models, vocal
separation, stem splitting, and voice blending. It does **not** cover the
interactive Harmony Generator.

So this stage is deliberately manual:

1. Take the isolated lead vocal from step 4.
2. Upload it to the Harmony Generator in the Kits web app.
3. Audition intervals there.
4. Export the takes you want into
   `projects/working-title/harmonies/manual-kits/`.

Voice conversion is *not* the same feature. Automating the harmony stage by
substituting voice conversion would produce something that runs and sounds
wrong — the worst kind of failure. When Kits publishes a harmony endpoint, it
becomes a `kits harmonies` command; until then the folder is the interface.

## 6. Write

At this point the project holds the original, a lossless working copy, chords
and lyrics as data, separated stems from two engines, and harmony guides.
`notes/` is for lyric drafts and arrangement scratch; `renders/` for bounces.

## Cost discipline

- Read-only commands (`workflows`, `models`, `doctor`, `project`, `audio`) never
  spend anything. Use them freely.
- Only `music-ai process` and the `kits` job commands cost credits.
- Test new workflows on short excerpts.
- `--delete-remote` cleans up the vendor-side job after download.

## Reproducing a past run

`project.json` records every job: service, workflow, job id, output path, and
timestamp. To see what a previous run actually did:

```bash
cat projects/working-title/project.json
music-stack music-ai job <job-id>
```

## Working out a lick

Structure and stems say how the song is arranged. Neither tells you *what you
played*. That needs pitch transcription — `basic-pitch`, which is polyphonic
and instrument-agnostic.

```bash
pip install -U basic-pitch

music-stack lick \
  --input projects/working-title/input/demo.m4a \
  --start 1:23 --end 1:31
```

Times take `83`, `1:23`, or `1:23.5`.

**Trim tightly.** It is the single biggest accuracy lever. Transcribing four
seconds beats transcribing four minutes: fewer overlapping notes to confuse the
model, and no unrelated material to pollute the scale hypothesis. Two seconds
of run-in is plenty.

If the lick sits under vocals or a full band, isolate it first:

```bash
music-stack lick --input demo.m4a --start 1:23 --end 1:31 --isolate other
```

Demucs' `other` stem is where guitar lands (`vocals`, `drums`, and `bass` being
the named three). This needs demucs installed; without it the command says so
and continues on the full mix.

You get the notes in order, ASCII tab on the top three strings, a ranked scale
hypothesis, and a per-note table with fret positions. `--all-strings` widens
the fingering search; `--sharps` names notes with sharps instead of flats.

### On the scale ranking

It is a ranked list, not a verdict, because the ambiguity is often real. A
minor pentatonic and its relative major contain *identical* notes — A C D E G
is both A minor pentatonic and C major pentatonic. Nothing in the note set can
separate them; only where the phrase resolves can, so the ranking weighs the
last note heaviest, then the first, then how often the candidate root is
played. When the second entry is the relative major of the first, that is the
tool telling you the truth rather than guessing.

Scales are also scored on *fit*, not just coverage. A seven-note scale contains
a five-note one, so coverage alone would always favour the bigger scale;
penalising unplayed scale degrees is what lets a pentatonic win.

### Chords, and sheet music

`basic-pitch` is polyphonic — it reports overlapping notes already. `lick`
groups those into chords, names them, and fingers them across all six strings:

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

Chord boxes for each distinct shape follow, unless you pass `--no-diagrams`.

The voicing shown is **descriptive, not prescriptive**: it fingers the notes
actually detected rather than substituting a textbook shape, because the
question is "what did I play", not "how is this chord usually voiced". When
the detected notes cannot be one hand position — seven pitches, or a spread of
three octaves — it says so instead of inventing a grip.

Naming leans on the bass. `A C E G` is *exactly* Am7 and *exactly* C6; the note
set cannot separate them and only what is underneath can, so the lowest note
decides. A note that fits no chord tone is reported as `extra` rather than
quietly pushing the name to something exotic — usually it is a transcription
artefact, not a real extension.

**Tuning for the material:** `--chord-window` sets how close onsets must be to
count as one strum (default 0.08s). Raise it for slow, spread strums; lower it
if fast passages are being glued together. `--melody-only` forces the
single-line reading; `--also-melody` shows both.

For notation:

```bash
music-stack lick --input demo.m4a --start 1:23 --end 1:31 --musicxml --bpm 92
```

That writes a `.musicxml` which MuseScore (free), Guitar Pro, Dorico, and
Sibelius all open — engraved notation, with chord symbols above the staff, and
guitar tab if you add a tab staff in the editor.

The MIDI that basic-pitch writes also opens directly in MuseScore and needs no
extra step. Prefer it when rhythm matters: **MusicXML export quantises to a
sixteenth-note grid against a fixed tempo**, so anything rubato, swung, or in
triplets will notate squarer than you played it. Pass the real `--bpm` (from
`local structure`) to keep the barlines honest.
