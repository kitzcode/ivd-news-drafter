"""
Source fetchers. Each returns a list of normalized dicts:

    {"title": str, "summary": str, "url": str, "source": str, "date": "YYYY-MM-DD"}

Everything here is defensive: a failing source prints a warning and returns [],
so one broken source never kills the run.
"""

import datetime as _dt
import requests

import config


# Advisory-committee panels that correspond to IVDs (confirmed against live
# openFDA data). Matched case-insensitively as substrings, since some values
# are combined like "Hematology and Pathology".
IVD_PANELS = (
    "clinical chemistry", "clinical toxicology", "toxicology",
    "hematology", "pathology", "immunology", "microbiology",
    "molecular genetics",
)


def _since_date(days):
    return (_dt.date.today() - _dt.timedelta(days=days)).isoformat()


def fetch_federal_register():
    cfg = config.SOURCES["federal_register"]
    if not cfg.get("enabled"):
        return []
    params = {
        "per_page": cfg["per_page"],
        "order": "newest",
        "conditions[publication_date][gte]": _since_date(config.LOOKBACK_DAYS),
        "conditions[agencies][]": cfg["agencies"],
    }
    try:
        r = requests.get(cfg["base_url"], params=params, timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [warn] federal_register fetch failed: {e}")
        return []

    items = []
    for row in data.get("results", []):
        items.append({
            "title": (row.get("title") or "").strip(),
            "summary": (row.get("abstract") or "").strip(),
            "url": row.get("html_url") or "",
            "source": "Federal Register",
            "date": row.get("publication_date") or "",
        })
    return items


def fetch_openfda_510k():
    cfg = config.SOURCES["openfda_510k"]
    if not cfg.get("enabled"):
        return []
    start = _since_date(config.LOOKBACK_DAYS)            # ISO, keep dashes
    end = _dt.date.today().isoformat()                  # ISO, keep dashes
    params = {
        "search": f"decision_date:[{start} TO {end}]",  # space, not +TO+
        "limit": cfg["limit"],
    }
    try:
        r = requests.get(cfg["base_url"], params=params, timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [warn] openfda_510k fetch failed: {e}")
        return []

    items = []
    for row in data.get("results", []):
        # Keep only IVD device panels. Most 510(k)s are surgical/therapeutic
        # devices; IVDs sit under these advisory committees.
        panel = (row.get("advisory_committee_description") or "").lower()
        if not any(p in panel for p in IVD_PANELS):
            continue
        k = row.get("k_number", "")
        name = row.get("device_name") or "Device 510(k)"
        applicant = row.get("applicant") or ""
        panel_label = row.get("advisory_committee_description") or "IVD"
        url = (f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID={k}"
               if k else "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm")
        items.append({
            "title": f"FDA 510(k): {name}",
            "summary": f"510(k) clearance ({panel_label} panel). Applicant: {applicant}. Number: {k}.",
            "url": url,
            "source": "openFDA 510(k)",
            "date": row.get("decision_date") or "",
            "prequalified": True,   # already screened by device panel; skip keyword pass
        })
    return items


def fetch_openfda_enforcement():
    cfg = config.SOURCES["openfda_enforcement"]
    if not cfg.get("enabled"):
        return []
    start = _since_date(config.LOOKBACK_DAYS)
    end = _dt.date.today().isoformat()
    params = {
        "search": f"report_date:[{start} TO {end}]",
        "limit": cfg["limit"],
    }
    try:
        r = requests.get(cfg["base_url"], params=params, timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  [warn] openfda_enforcement fetch failed: {e}")
        return []

    items = []
    for row in data.get("results", []):
        items.append({
            "title": f"FDA device recall: {row.get('product_description', 'device')[:80]}",
            "summary": (row.get("reason_for_recall") or "")[:300],
            "url": "https://www.fda.gov/medical-devices/medical-device-recalls",
            "source": "openFDA enforcement",
            "date": row.get("report_date") or "",
        })
    return items


def fetch_genomeweb():
    """
    Pull recent headlines + links from the GenomeWeb POC category page.
    Headlines only -- never article bodies. The post draft is original
    commentary that links back to the source.

    CAVEATS (see README):
      - GenomeWeb is a subscription publication. Confirm their ToS / robots.txt
        permit automated access before you rely on this.
      - The page may be JS-rendered or partly paywalled; if it returns few/no
        items under --dry-run, requests can't run JS and this approach won't work.
      - Reliable publish dates aren't available without fetching each article, so
        this returns the most-recent headlines from the page (date left blank) and
        leans on the seen-cache to avoid repeats.
    """
    cfg = config.SOURCES["genomeweb"]
    if not cfg.get("enabled"):
        return []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print("  [warn] beautifulsoup4 not installed; skipping genomeweb "
              "(run: pip install beautifulsoup4)")
        return []

    headers = {"User-Agent": "Mozilla/5.0 (personal news monitor)"}
    try:
        r = requests.get(cfg["url"], headers=headers, timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  [warn] genomeweb fetch failed: {e}")
        return []

    skip_segments = ("/about", "/subscribe", "/login", "/topic", "/contact",
                     "/advertise", "/account", "/user", "/search", "/webinars")
    items, seen_urls = [], set()
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        href = a["href"]
        if len(text) < 25:               # filter nav/buttons; keep real headlines
            continue
        if href.startswith("/"):
            href = "https://www.genomeweb.com" + href
        if "genomeweb.com" not in href or href in seen_urls:
            continue
        if any(seg in href for seg in skip_segments):
            continue
        seen_urls.add(href)
        items.append({
            "title": text,
            "summary": text,            # headline only
            "url": href,
            "source": "GenomeWeb (POC)",
            "date": "",                 # approximate; see docstring
        })
        if len(items) >= cfg["max_items"]:
            break
    return items


def fetch_rss():
    cfg = config.SOURCES["rss"]
    if not cfg.get("enabled") or not cfg.get("feeds"):
        return []
    try:
        import feedparser
    except ImportError:
        print("  [warn] feedparser not installed; skipping RSS")
        return []

    items = []
    for url in cfg["feeds"]:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                items.append({
                    "title": entry.get("title", "").strip(),
                    "summary": entry.get("summary", "").strip(),
                    "url": entry.get("link", ""),
                    "source": feed.feed.get("title", "RSS"),
                    "date": entry.get("published", ""),
                })
        except Exception as e:
            print(f"  [warn] RSS fetch failed for {url}: {e}")
    return items


def _within_window(item):
    """
    Keep items whose date is within LOOKBACK_DAYS. Items with no parseable date
    (e.g. GenomeWeb headlines) are kept -- the source-level query already scopes
    the dated ones.
    """
    raw = (item.get("date") or "")[:10]
    if not raw:
        return True
    try:
        d = _dt.date.fromisoformat(raw)
    except ValueError:
        return True
    return d >= (_dt.date.today() - _dt.timedelta(days=config.LOOKBACK_DAYS))


def fetch_all():
    """Run every enabled source, apply the date window, return the combined list."""
    items = []
    for fn in (fetch_federal_register, fetch_openfda_510k, fetch_openfda_enforcement,
               fetch_genomeweb, fetch_rss):
        got = [it for it in fn() if _within_window(it)]
        print(f"  {fn.__name__}: {len(got)} item(s)")
        items.extend(got)
    return items
