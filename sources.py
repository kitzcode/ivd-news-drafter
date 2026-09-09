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


def _scrape_headlines(url, domain, source_label, max_items):
    """
    Pull recent headlines + links from a category page. Headlines only -- never
    article bodies. The post draft is original commentary that links back.

    CAVEATS (see README): these are subscription publications. Confirm ToS /
    robots.txt permit automated access. Pages may be JS-rendered or paywalled; if
    a page returns few/no items, `requests` can't run JS and this won't work.
    Reliable publish dates aren't available without fetching each article, so this
    returns the most-recent headlines (date left blank) and leans on the seen-cache
    to avoid repeats.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print(f"  [warn] beautifulsoup4 not installed; skipping {source_label} "
              "(run: pip install beautifulsoup4)")
        return []

    headers = {"User-Agent": "Mozilla/5.0 (personal news monitor)"}
    try:
        r = requests.get(url, headers=headers, timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  [warn] {source_label} fetch failed: {e}")
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
            href = f"https://www.{domain}" + href
        if domain not in href or href in seen_urls:
            continue
        if any(seg in href for seg in skip_segments):
            continue
        seen_urls.add(href)
        items.append({
            "title": text,
            "summary": text,            # headline only
            "url": href,
            "source": source_label,
            "date": "",                 # approximate; see docstring
        })
        if len(items) >= max_items:
            break
    return items


def fetch_genomeweb():
    cfg = config.SOURCES["genomeweb"]
    if not cfg.get("enabled"):
        return []
    return _scrape_headlines(cfg["url"], "genomeweb.com", "GenomeWeb (POC)",
                             cfg["max_items"])


def fetch_360dx():
    cfg = config.SOURCES["360dx"]
    if not cfg.get("enabled"):
        return []
    return _scrape_headlines(cfg["url"], "360dx.com", "360Dx", cfg["max_items"])


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
            # Fetch with an explicit timeout, then hand bytes to feedparser.
            # feedparser.parse(url) would do its own fetch with NO timeout and can
            # hang the whole run on a slow feed.
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (personal news monitor)"},
                             timeout=config.REQUEST_TIMEOUT)
            r.raise_for_status()
            feed = feedparser.parse(r.content)
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


# ---------------------------------------------------------------------------
# V2 source adapters. Same normalized-dict interface as above, plus optional
# V2-only keys: "region" (US|EU) and "force_thin" (source is announcement-level).
# Every fetcher is defensive: failure prints a warning and returns [].
# ---------------------------------------------------------------------------

def _scrape_links(url, base_origin, source_label, region, max_items,
                  keep_predicate, force_thin=False):
    """
    Generic anchor scraper for V2 HTML pages. Pulls (text, href) pairs the
    caller's `keep_predicate(text, href)` accepts. Headlines / document titles
    only, never article or document bodies. Relative hrefs are resolved against
    `base_origin` (a full scheme+host, e.g. "https://health.ec.europa.eu").

    CAVEAT: these public pages may be JS-rendered; `requests` cannot run JS, so a
    page that returns few/no items simply yields fewer items (never an error).
    Publish dates are not reliably available without fetching each item, so date
    is left blank and the seen-cache prevents repeats.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print(f"  [warn] beautifulsoup4 not installed; skipping {source_label}")
        return []

    headers = {"User-Agent": "Mozilla/5.0 (personal news monitor)"}
    try:
        r = requests.get(url, headers=headers, timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  [warn] {source_label} fetch failed: {e}")
        return []

    items, seen_urls = [], set()
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        href = a["href"]
        if href.startswith("/"):
            href = base_origin.rstrip("/") + href
        if not href.startswith("http"):
            continue
        if not keep_predicate(text, href):
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)
        items.append({
            "title": text[:200],
            "summary": text[:200],       # link text only; never the body
            "url": href,
            "source": source_label,
            "date": "",
            "region": region,
            "prequalified": True,        # topically scoped by the page itself
            "force_thin": force_thin,
        })
        if len(items) >= max_items:
            break
    return items


def fetch_federal_register_ivd():
    """
    Targeted Federal Register queries by precise IVD/CLIA phrases (see config). The
    default agency feed is capped at the 40 newest docs with no topic filter, so it
    misses substantive IVD regulatory changes older than that. This queries by term
    so rules / proposed rules / guidances / CLIA + coverage actions are caught, with
    their real abstracts. Deduped by document number across terms. Not prequalified,
    so the keyword filter still screens the results.
    """
    cfg = config.SOURCES.get("federal_register_ivd", {})
    if not cfg.get("enabled"):
        return []
    since = _since_date(config.LOOKBACK_DAYS)
    items, seen_docs = [], set()
    for term in cfg.get("terms", []):
        params = {
            "per_page": cfg.get("per_page", 50),
            "order": "newest",
            "conditions[term]": term,
            "conditions[publication_date][gte]": since,
        }
        try:
            r = requests.get(cfg["base_url"], params=params, timeout=config.REQUEST_TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"  [warn] federal_register_ivd term={term!r} failed: {e}")
            continue
        for row in data.get("results", []):
            doc = row.get("document_number") or row.get("html_url") or ""
            if doc and doc in seen_docs:
                continue
            if doc:
                seen_docs.add(doc)
            dtype = (row.get("type") or "").strip()
            title = (row.get("title") or "").strip()
            items.append({
                # Lead with the document type so a reader and the relevance pass can
                # tell a Rule / Proposed Rule from a routine Notice at a glance.
                "title": (f"{dtype}: {title}" if dtype else title)[:200],
                "summary": (row.get("abstract") or "").strip(),
                "url": row.get("html_url") or "",
                "source": "Federal Register",
                "date": row.get("publication_date") or "",
                "region": cfg.get("region", "US"),
            })
    return items


