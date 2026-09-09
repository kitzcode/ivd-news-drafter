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

## RegWatch V2 (opt-in: `python main.py --v2`)

V2 reuses the same pipeline (fetch, keyword prefilter, seen-cache dedupe, Haiku
relevance pass, code-injected citations) and adds layers on top. It writes to a
SEPARATE output, `docs/drafts_v2.json` + `drafts/v2/<date>.md` + its own
`seen_v2.json`, so the default run and its `docs/drafts.json` are never touched.
Review page: `docs/index_v2.html`.

```
python main.py --v2 --dry-run    # V2 fetch + tag + filter only, no Claude, no writes
python main.py --v2              # full V2 run (uses Claude, writes drafts_v2.json)
```

New sources (adapters behind the same interface, verified in recon):

- **Targeted Federal Register (IVD/CLIA)**: the default agency feed is capped at
  the 40 newest FDA+CMS docs with no topic filter, so substantive IVD regulatory
  CHANGES (device reclassification rules, the CLIA RFI, the Medicare physician fee
  schedule, IVD EUAs and revocations) older than the newest 40 are invisible to it.
  `fetch_federal_register_ivd` queries the same API by precise IVD/CLIA phrases so
  those are caught with their real abstracts (which lets the practitioner read be
  concrete instead of thin). The V2 relevance pass also prefers regulatory changes
  over routine 510(k) clearances (`score_and_select(prefer_regulatory_changes=True)`).
- **CMS** coverage/reimbursement: NOT a new endpoint. Most CMS rulemaking already
  arrives through the Federal Register feed (the CMS agency is already queried), so
  CMS is a keyword LENS (`config.CMS_LENS`) that tags those items. `data.cms.gov`
  exposes only statistical datasets, and the Medicare Coverage Database (NCD/LCD)
  is not a clean public feed, so the Federal Register is the verified path.
- **CLIA** (42 CFR 493, administered by CMS): a keyword LENS (`config.CLIA_LENS`)
  over the Federal Register + CMS items, tagged CLIA. Not a standalone source.
- **CAP**: honest limitation. The public newsroom is fetchable but JS-rendered, so
  the static HTML yields only section/nav links, not dated announcements. It cannot
  be usefully automated, so it is DISABLED by default and left as a manual-watch
  note; the adapter stays in place (force-thin) if a genuinely itemized public page
  is pointed at it. Membership-gated checklist content is never fetched.
- **EU IVDR (MDCG)**: the Medical Device Coordination Group endorsed-documents page
  on `health.ec.europa.eu`, verified fetchable with extractable document links. This
  is the best available public EU IVDR signal. EUR-Lex blocks automated access (HTTP
  202 anti-bot wall) and EMA retired its public RSS with a JS-rendered news list, so
  full EU legal text and EMA news are NOT automated (manual watch). EU items are
  tagged region EU. An optional EC press-corner RSS lens (`eu_presscorner`, off by
  default) is available for a wider EU policy net.

The practitioner read (PART 2): for each change, per CONFIGURED role (CDM, ClinOps,
RA, QA, Lab, Biostat; picked by id, invented ids dropped), the model names the
specific artifact, the specific suggested action, and the lifecycle phase(s) it
lands in (planning / execution / submission). It PROPOSES; you adjudicate.

Anti-hallucination is tightened for V2 (`sanitize.py`): the model phrases
implications only. Any URL, date, document id, or CFR clause it emits is stripped
and flagged (`sanitize_flags`), because every citation is code-injected from the
source record. If a source is too thin to name what concretely changes, the read is
collapsed to a "watch, do not act yet" note (`thin_source`). Applicability to your
own studies is always your call and is appended in code to every action. CRA/monitor
framing is locked (`config.CRA_CONSTRAINT`): CRA is not a selectable role, and any
monitor-relevant note is framed as "what this means for the monitor", never in the
first person. No em dashes anywhere.

Tests (no API key needed): `python tests/test_v2.py`.

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
