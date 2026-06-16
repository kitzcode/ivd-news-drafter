"""Writes outputs: docs/drafts.json (for the static site) + a dated markdown archive."""

import datetime as _dt
import json

import config


def write_outputs(drafted):
    config.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    config.ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    today = _dt.date.today().isoformat()

    records = [{
        "title": it["title"],
        "source": it["source"],
        "url": it["url"],
        "why": it.get("why", ""),
        "confidence": it.get("confidence", "low"),
        "summary": it.get("tl_summary", ""),
        "draft": it.get("draft", ""),
        "source_date": it.get("date", ""),
    } for it in drafted if it.get("draft")]

    payload = {"generated": today, "count": len(records), "drafts": records}
    with open(config.DRAFTS_JSON, "w") as f:
        json.dump(payload, f, indent=2)

    # human-readable archive
    md = [f"# IVD / diagnostics drafts \u2014 {today}\n"]
    if not records:
        md.append("_No relevant items this run._\n")
    for i, r in enumerate(records, 1):
        flag = "  (low confidence)" if r["confidence"] == "low" else ""
        md.append(f"## {i}. {r['title']}{flag}\n")
        md.append(f"**Why:** {r['why']}\n")
        md.append(f"**Summary:** {r['summary']}\n")
        md.append("**Draft:**\n\n" + r["draft"] + "\n")
        md.append(f"**Source:** {r['source']} \u2014 {r['url']}\n")
        md.append("\n---\n")
    with open(config.ARCHIVE_DIR / f"{today}.md", "w") as f:
        f.write("\n".join(md))

    return len(records)
