"""
Central configuration. Edit this file to tune behavior.

NOTE ON MODEL STRINGS: model names change over time. These were current as of
mid-2026. If a call fails with a model-not-found error, check the current model
list at https://docs.claude.com/en/api/overview and update here.
"""

from pathlib import Path

# ---- Claude models ----
MODEL_FILTER = "claude-haiku-4-5"     # cheap model for the batched relevance pass
MODEL_DRAFT = "claude-sonnet-4-6"     # stronger model for summarizing + drafting

# ---- Run behavior ----
LOOKBACK_DAYS = 14     # how far back the DEFAULT run looks. 14 / 21 / 28 = ~2-4 weeks.
# The V2 run uses a wider window: regulatory CHANGES (rules, proposed rules,
# guidances, CLIA/coverage actions) publish less often than device clearances, so
# a wider net catches them with margin over a weekly cadence. Kept separate so the
# default run above stays exactly as it was. run_v2 applies this at runtime.
LOOKBACK_DAYS_V2 = 45
MAX_DRAFTS = 8         # max posts drafted per run (after relevance ranking)
REQUEST_TIMEOUT = 30   # seconds, for source HTTP calls

# ---- Keyword pre-filter ----
# Substantive IVD terms only. Generic FDA-process words (510(k), premarket, pma)
# were removed because they match every FDA item and don't discriminate.
# NOTE: openFDA items are pre-qualified by device panel in sources.py and bypass
# this keyword pass (see filtering.py), so this list only screens text sources
# (Federal Register, GenomeWeb, RSS).
KEYWORDS = [
    "in vitro diagnostic", "ivd", "clia", "companion diagnostic",
    "point of care", "point-of-care", "ldt", "laboratory developed test",
    "assay", "immunoassay", "diagnostic test", "molecular diagnostic",
    "biomarker", "serology", "antigen test", "antibody test", "pcr",
    "sequencing", "ngs", "liquid biopsy", "lateral flow", "sars-cov-2",
    "infectious disease", "screening test", "blood test",
]

