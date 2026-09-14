"""
IVD / diagnostics / regulatory news -> LinkedIn draft pipeline.

Usage:
    python main.py                 # full run (uses Claude, writes drafts)
    python main.py --dry-run       # fetch + filter only, no Claude calls, no writes
    python main.py --ignore-seen   # re-draft items even if already processed
                                   # (use after changing the voice in voice.py)
    python main.py --v2            # RegWatch V2: adds CMS/CLIA lens, CAP, EU IVDR
                                   # sources + a per-role practitioner read; writes
                                   # docs/drafts_v2.json (default output untouched)
    python main.py --v2 --dry-run  # V2 fetch + tag + filter only, no Claude, no writes

The tool only writes draft files. It never posts anywhere. You review and post.
"""

import argparse

from dotenv import load_dotenv

import sources
import filtering
import cache
import claude_client
import writer
import tagging
import practitioner
import config


def run(dry_run=False, ignore_seen=False, v2=False):
    if v2:
        return run_v2(dry_run=dry_run, ignore_seen=ignore_seen)
    load_dotenv()

    print("1. Fetching sources...")
    items = sources.fetch_all()
    print(f"   -> {len(items)} total\n")

    print("2. Keyword pre-filter...")
    items = filtering.keyword_filter(items)
    print(f"   -> {len(items)} relevant by keyword\n")

    seen = cache.load_seen()
    if ignore_seen:
        print("3. Ignoring the seen-cache (re-drafting everything in the window).\n")
    else:
        print("3. Dropping already-seen stories...")
        items = cache.drop_seen(items, seen)
        print(f"   -> {len(items)} new\n")

    if dry_run:
        print("DRY RUN. Items that would go to Claude:\n")
        for it in items:
            print(f"  - [{it['source']}] {it['title']}")
            print(f"    {it['url']}")
        print("\nNo Claude calls made, nothing written. "
              "Confirm these look right, then run without --dry-run.")
        return

    if not items:
        print("Nothing to draft. Done.")
        return

    print("4. Ranking relevance (batched Claude call)...")
    selected = claude_client.score_and_select(items)
    print(f"   -> {len(selected)} selected\n")

    print("5. Summarizing + drafting...")
    drafted = [claude_client.summarize_and_draft(it) for it in selected]

    print("6. Writing outputs...")
    n = writer.write_outputs(drafted)

    for it in selected:
        if it.get("url"):
            seen.add(it["url"])
    cache.save_seen(seen)

    print(f"\nDone. {n} draft(s) written to docs/drafts.json and the archive.")
    print("Open the review site (or the dated file in drafts/), pick one, post it yourself.")


def run_v2(dry_run=False, ignore_seen=False):
    """RegWatch V2: reuses the same pipeline, adds the new sources, the region +
    CMS/CLIA tagging lens, and the per-role practitioner read. Writes a SEPARATE
    output (docs/drafts_v2.json + drafts/v2/); the default output is never touched."""
    load_dotenv()

    # V2 uses a wider lookback than the default run. The fetchers read
    # config.LOOKBACK_DAYS, so set it to the V2 window for this process. A single
    # invocation is either --v2 or not, so the default run never sees this.
    config.LOOKBACK_DAYS = config.LOOKBACK_DAYS_V2

    print(f"1. Fetching sources (V2, last {config.LOOKBACK_DAYS} days: "
          "+ FedReg IVD/CLIA terms, CAP, EU IVDR/MDCG, optional EU press)...")
    items = sources.fetch_all_v2()
    print(f"   -> {len(items)} total\n")

    print("2. Tagging (region + CMS/CLIA topic lens)...")
    items = tagging.tag_all(items)

    print("3. Keyword pre-filter...")
    items = filtering.keyword_filter(items)
    print(f"   -> {len(items)} relevant by keyword\n")

    seen = cache.load_seen(config.CACHE_FILE_V2)
    if ignore_seen:
        print("4. Ignoring the V2 seen-cache (re-processing everything in the window).\n")
    else:
        print("4. Dropping already-seen stories...")
        items = cache.drop_seen(items, seen)
        print(f"   -> {len(items)} new\n")

    if dry_run:
        print("DRY RUN (V2). Items that would go to Claude:\n")
        for it in items:
            tags = ", ".join([it.get("region", "US")] + it.get("source_tags", []))
            thin = "  [force-thin]" if it.get("force_thin") else ""
            print(f"  - [{it['source']}] ({tags}){thin} {it['title']}")
            print(f"    {it['url']}")
        print("\nNo Claude calls made, nothing written.")
        return

    if not items:
        print("Nothing to draft. Done.")
        return

    print("5. Ranking relevance (batched Claude call)...")
    selected = claude_client.score_and_select(items, prefer_regulatory_changes=True)
    print(f"   -> {len(selected)} selected\n")

    print("6. Building per-role practitioner reads...")
    drafted = [practitioner.practitioner_read(it) for it in selected]

    print("7. Writing V2 outputs...")
    n = writer.write_outputs_v2(drafted)

    # Mark seen ONLY for items that actually produced a written record. If a
    # practitioner read fully failed (empty output), the item is left unseen so a
    # later run retries it, rather than being burned into the cache and skipped.
    for it in drafted:
        if it.get("url") and (it.get("reads") or it.get("what_changed")):
            seen.add(it["url"])
    cache.save_seen(seen, config.CACHE_FILE_V2)

    thin_n = sum(1 for it in drafted if it.get("thin_source"))
    flagged = sum(1 for it in drafted if it.get("sanitize_flags"))
    print(f"\nDone. {n} V2 item(s) written to docs/drafts_v2.json and drafts/v2/.")
    print(f"   thin_source items: {thin_n}   sanitizer-flagged items: {flagged}")
    print("Review, adjudicate applicability yourself, then write your own post.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch + filter only; no Claude calls, no writes")
    ap.add_argument("--ignore-seen", action="store_true",
                    help="re-draft items even if already processed (e.g. after changing voice)")
    ap.add_argument("--v2", action="store_true",
                    help="RegWatch V2: new sources + per-role practitioner read; separate output")
    run(**vars(ap.parse_args()))
