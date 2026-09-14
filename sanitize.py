"""
Citation strip-and-flag: the anti-hallucination enforcement, tightened for V2.

The model PHRASES practice implications. It must never emit a citation, URL, date,
document id, or CFR clause: every one of those is injected by code from the source
record. This module scrubs any that slip into model-generated text and records a
flag for each kind removed, so a reviewer can see the model tried to assert one.

`scrub(text)` returns (clean_text, flags) where flags is a sorted list of the
categories that were removed (e.g. ["date", "doc_id", "url"]). Deterministic and
network-free, so it is safe to unit-test.
"""

import re

# Full and abbreviated month names, with an optional trailing period.
_MONTHS = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
           r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|"
           r"Dec(?:ember)?)\.?")

# Order matters: strip full URLs first, then structured ids, then dates, then
# bare domains, then any remaining long digit run last. Each pattern that fires
# records its flag so a reviewer can see the model tried to assert a citation.
_PATTERNS = [
    # --- URLs ---
    ("url",      re.compile(r"https?://[^\s<>\"']+", re.I)),
    ("url",      re.compile(r"\bwww\.\S+", re.I)),
    # --- document ids ---
    # FDA submission ids: K260047, P123456, DEN240001, BK/DK variants.
    ("doc_id",   re.compile(r"\b(?:K|P|DEN|BK|DK|Q)\d{6,7}\b")),
    # FDA docket ids, e.g. FDA-2026-N-1234.
    ("doc_id",   re.compile(r"\bFDA-\d{4}-[A-Z]-\d+\b", re.I)),
    # MDCG endorsed-document numbers, e.g. "MDCG 2024-13", "MDCG 2022-5 rev.1".
    ("doc_id",   re.compile(r"\bMDCG[\s-]?\d{4}-\d+(?:\s?rev\.?\s?\d+)?\b", re.I)),
    # EU regulation/directive slash form, e.g. "(EU) 2017/746", "2017/746" (IVDR).
    ("doc_id",   re.compile(r"\b(?:\(EU\)\s*)?(?:19|20)\d{2}/\d{1,4}\b")),
    # Federal Register / OMB document numbers, e.g. "2026-13534" (5-6 trailing
    # digits, so ordinary four-digit year ranges like "2019-2024" are left alone).
    ("doc_id",   re.compile(r"\b\d{4}-\d{5,6}\b")),
    # --- CFR citations: "42 CFR 493", "21 CFR Part 820", "21 C.F.R. § 809.10" ---
    ("cfr_cite", re.compile(
        r"\b\d{1,2}\s?C\.?\s?F\.?\s?R\.?\s?(?:part\s+|§\s*)?\d+(?:\.\d+)?\b", re.I)),
    # --- dates ---
    ("date",     re.compile(r"\b\d{4}-\d{2}-\d{2}\b")),               # ISO
    ("date",     re.compile(r"\b\d{4}/\d{1,2}/\d{1,2}\b")),           # yyyy/mm/dd
    ("date",     re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")),         # dd/mm/yyyy
    ("date",     re.compile(rf"\b{_MONTHS}\s+\d{{1,2}},?\s+\d{{4}}\b", re.I)),
    ("date",     re.compile(rf"\b\d{{1,2}}\s+{_MONTHS}\s+\d{{4}}\b", re.I)),
    ("date",     re.compile(rf"\b{_MONTHS}\s+\d{{4}}\b", re.I)),      # month + year
    # --- bare domains without a scheme, e.g. "fda.gov/x", "health.ec.europa.eu" ---
    ("url",      re.compile(r"\b(?:[a-z0-9-]+\.)+(?:gov|int|eu)\b(?:/\S*)?", re.I)),
    ("url",      re.compile(r"\b(?:[a-z0-9-]+\.)+(?:com|org|net|io)\b/\S*", re.I)),
    # --- any remaining long digit run (>=7) is almost certainly an invented id ---
    ("number",   re.compile(r"\b\d{7,}\b")),
]

_EM_EN_DASH = re.compile(r"\s*[—–]\s*")     # em / en dash used as a pause
_MULTISPACE = re.compile(r"[ \t]{2,}")
_SPACE_PUNCT = re.compile(r"\s+([,.;:!?])")
_EMPTY_WRAP = re.compile(r"[(\[]\s*[)\]]")            # leftover "()" / "[]"
_DANGLING = re.compile(r"[ \t]*[(,;:]\s*(?=[.\n]|$)")


def scrub(text):
    """Return (clean_text, flags). Idempotent-ish and safe on empty input."""
    if not text:
        return "", []
    flags = set()
    out = text

    for name, pat in _PATTERNS:
        if pat.search(out):
            flags.add(name)
            out = pat.sub("", out)

    # No em dashes anywhere in body/UI: turn a dash-as-pause into a comma.
    if _EM_EN_DASH.search(out):
        flags.add("em_dash")
        out = _EM_EN_DASH.sub(", ", out)

    # Tidy the wreckage left by removals.
    out = _EMPTY_WRAP.sub("", out)
    out = _DANGLING.sub("", out)
    out = _SPACE_PUNCT.sub(r"\1", out)
    out = _MULTISPACE.sub(" ", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = re.sub(r"(?m)^[ \t]+", "", out)
    out = out.strip()

    return out, sorted(flags)
