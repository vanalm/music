# Services, accounts, and costs

Pricing and limits change; treat every number here as "check the dashboard".
What does not change is the *shape* of each relationship, which is what this
page is really about.

## Moises — the door that is actually open

Moises and Music.AI are one company (Moises Systems) running one engine.
Moises is the consumer/self-serve side; Music.AI is the enterprise platform.

**For an individual, Moises is the only reachable door.** Music.AI's login page
offers no self-serve signup — the sole call to action is "Get Enterprise
access", and their Contact Sales page explicitly redirects musicians and
producers to moises.ai. Third-party articles still describe a Music.AI free
tier; that is stale.

- **What it gives you**: the same stem separation, chord/key/tempo detection,
  and lyric transcription that powers the Moises app.
- **Cost**: Pro is around $9.99/month and is the tier that includes API access.
- **Getting the key**: developer account → **create an Application** → the key
  is on the Application. It is not in ordinary account settings.
- **Protocol**: **GraphQL**, one endpoint — `https://api.moises.ai/graphql`.
  Not REST.
- **Auth**: the key goes in the `Authorization` header. Published sources do
  not agree on whether it is bare or `Bearer`-prefixed, so run
  `music-stack moises auth` — it tries both and tells you which the server
  accepts.

Because the schema sits behind a login, this repo ships **no guessed queries**.
Run:

```bash
music-stack moises introspect
```

GraphQL servers describe themselves, so this returns the real operations,
arguments, and return types straight from Moises. Write queries from that
output — never from a blog post or an unofficial wrapper.

## Music.AI — enterprise only

Same engine, REST instead of GraphQL, at `api.music.ai`. The adapter is built
and tested and works unchanged **if** you are granted enterprise access. Auth
is `Authorization: <key>` with the raw key — no `Bearer`.

- **Workflows are account-specific.** No universal slug list. Always run
  `music-stack music-ai workflows` before writing a `--workflow` value.
- **Billing**: prepaid developer credits, quoted by sales.

Ignore this unless enterprise access comes through. A Moises subscription does
**not** grant Music.AI API credits — same company, separate ledgers.

## Kits AI (Arpeggi Labs)

- **What it gives you**: voice models, voice conversion, vocal separation,
  stem splitting, voice blending.
- **Auth**: `Authorization: Bearer <key>`.
- **Host**: the API is served from `arpeggi.io`, not `kits.ai` — Kits is an
  Arpeggi Labs product. This surprises people reading the marketing site.
- **Rate limit**: the alpha API is documented at roughly **one job-creating
  POST per account per minute**. The client spaces requests for you.
- **Result links expire quickly**, so outputs download as soon as a job
  resolves.
- **Two products, two tiers**: API access and the web app are billed
  separately. The Harmony Generator lives in the *app*, not the API, so if
  harmonies matter to you, check which app tier permits exports before paying
  for API access alone.

## Suno

- **What it gives you**: a REST API for songs, covers, and mashups, per its
  platform page.
- **Status here**: deliberately disabled. The endpoint and auth detail sit
  behind an authenticated account, and this repository does not guess.
- **To enable**: sign in at suno.com/platform, read the API reference, and set
  `SUNO_API_KEY` and `SUNO_API_BASE`. Then implement the documented endpoints
  in `adapters/suno.py`.
- **What not to do**: unofficial wrappers, browser cookie extraction, captcha
  workarounds, or invented endpoints. All are ToS violations and ban risks.
  See [security.md](security.md).

Do this one last. It is the only integration whose contract you cannot read
without an account, so it is the one most likely to waste money if rushed.

## ffmpeg

Free, local, no account. Installed by the bootstrap script. Everything under
`music-stack audio` runs entirely on your machine and costs nothing.

## Suggested order

1. **ffmpeg** — free; get the local pipeline working end to end first.
2. **Music.AI** — minimum credits, one short demo, confirm a workflow runs.
3. **Kits** — API access plus whichever app tier allows harmony export.
4. **Suno** — only once you can read its authenticated schema.

Each step is independently useful. If you stop after step 2 you still have a
working analysis pipeline.

## Keeping spend down

- Read-only commands cost nothing: `doctor`, `project`, `audio`,
  `music-ai workflows`, `music-ai job`, `kits models`. Use them freely.
- Test any new workflow on a 30-second excerpt. A first attempt at an
  unfamiliar workflow is the run most likely to be wrong, and a snippet costs
  the same to be wrong with as a full arrangement.
- `music-ai process --delete-remote` removes the vendor-side job and its
  stored outputs after download.
- `project.json` records every job you have run, so you can audit spend per
  song rather than reconstructing it from a bill.
