"""
Claude calls. Two steps:
  1. score_and_select: ONE batched call ranks relevance + dedupes, returns top N.
  2. summarize_and_draft: one call per selected item -> summary + post draft.

Uses the official `anthropic` SDK. The key is read from ANTHROPIC_API_KEY in the
environment (loaded from .env by main.py). No key is ever written to output.
"""

import json
import anthropic

import config
from voice import voice_system

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    return _client


def _extract_text(message):
    """Join all text blocks of a Messages API response."""
    return "".join(b.text for b in message.content if getattr(b, "type", None) == "text")


def _parse_json(text):
    """Parse JSON, tolerating stray markdown fences."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    return json.loads(cleaned.strip())


def score_and_select(items, max_drafts=None):
    """
    One batched call. Returns a list of selected items, each annotated with
    'why' (one line) and 'confidence' ('high' | 'low').
    """
    if not items:
        return []
    max_drafts = max_drafts or config.MAX_DRAFTS

    catalog = [
        {"i": idx, "title": it["title"], "summary": it["summary"][:400], "source": it["source"]}
        for idx, it in enumerate(items)
    ]
    prompt = (
        "You are screening news items for an IVD / diagnostics / regulatory "
        "professional who wants to post about the most relevant ones on LinkedIn.\n\n"
        f"From the list below, pick at most {max_drafts} items that are genuinely "
        "relevant to in-vitro diagnostics, point-of-care testing, CLIA/lab regulation, "
        "or FDA diagnostic device actions. Drop near-duplicates and anything off-topic. "
        "If nothing is clearly relevant, return fewer (or none).\n\n"
        "Return ONLY a JSON array, no prose, each element:\n"
        '{"i": <index>, "why": "<one short line on why it matters>", '
        '"confidence": "high" | "low"}\n\n'
        f"ITEMS:\n{json.dumps(catalog, indent=2)}"
    )
    try:
        msg = _get_client().messages.create(
            model=config.MODEL_FILTER,
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        picks = _parse_json(_extract_text(msg))
    except Exception as e:
        print(f"  [warn] relevance pass failed ({e}); falling back to first {max_drafts}")
        return items[:max_drafts]

    selected = []
    for p in picks[:max_drafts]:
        idx = p.get("i")
        if isinstance(idx, int) and 0 <= idx < len(items):
            it = dict(items[idx])
            it["why"] = p.get("why", "")
            it["confidence"] = p.get("confidence", "low")
            selected.append(it)
    return selected


def summarize_and_draft(item):
    """One call: returns the item with 'tl_summary' and 'draft' added."""
    prompt = (
        "Source item (use only facts present here; invent nothing):\n"
        f"TITLE: {item['title']}\n"
        f"SOURCE: {item['source']}\n"
        f"URL: {item['url']}\n"
        f"TEXT: {item['summary']}\n\n"
        "Return ONLY JSON, no prose:\n"
        '{"summary": "<2-3 plain lines summarizing the item>", '
        '"draft": "<the LinkedIn post, following the voice rules>"}'
    )
    try:
        msg = _get_client().messages.create(
            model=config.MODEL_DRAFT,
            max_tokens=900,
            system=voice_system(),
            messages=[{"role": "user", "content": prompt}],
        )
        out = _parse_json(_extract_text(msg))
        item["tl_summary"] = out.get("summary", "")
        item["draft"] = out.get("draft", "")
    except Exception as e:
        print(f"  [warn] draft failed for '{item['title'][:50]}': {e}")
        item["tl_summary"] = ""
        item["draft"] = ""
    return item
