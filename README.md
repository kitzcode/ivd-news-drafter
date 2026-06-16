# IVD / Diagnostics News Drafter

Scans IVD / diagnostics / regulatory news weekly and writes LinkedIn post drafts
in your voice. You review and post manually. The tool never posts anything.

It removes the part that stops you posting: parsing the news and writing a first
draft. You get a short list of finished drafts, pick one, and post it yourself.

## How it works

```
sources  ->  keyword filter  ->  dedupe (seen.json)  ->  Claude ranks top 4
         ->  Claude summarizes + drafts each  ->  writes drafts.json + archive
```

Two ways to use it:

- **Engine (works on its own):** run `python main.py` locally whenever you want.
  Drafts land in `docs/drafts.json` and a dated file in `drafts/`.
- **Phase 2 (automation + review site):** a GitHub Action runs it weekly and
  commits the refreshed `drafts.json`; GitHub Pages serves `docs/index.html` as
  a review page with copy buttons. Optional, but it gives you a live URL and
  demonstrates scheduled CI/CD + a deployed front end.

## Setup

```bash
git clone <your-repo> && cd ivd-news-drafter
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then paste your Anthropic API key into .env
```

## First run: verify the sources BEFORE spending tokens

The source endpoints in `config.py` are starting points, **not** verified-correct.
Confirm them, cheaply, with dry-run mode (no Claude calls, nothing written):

```bash
python main.py --dry-run
```

This prints what each source returned. If a source returns 0 or errors:

1. Open the provider docs linked in `config.py` / `sources.py`
   (Federal Register API; openFDA device APIs).
2. Fix the endpoint URL, the query params, and the response keys in `sources.py`
   (every spot that needs checking is marked `VERIFY`).
3. Re-run `--dry-run` until the items look right.

Then run for real:

```bash
python main.py
```

## Make the drafts sound like you

Open `voice.py` and paste 1-2 of your actual past LinkedIn posts into `EXAMPLES`.
Rules describe your voice; a real example or two gets it much closer.

## Phase 2: weekly automation + review site

1. Push the repo to GitHub.
2. Repo **Settings -> Secrets and variables -> Actions** -> add `ANTHROPIC_API_KEY`.
3. Repo **Settings -> Pages** -> set source to the `main` branch, `/docs` folder.
4. The workflow (`.github/workflows/weekly.yml`) runs Mondays and commits the new
   `drafts.json`. Trigger it manually anytime from the **Actions** tab
   (workflow_dispatch). Your review page will be at the Pages URL GitHub gives you.

The API key only ever lives in Actions secrets and is used during the run. The
published site only contains finished drafts, never the key.

## Notes and caveats

- **Verify endpoints.** See above. The biggest risk is trusting an unconfirmed
  source URL or response shape.
- **Model strings drift.** `config.py` pins specific Claude models; if a call
  fails with model-not-found, update them from the current API docs.
- **No auto-posting, by design.** A human reviews everything that could go out
  under your name. Always open the source link and check facts before posting.
- **Actions cron is best-effort timing**, not to the minute.
- This is research / informational tooling, not legal or regulatory advice.
```