# ---- Sources ----
SOURCES = {
    # Federal Register API. Confirmed working.
    "federal_register": {
        "enabled": True,
        "base_url": "https://www.federalregister.gov/api/v1/documents.json",
        "agencies": ["food-and-drug-administration", "centers-for-medicare-medicaid-services"],
        "per_page": 40,
    },
    # openFDA 510(k). Confirmed working: ISO dates (with dashes), space in the range.
    # limit is high because IVD clearances are a small fraction of all device
    # clearances; we fetch a wide window and keep only IVD device panels.
    "openfda_510k": {
        "enabled": True,
        "base_url": "https://api.fda.gov/device/510k.json",
        "limit": 200,
    },
    "openfda_enforcement": {
        "enabled": False,  # device recalls; turn on if you want them
        "base_url": "https://api.fda.gov/device/enforcement.json",
        "limit": 25,
    },
    # GenomeWeb point-of-care category page (HTML, headlines only).
    # READ THE CAVEAT in the README before relying on this. GenomeWeb is a
    # subscription publication; confirm their ToS / robots.txt allow automated
    # access. This pulls only public headlines + links and never article bodies.
    "genomeweb": {
        "enabled": True,
        "url": "https://www.genomeweb.com/point-care-testing",
        "max_items": 25,
    },
    # 360Dx: GenomeWeb's sister IVD/diagnostics publication (separate site).
    # Same CAVEAT as GenomeWeb: subscription publication with no public RSS feed
    # (checked -- /rss endpoints 404), so this scrapes only public headlines +
    # links from the category page, never article bodies. Confirm ToS / robots.txt
    # allow automated access before relying on it.
    "360dx": {
        "enabled": True,
        "url": "https://www.360dx.com/point-care-testing",
        "max_items": 25,
    },
    # Optional extra RSS feeds. Add verified feed URLs here.
    "rss": {
        "enabled": False,
        "feeds": [],
    },
    # ---- V2 sources (used only on the `--v2` run; the default run ignores these) ----
    # Targeted Federal Register queries by precise IVD/CLIA phrases. The default
    # agency feed above is capped at the 40 NEWEST FDA+CMS docs with no topic
    # filter, so substantive IVD regulatory CHANGES (rules, proposed rules,
    # guidances, CLIA and Medicare coverage/payment actions) that are older than
    # the newest 40 are invisible to it. Verified: phrase queries surface items the
    # capped feed misses (a CLIA proposed rule, an IVD device reclassification rule,
    # the Medicare physician fee schedule). Items carry real abstracts, so the
    # practitioner read has substantive text to ground in (not thin). Only clean,
    # high-signal phrases are used; broad free-terms returned off-topic noise. These
    # are NOT prequalified, so the keyword filter still screens them.
    "federal_register_ivd": {
        "enabled": True,
        "base_url": "https://www.federalregister.gov/api/v1/documents.json",
        "terms": [
            "in vitro diagnostic",
            "companion diagnostic",
            "Clinical Laboratory Improvement Amendments",
            "laboratory developed test",
        ],
        "per_page": 50,
        "region": "US",
    },
    # CAP (College of American Pathologists) public newsroom. HONEST LIMITATION:
    # verified fetchable (HTTP 200) but the page is a JS-rendered Sitecore site;
    # the static HTML gives section/announcement links, NOT dated checklist detail.
    # So this captures the ANNOUNCEMENT that something changed (a checklist edition,
    # an accreditation-program update), never the checklist content itself. Every
    # CAP item is force-flagged thin_source. Membership-gated checklist content is
    # never fetched. Confirm ToS / robots.txt before relying on it.
    # DISABLED by default: recon confirmed the public page returns only left-nav /
    # section links (JS-rendered site), not dated announcements, so it cannot be
    # usefully automated. Left here as a MANUAL-WATCH note + a working adapter in
    # case a genuinely itemized public CAP page is pointed at it later. If enabled,
    # every item is force-thin (announcement-level at best).
    "cap": {
        "enabled": False,
        "url": "https://www.cap.org/about-the-cap/newsroom",
        "domain": "cap.org",
        "max_items": 15,
        "region": "US",
    },
    # EU IVDR guidance: the Medical Device Coordination Group (MDCG) endorsed-
    # documents page on the European Commission health site. VERIFIED fetchable
    # (HTTP 200, static HTML) with extractable MDCG document links (e.g. "MDCG
    # 2024-13"). This is the practical, public EU IVDR signal. It is the best
    # available public access path: EUR-Lex blocks automated access (HTTP 202
    # anti-bot wall) and EMA retired its public RSS (news list is JS-rendered),
    # so full legal text and EMA news are NOT automated (manual-watch notes).
    "eu_mdcg": {
        "enabled": True,
        "url": "https://health.ec.europa.eu/medical-devices-sector/new-regulations/guidance-mdcg-endorsed-documents-and-other-guidance_en",
        "domain": "health.ec.europa.eu",
        "max_items": 25,
        "region": "EU",
    },
    # EU policy news: European Commission press-corner RSS, keyword-filtered.
    # VERIFIED fetchable (valid dated RSS). Coarse (mostly "Daily News" digests),
    # so it is OFF by default; enable if you want a wide EU policy net. region EU.
    "eu_presscorner": {
        "enabled": False,
        "url": "https://ec.europa.eu/commission/presscorner/api/rss?language=en",
        "max_items": 25,
        "region": "EU",
    },
}

