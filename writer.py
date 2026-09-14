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


def _v2_record(it):
    """One V2 output record. Citations (url, date) are code-injected here from the
    source item, never from the model. No em dashes anywhere."""
    reads = it.get("reads", [])
    return {
        "title": it.get("title", ""),
        "source": it.get("source", ""),
        "region": it.get("region", "US"),
        "source_tags": it.get("source_tags", []),
        "url": it.get("url", ""),                 # code-injected citation
        "source_date": it.get("date", ""),        # code-injected citation
        "why": it.get("why", ""),
        "confidence": it.get("confidence", "low"),
        "what_changed": it.get("what_changed", ""),
        "thin_source": bool(it.get("thin_source")),
        "thin_source_reason": it.get("thin_source_reason", ""),
        "roles": sorted({r.get("role", "") for r in reads if r.get("role")}),
        "lifecycle": sorted({p for r in reads for p in r.get("lifecycle", [])}),
        "reads": reads,
        "linkedin_stub": it.get("draft", ""),     # deliberately bare
        "sanitize_flags": it.get("sanitize_flags", []),
    }


def write_outputs_v2(drafted):
    """
    Write the V2 outputs, fully separate from the default run:
      docs/drafts_v2.json  +  drafts/v2/<date>.md
    Keeps an item if it produced either a practitioner read or a what_changed line.
    """
    config.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    config.ARCHIVE_DIR_V2.mkdir(parents=True, exist_ok=True)
    today = _dt.date.today().isoformat()

    records = [_v2_record(it) for it in drafted
               if it.get("reads") or it.get("what_changed")]

    payload = {"generated": today, "count": len(records), "version": "v2",
               "drafts": records}
    with open(config.DRAFTS_JSON_V2, "w") as f:
        json.dump(payload, f, indent=2)

    md = [f"# RegWatch V2 practitioner reads: {today}\n"]
    if not records:
        md.append("_No relevant items this run._\n")
    for i, r in enumerate(records, 1):
        thin = "  [thin source]" if r["thin_source"] else ""
        tags = ", ".join([r["region"]] + r["source_tags"])
        md.append(f"## {i}. {r['title']}{thin}\n")
        md.append(f"**Tags:** {tags}\n")
        if r["what_changed"]:
            md.append(f"**What the source says:** {r['what_changed']}\n")
        if r["thin_source"] and r["thin_source_reason"]:
            md.append(f"_Thin source: {r['thin_source_reason']}. "
                      f"Naming a concrete artifact would be guessing._\n")
        if r["reads"]:
            md.append("**Practitioner read (proposed, check applicability):**\n")
            for rd in r["reads"]:
                phases = ", ".join(rd["lifecycle"]) or "n/a"
                md.append(f"- **{rd['role']} ({rd['role_label']})** lands in: {phases}\n"
                          f"  - Artifact: {rd['artifact']}\n"
                          f"  - Action: {rd['action']}\n")
        md.append("**LinkedIn stub (bare by design):**\n\n" + r["linkedin_stub"] + "\n")
        if r["sanitize_flags"]:
            md.append(f"_Sanitizer stripped model-emitted: {', '.join(r['sanitize_flags'])}._\n")
        md.append(f"**Source:** {r['source']} : {r['url']}\n")
        md.append("\n---\n")
    with open(config.ARCHIVE_DIR_V2 / f"{today}.md", "w") as f:
        f.write("\n".join(md))

    write_self_contained_review(payload)
    return len(records)


def _inline_data_script(payload):
    """Build the `<script>window.__V2_DATA__ = ...;</script>` blob for the
    self-contained review page. Escapes '<' as \\u003c across the WHOLE serialized
    JSON so a literal </script> inside any string (title, abstract, action) can
    never close the script element early, and escapes the JS line separators
    U+2028/U+2029 which are invalid raw in a script literal."""
    blob = (json.dumps(payload)
            .replace("<", "\\u003c")
            .replace(" ", "\\u2028")
            .replace(" ", "\\u2029"))
    return "<script>window.__V2_DATA__ = " + blob + ";</script>\n"


def write_self_contained_review(payload):
    """
    Emit docs/drafts_v2_review.html: the index_v2.html review page with the run's
    data inlined, so it renders on any device with no server or sibling JSON file.
    The page's own esc()/safeUrl() still run on every field at render time; this
    only changes where `data` comes from. Defensive: if the template is missing or
    unreadable, skip silently (the fetch-based index_v2.html + drafts_v2.json still
    work). Returns the output path, or None if skipped.
    """
    template = config.DOCS_DIR / "index_v2.html"
    out = config.DOCS_DIR / "drafts_v2_review.html"
    try:
        html = template.read_text()
    except OSError:
        return None
    # Inject just before the first <script> so the hook is defined before load().
    marker = "<script>"
    if marker not in html:
        return None
    inlined = html.replace(marker, _inline_data_script(payload) + marker, 1)
    out.write_text(inlined)
    return out
