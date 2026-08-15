# Roadmap

What is deliberately absent, and what it would take to add it. Everything here
is unbuilt on purpose — this is a list of decisions, not a backlog of debt.

## Blocked on vendor documentation

**Suno.** The adapter is inert until the authenticated API reference is read.
Once `SUNO_API_BASE` is known, implementing songs/covers/mashups is
straightforward — the job/poll/download shape already exists twice in this
codebase. The blocker is documentation access, not effort.

**Kits vocal separation / stem splitting paths.** Two entries in `ENDPOINTS`
are flagged `verified=False`. Confirming them against the signed-in reference
is a one-line change each. `doctor` will stop warning once both flip.

**Kits harmony generation.** Not in Kits' published API index — it exists only
in the web app. The manual export step in
[workflow.md](workflow.md) is the honest interface until an endpoint appears.
Do not substitute voice conversion for it.

## Worth building once the pipeline is in daily use

**Batch processing.** Run one workflow across every project, or every take in
a project. Straightforward, but wait until you know which workflows you
actually re-run — building a batch runner for the wrong three commands is
wasted work.

**Resumable jobs.** Today a timeout means polling again by job id. Since
`project.json` already records job ids, a `music-stack resume` that re-attaches
to unfinished jobs and downloads their results is a small addition.

**Stem alignment verification.** Everything is normalized to 48 kHz/24-bit, so
stems from different services *should* line up sample-for-sample. An
ffprobe-based check that asserts equal duration and sample rate across a
project's stems would catch drift early.

**Local-only analysis.** Key and tempo detection can run offline with
`aubio` or `librosa`. That would mean a dependency, so it belongs behind an
optional extra — and only if you find yourself paying for analysis often
enough to care.

## Explicitly not doing

**A GUI.** The filesystem is the interface. Project folders are inspectable
in Finder and any DAW opens them directly.

**Storing audio anywhere but locally.** No sync, no cloud library. Vendors get
files transiently for job processing; `--delete-remote` cleans up after.

**Unofficial API access of any kind.** No scraping, no cookie extraction, no
guessed endpoints, for any vendor. See [security.md](security.md).

**Vendoring dependencies.** The zero-dependency stance is load-bearing (see
[architecture.md](architecture.md)). If something genuinely needs a library,
it goes behind an optional extra, and the core CLI keeps working without it.

## If a vendor breaks a contract

The verification flags and the mocked test suite are the recovery mechanism.
When a response shape changes:

1. Reproduce with the single-job command (`music-ai job <id>`).
2. Update the adapter *and* the corresponding fixture in `tests/` together.
3. If an endpoint moved, update `ENDPOINTS` and its flag.

The tests are mocks, so they will not catch a vendor change on their own —
they catch *regressions in this code* once you have encoded the new reality.
That is the honest limit of an offline suite, and the reason the README states
plainly which integrations have never made a live call.