# ---- V2 topic lenses (tags applied over the reused feed; NOT new endpoints) ----
# CMS coverage/reimbursement: most CMS rulemaking already arrives via the Federal
# Register feed (the CMS agency is already queried above). This is a keyword lens
# that TAGS those items "CMS", it is not a separate fetch. data.cms.gov exposes a
# JSON catalog but only statistical datasets (fee schedules, enrollment), not
# timely coverage actions, and the Medicare Coverage Database (NCD/LCD) is not a
# clean public feed, so the Federal Register is the verified path for CMS actions.
CMS_LENS = [
    "medicare", "medicaid", "cms", "coverage", "reimbursement", "ncd",
    "national coverage", "local coverage", "lcd", "clinical laboratory fee",
    "clfs", "physician fee schedule", "coverage determination", "payment",
]
# CLIA: a federal program (42 CFR 493) administered by CMS. Implemented as a
# TOPIC/keyword lens over the Federal Register + CMS items, tagged CLIA. It is
# NOT a standalone source/API.
CLIA_LENS = [
    "clia", "clinical laboratory improvement", "42 cfr 493", "part 493",
    "laboratory certification", "proficiency testing", "clinical laboratory",
    "waived test", "certificate of waiver", "laboratory-developed test", "ldt",
]

# ---- Roles (V2 practitioner read) ----
# CONFIGURED roles, picked by id. The model may only choose from these ids; any id
# it invents is dropped in code. "lab tech" maps to the Lab role. See CRA_CONSTRAINT.
ROLES = {
    "CDM": {
        "label": "Clinical Data Management",
        "scope": "CRFs/eCRFs, EDC builds and edit checks, data management plans, "
                 "data validation specs, coding/mapping, database locks.",
    },
    "ClinOps": {
        "label": "Clinical Operations",
        "scope": "study start-up, site management, monitoring oversight, protocol "
                 "logistics, vendor/EDC coordination, TMF.",
    },
    "RA": {
        "label": "Regulatory Affairs",
        "scope": "submissions and submission datasets, regulatory strategy, agency "
                 "correspondence, labeling, registrations, change filings.",
    },
    "QA": {
        "label": "Quality Assurance",
        "scope": "SOPs, quality system procedures, audits, CAPA, validation "
                 "documentation, compliance records.",
    },
    "Lab": {
        "label": "Laboratory (incl. lab techs)",
        "scope": "assay SOPs, instrument/method validation and verification, "
                 "QC procedures, specimen handling, accreditation/CLIA records.",
    },
    "Biostat": {
        "label": "Biostatistics",
        "scope": "statistical analysis plans, analysis datasets and derivations, "
                 "endpoint definitions, coding of demographic/covariate variables.",
    },
}

# LOCKED. Content for the CRA/monitor audience must be framed as "what this means
# for the monitor" and must NEVER imply the author has held the CRA role. CRA is
# intentionally NOT a pickable role; this constraint is a hard rule in the prompt.
CRA_CONSTRAINT = (
    "CRA/monitor framing is LOCKED: if anything is relevant to a CRA/monitor, frame "
    "it strictly as 'what this likely means for the monitor'. Never write in the "
    "first person as a CRA and never imply the author has held the CRA role. CRA is "
    "not one of the selectable roles."
)

# Lifecycle phases a practitioner action can land in.
LIFECYCLE_PHASES = ("planning", "execution", "submission")

# Always-appended applicability caveat (code-injected, never model-emitted) so it
# is present on every practitioner read regardless of what the model returns.
APPLICABILITY_CAVEAT = "Check applicability to your own studies before acting."

# ---- Output paths ----
ROOT = Path(__file__).resolve().parent
DOCS_DIR = ROOT / "docs"
DRAFTS_JSON = DOCS_DIR / "drafts.json"
ARCHIVE_DIR = ROOT / "drafts"
CACHE_FILE = ROOT / "seen.json"

# ---- V2 output paths (kept fully separate; the default run never touches these) ----
DRAFTS_JSON_V2 = DOCS_DIR / "drafts_v2.json"
ARCHIVE_DIR_V2 = ROOT / "drafts" / "v2"
CACHE_FILE_V2 = ROOT / "seen_v2.json"
