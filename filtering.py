"""Cheap keyword pre-filter, run before any Claude call."""

import config


def keyword_filter(items):
    kept = []
    for it in items:
        # openFDA items are already screened by device panel at the source,
        # so they bypass the keyword pass (their text wouldn't contain the
        # right terms anyway -- e.g. "BD BACTEC Culture System").
        if it.get("prequalified"):
            kept.append(it)
            continue
        hay = (it.get("title", "") + " " + it.get("summary", "")).lower()
        if any(kw in hay for kw in config.KEYWORDS):
            kept.append(it)
    return kept
