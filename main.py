"""
IVD / diagnostics / regulatory news -> LinkedIn draft pipeline.

Usage:
    python main.py                 # full run (uses Claude, writes drafts)
    python main.py --dry-run       # fetch + filter only, no Claude calls, no writes
    python main.py --ignore-seen   # re-draft items even if already processed
                                   # (use after changing the voice in voice.py)

The tool only writes draft files. It never posts anywhere. You review and post.
"""

import argparse

from dotenv import load_dotenv

import sources
import filtering
import cache
import claude_client
import writer


def run(dry_run=False, ignore_seen=False):
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


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch + filter only; no Claude calls, no writes")
    ap.add_argument("--ignore-seen", action="store_true",
                    help="re-draft items even if already processed (e.g. after changing voice)")
    run(**vars(ap.parse_args()))
