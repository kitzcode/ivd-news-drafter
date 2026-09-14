"""
V2 topic tagging. Runs over already-fetched items (no network). Adds:

  - item["region"]      -> "US" | "EU"  (kept from the source; defaults to US)
  - item["source_tags"] -> list[str]    e.g. ["FDA"], ["CMS", "CLIA"], ["IVDR"]

CMS and CLIA are TOPIC LENSES over the existing Federal Register / CMS feed, not
new endpoints (see config.CMS_LENS / config.CLIA_LENS). This is deterministic
keyword matching, so it never invents a classification.
"""

import config


def _haystack(item):
    return (item.get("title", "") + " " + item.get("summary", "") + " "
            + item.get("source", "")).lower()


def _source_family(item):
    """Coarse family tag from the source label, for display grouping."""
    src = (item.get("source") or "").lower()
    if "federal register" in src:
        return "FederalRegister"
    if "openfda" in src or "510(k)" in src or "enforcement" in src:
        return "FDA"
    if "mdcg" in src:
        return "IVDR"
    if "commission" in src:
        return "EU-Policy"
    if "cap" in src:
        return "CAP"
    return "Other"


def tag_item(item):
    """Attach region + source_tags to a single item. Returns the same item."""
    item.setdefault("region", "US")
    tags = [_source_family(item)]

    hay = _haystack(item)
    if any(k in hay for k in config.CMS_LENS):
        tags.append("CMS")
    if any(k in hay for k in config.CLIA_LENS):
        tags.append("CLIA")

    # de-dupe, keep order
    seen, ordered = set(), []
    for t in tags:
        if t and t not in seen:
            seen.add(t)
            ordered.append(t)
    item["source_tags"] = ordered
    return item


def tag_all(items):
    return [tag_item(it) for it in items]
