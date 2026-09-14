"""Tracks URLs already processed so the same story is never drafted twice."""

import json
import config


def load_seen(path=None):
    path = path or config.CACHE_FILE
    try:
        with open(path, "r") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_seen(seen, path=None):
    path = path or config.CACHE_FILE
    with open(path, "w") as f:
        json.dump(sorted(seen), f, indent=2)


def drop_seen(items, seen):
    """Return only items whose URL has not been seen before."""
    fresh = []
    for it in items:
        url = it.get("url", "")
        if url and url not in seen:
            fresh.append(it)
    return fresh
