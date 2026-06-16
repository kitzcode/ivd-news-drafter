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
LOOKBACK_DAYS = 14     # how far back each run looks. 14 / 21 / 28 = ~2-4 weeks.
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
    # Optional extra RSS feeds. Add verified feed URLs here.
    "rss": {
        "enabled": False,
        "feeds": [],
    },
}

# ---- Output paths ----
ROOT = Path(__file__).resolve().parent
DOCS_DIR = ROOT / "docs"
DRAFTS_JSON = DOCS_DIR / "drafts.json"
ARCHIVE_DIR = ROOT / "drafts"
CACHE_FILE = ROOT / "seen.json"
