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