def fetch_cap():
    """
    CAP public newsroom. Announcement-level only (see config caveat). Every item
    is force_thin: it signals THAT a checklist edition / accreditation update was
    announced, not what concretely changed. Membership-gated content is never hit.
    """
    cfg = config.SOURCES["cap"]
    if not cfg.get("enabled"):
        return []
    domain = cfg["domain"]
    interest = ("checklist", "accreditation", "clia", "laboratory", "reimburse",
                "payment", "regulation", "proficiency", "standard", "coverage",
                "quality")

    def keep(text, href):
        if len(text) < 25:
            return False
        if domain not in href:
            return False
        low = (text + " " + href).lower()
        return any(k in low for k in interest)

    return _scrape_links(cfg["url"], f"https://www.{domain}", "CAP (newsroom)",
                         cfg["region"], cfg["max_items"], keep, force_thin=True)


def fetch_eu_mdcg():
    """
    EU IVDR guidance: MDCG endorsed-documents page. Captures the guidance-document
    listing (titles + links). The best available public EU IVDR access path.
    """
    cfg = config.SOURCES["eu_mdcg"]
    if not cfg.get("enabled"):
        return []
    domain = cfg["domain"]

    def keep(text, href):
        if len(text) < 8:
            return False
        # Only actual endorsed-document downloads ON THE CONFIGURED HOST. Requiring
        # the domain stops an injected off-host "/document/download" link from being
        # stored as a trusted "open source" target. This also excludes language
        # switchers and other site nav. NOTE: the page carries both MDR and IVDR
        # guidance; the downstream relevance pass narrows to IVD.
        return domain in href and "/document/download" in href

    return _scrape_links(cfg["url"], f"https://{domain}", "EU MDCG (IVDR guidance)",
                         cfg["region"], cfg["max_items"], keep)


def fetch_eu_presscorner():
    """
    EU policy news: European Commission press-corner RSS, filtered to the IVD
    keyword set. Coarse; off by default. region EU.
    """
    cfg = config.SOURCES["eu_presscorner"]
    if not cfg.get("enabled"):
        return []
    try:
        import feedparser
    except ImportError:
        print("  [warn] feedparser not installed; skipping eu_presscorner")
        return []
    try:
        r = requests.get(cfg["url"],
                         headers={"User-Agent": "Mozilla/5.0 (personal news monitor)"},
                         timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        feed = feedparser.parse(r.content)
    except Exception as e:
        print(f"  [warn] eu_presscorner fetch failed: {e}")
        return []

    items = []
    for entry in feed.entries[:cfg["max_items"]]:
        items.append({
            "title": (entry.get("title") or "").strip(),
            "summary": (entry.get("summary") or entry.get("title") or "").strip()[:400],
            "url": entry.get("link", ""),
            "source": "EU Commission (press)",
            "date": "",   # RSS pubDate parsing left to the window filter if present
            "region": cfg["region"],
            # not prequalified: must pass the IVD keyword filter to survive
        })
    return items


def fetch_all_v2():
    """
    V2 feed: every enabled default source PLUS the V2 adapters. Used only by the
    `--v2` run. Items carry a `region` (defaulting to US for the legacy sources).
    """
    items = []
    # fetch_federal_register_ivd runs FIRST so that when the same Federal Register
    # document also comes back from the capped agency feed, the url de-dup below
    # keeps the term-feed copy, whose title carries the "Rule:"/"Proposed Rule:"
    # type prefix that the prefer_regulatory_changes pass relies on.
    ordered = (fetch_federal_register_ivd,
               fetch_federal_register, fetch_openfda_510k, fetch_openfda_enforcement,
               fetch_genomeweb, fetch_360dx, fetch_rss,
               fetch_cap, fetch_eu_mdcg, fetch_eu_presscorner)
    for fn in ordered:
        got = [it for it in fn() if _within_window(it)]
        for it in got:
            it.setdefault("region", "US")   # legacy sources are all US
        print(f"  {fn.__name__}: {len(got)} item(s)")
        items.extend(got)

    # De-dupe by url: the capped agency feed and the targeted IVD term feed can
    # return the same Federal Register document. Keep the first occurrence.
    deduped, seen_urls = [], set()
    for it in items:
        u = it.get("url", "")
        if u and u in seen_urls:
            continue
        if u:
            seen_urls.add(u)
        deduped.append(it)
    return deduped


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
               fetch_genomeweb, fetch_360dx, fetch_rss):
        got = [it for it in fn() if _within_window(it)]
        print(f"  {fn.__name__}: {len(got)} item(s)")
        items.extend(got)
    return items
