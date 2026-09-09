"""
V2 tests that run WITHOUT any Anthropic API key: they exercise the deterministic
layers (sanitizer, role validation, tagging, output writer) directly, and feed the
practitioner post-processing a MOCKED model payload so the full read -> output path
is covered end to end without a Claude call.

Run:  python tests/test_v2.py     (from the repo root; no pytest needed)
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
import sanitize
import tagging
import practitioner
import writer

_passed = 0


def check(name, cond):
    global _passed
    if cond:
        _passed += 1
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}")
        raise AssertionError(name)


def test_sanitizer_strips_and_flags():
    text = ("Update the CRF per https://fda.gov/x and 42 CFR 493, doc K260047, "
            "MDCG 2024-13, notice 2026-13534 dated 2026-09-08 on September 8, 2026 "
            "with code 1234567 and a range 5 to 10 pages.")
    clean, flags = sanitize.scrub(text)
    check("url stripped", "http" not in clean and "fda.gov" not in clean)
    check("k-number stripped", "K260047" not in clean)
    check("mdcg id stripped", "2024-13" not in clean)
    check("fr docnum stripped", "2026-13534" not in clean)
    check("cfr cite stripped", "493" not in clean and "CFR" not in clean)
    check("iso date stripped", "2026-09-08" not in clean)
    check("month date stripped", "September 8, 2026" not in clean)
    check("long number stripped", "1234567" not in clean)
    for f in ("url", "doc_id", "cfr_cite", "date", "number"):
        check(f"flag present: {f}", f in flags)


def test_sanitizer_new_citation_forms():
    # Forms flagged as gaps in review: must now be stripped + flagged.
    for src, token in [
        ("update per 42 CFR Part 493 today", "493"),
        ("see 21 C.F.R. § 809.10 for detail", "809"),
        ("the IVDR, Regulation (EU) 2017/746, applies", "2017/746"),
        ("docket FDA-2026-N-1234 is open", "FDA-2026-N-1234"),
        ("effective 09/08/2026 per notice", "09/08/2026"),
        ("published September 2026 as final", "September 2026"),
        ("details at fda.gov/medical-devices online", "fda.gov"),
    ]:
        clean, flags = sanitize.scrub(src)
        check(f"stripped {token!r}", token not in clean and flags)


def test_sanitizer_preserves_legit_numbers_and_ranges():
    for src in [
        "over the 2019-2024 review period",     # year range, not a doc id
        "50000 patients were enrolled",         # legit 5-digit quantity
        "about 123456 samples total",           # legit 6-digit quantity
    ]:
        clean, flags = sanitize.scrub(src)
        check(f"preserved: {src!r}", clean == src and flags == [])


def test_sanitizer_em_dash():
    clean, flags = sanitize.scrub("This is fine — mostly.")
    check("em dash removed", "—" not in clean)
    check("em_dash flagged", "em_dash" in flags)


def test_sanitizer_leaves_clean_text():
    src = "Update the ethnicity field options in the CRF and reuse them in future builds."
    clean, flags = sanitize.scrub(src)
    check("clean text unchanged", clean == src)
    check("no false flags", flags == [])


def test_role_validation_and_caveat():
    raw = [
        {"role": "CDM", "artifact": "ethnicity CRF field",
         "action": "update the option list", "lifecycle": ["planning", "bogus"]},
        {"role": "WIZARD", "artifact": "x", "action": "y", "lifecycle": []},   # invalid
        {"role": "Lab", "artifact": "assay SOP", "action": "revalidate",
         "lifecycle": ["execution"]},
    ]
    reads, flags = practitioner._clean_reads(raw, thin=False)
    roles = [r["role"] for r in reads]
    check("invalid role dropped", "WIZARD" not in roles)
    check("valid roles kept", roles == ["CDM", "Lab"])
    check("bogus lifecycle filtered", reads[0]["lifecycle"] == ["planning"])
    check("caveat appended", config.APPLICABILITY_CAVEAT in reads[0]["action"])
    check("role_label injected", reads[1]["role_label"] == config.ROLES["Lab"]["label"])


def test_thin_source_collapses_reads():
    raw = [{"role": "CDM", "artifact": "a very specific CRF field",
            "action": "definitely change it now", "lifecycle": ["planning"]}]
    reads, _ = practitioner._clean_reads(raw, thin=True)
    check("thin nulls artifact", "not determinable" in reads[0]["artifact"])
    check("thin softens action", "Watch" in reads[0]["action"])
    check("thin clears lifecycle", reads[0]["lifecycle"] == [])
    check("thin keeps caveat", config.APPLICABILITY_CAVEAT in reads[0]["action"])


def test_tagging():
    us = tagging.tag_item({"title": "Medicare coverage determination for a lab test",
                           "summary": "", "source": "Federal Register"})
    check("region default US", us["region"] == "US")
    check("CMS tag applied", "CMS" in us["source_tags"])
    clia = tagging.tag_item({"title": "CLIA proficiency testing update under part 493",
                             "summary": "", "source": "Federal Register"})
    check("CLIA tag applied", "CLIA" in clia["source_tags"])
    eu = tagging.tag_item({"title": "MDCG guidance", "summary": "",
                           "source": "EU MDCG (IVDR guidance)", "region": "EU"})
    check("EU region kept", eu["region"] == "EU")
    check("IVDR family tag", "IVDR" in eu["source_tags"])


def test_practitioner_postprocess_with_mock(monkeypatch_client):
    """Feed a mocked model payload through practitioner_read; assert citations are
    code-injected and never taken from the model, and stubs stay bare."""
    mock_payload = {
        "thin_source": False,
        "what_changed": "The notice updates standard ethnicity options, see https://evil/x on 2026-09-08.",
        "reads": [{"role": "CDM", "artifact": "ethnicity CRF/EDC field",
                   "action": "update the option list and reuse in future builds",
                   "lifecycle": ["planning", "execution"]}],
        "linkedin_seed": "FDA updated the standard ethnicity options (doc K260047).",
    }
    monkeypatch_client(mock_payload)
    item = {"title": "Ethnicity options update", "source": "Federal Register",
            "region": "US", "summary": "text", "url": "https://real-source/x",
            "date": "2026-09-08"}
    out = practitioner.practitioner_read(item)
    check("model url scrubbed from what_changed", "evil" not in out["what_changed"])
    check("model date scrubbed", "2026-09-08" not in out["what_changed"])
    check("sanitizer flagged the attempt", out["sanitize_flags"])
    check("code-injected url intact on item", item["url"] == "https://real-source/x")
    check("seed doc id scrubbed", "K260047" not in out["linkedin_seed"])
    check("stub is bare", "(your angle here)" in out["draft"])
    check("read caveat present",
          config.APPLICABILITY_CAVEAT in out["reads"][0]["action"])


def _make_monkeypatch():
    """Tiny stand-in for pytest's monkeypatch: swaps the Claude call for a stub."""
    import claude_client

    def _patch(payload):
        class _Block:
            type = "text"
            text = json.dumps(payload)

        class _Msg:
            content = [_Block()]

        class _Messages:
            def create(self, *a, **k):
                return _Msg()

        class _Client:
            messages = _Messages()

        # practitioner.py imported _get_client by name; patch that binding.
        practitioner._get_client = lambda: _Client()

    return _patch


def test_writer_v2_output_no_em_dash():
    drafted = [{
        "title": "Ethnicity options update", "source": "Federal Register",
        "region": "US", "source_tags": ["FederalRegister", "CMS"],
        "url": "https://real-source/x", "date": "2026-09-08",
        "why": "relevant", "confidence": "high",
        "what_changed": "The notice updates the standard ethnicity options.",
        "thin_source": False, "thin_source_reason": "",
        "reads": [{"role": "CDM", "role_label": config.ROLES["CDM"]["label"],
                   "artifact": "ethnicity CRF/EDC field",
                   "action": "update the option list. " + config.APPLICABILITY_CAVEAT,
                   "lifecycle": ["planning", "execution"]}],
        "linkedin_seed": "The notice updates standard ethnicity options.",
        "draft": "The notice updates standard ethnicity options.\n\n(your angle here)",
        "sanitize_flags": [],
    }]
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        config.DOCS_DIR = d
        config.ARCHIVE_DIR_V2 = d / "v2"
        config.DRAFTS_JSON_V2 = d / "drafts_v2.json"
        n = writer.write_outputs_v2(drafted)
        check("one record written", n == 1)
        payload = json.loads((d / "drafts_v2.json").read_text())
        rec = payload["drafts"][0]
        check("version v2", payload["version"] == "v2")
        check("region in record", rec["region"] == "US")
        check("roles derived", rec["roles"] == ["CDM"])
        check("lifecycle derived", rec["lifecycle"] == ["execution", "planning"])
        check("url is code-injected source url", rec["url"] == "https://real-source/x")
        check("stub bare in record", "(your angle here)" in rec["linkedin_stub"])
        md = (d / "v2" / next(p.name for p in (d / "v2").iterdir())).read_text()
        check("no em dash in json", "—" not in json.dumps(payload))
        check("no em dash in markdown", "—" not in md)


def test_fedreg_ivd_fetcher_dedup_and_resilience():
    """fetch_federal_register_ivd: cross-term dedup by document_number, html_url
    fallback, keep-when-no-id, and one failing term does not abort the others."""
    import sources
    calls = {"n": 0}

    class _Resp:
        def __init__(self, payload): self._p = payload
        def raise_for_status(self): pass
        def json(self): return self._p

    def fake_get(url, params=None, timeout=None):
        calls["n"] += 1
        term = params.get("conditions[term]")
        if term == "in vitro diagnostic":
            return _Resp({"results": [
                {"document_number": "D1", "type": "Rule", "title": "IVD rule",
                 "abstract": "a", "html_url": "https://fr/d1", "publication_date": "2026-09-01"},
                {"document_number": "D2", "type": "Notice", "title": "IVD notice",
                 "abstract": "b", "html_url": "https://fr/d2", "publication_date": "2026-09-02"},
            ]})
        if term == "companion diagnostic":
            # D1 again (dup by doc number) + one with no document_number
            return _Resp({"results": [
                {"document_number": "D1", "type": "Rule", "title": "IVD rule dup",
                 "abstract": "a", "html_url": "https://fr/d1", "publication_date": "2026-09-01"},
                {"type": "Notice", "title": "no id", "abstract": "c",
                 "html_url": "https://fr/x", "publication_date": "2026-09-03"},
            ]})
        raise RuntimeError("simulated term failure")   # remaining terms fail

    orig_get, orig_cfg = sources.requests.get, config.SOURCES.get("federal_register_ivd")
    try:
        sources.requests.get = fake_get
        config.SOURCES["federal_register_ivd"] = {
            "enabled": True, "base_url": "https://fr/api",
            "terms": ["in vitro diagnostic", "companion diagnostic", "boom"],
            "per_page": 10, "region": "US"}
        items = sources.fetch_federal_register_ivd()
    finally:
        sources.requests.get = orig_get
        config.SOURCES["federal_register_ivd"] = orig_cfg

    urls = [it["url"] for it in items]
    check("dedup by document_number (D1 once)", urls.count("https://fr/d1") == 1)
    check("kept D2", "https://fr/d2" in urls)
    check("kept item with no document_number", "https://fr/x" in urls)
    check("failing term did not abort others", len(items) == 3)
    check("type prefix on title", any(it["title"].startswith("Rule:") for it in items))
    check("not prequalified", all(not it.get("prequalified") for it in items))


def test_fetch_all_v2_url_dedup(monkeypatch_fetchers):
    import sources
    monkeypatch_fetchers({
        "fetch_federal_register_ivd": [{"title": "Rule: X", "url": "https://fr/1", "source": "Federal Register"}],
        "fetch_federal_register": [{"title": "X", "url": "https://fr/1", "source": "Federal Register"}],  # dup url
        "fetch_openfda_510k": [{"title": "clr", "url": "https://fda/k1", "source": "openFDA 510(k)"}],
        "fetch_cap": [{"title": "no url a", "url": "", "source": "CAP"},
                      {"title": "no url b", "url": "", "source": "CAP"}],  # url-less all kept
    })
    items = sources.fetch_all_v2()
    urls = [it["url"] for it in items if it["url"]]
    check("dup url collapsed to one", urls.count("https://fr/1") == 1)
    check("type-prefixed copy won the dedup",
          next(it for it in items if it["url"] == "https://fr/1")["title"].startswith("Rule:"))
    check("all url-less items retained", sum(1 for it in items if not it["url"]) == 2)
    check("region defaulted to US", all(it["region"] == "US" for it in items))


def test_score_and_select_prompt_flag(monkeypatch_capture_prompt):
    import claude_client
    items = [{"title": "t", "summary": "s", "source": "Federal Register"}]
    get_prompt = monkeypatch_capture_prompt()
    claude_client.score_and_select(items, prefer_regulatory_changes=False)
    base = get_prompt()
    claude_client.score_and_select(items, prefer_regulatory_changes=True)
    pref = get_prompt()
    import re
    check("default prompt has no preference line", "PREFER substantive" not in base)
    check("flagged prompt adds preference once", pref.count("PREFER substantive") == 1)
    stripped = re.sub(r"\n\nWhen choosing, PREFER substantive.*?present\.", "", pref, flags=re.S)
    check("preference is the only delta (rest byte-identical)", stripped == base)


def test_self_contained_review_escapes_script(tmp_docs):
    import writer
    payload = {"generated": "2026-09-09", "count": 1, "version": "v2", "drafts": [
        {"title": "evil </script><img src=x>", "region": "US", "source_tags": [],
         "url": "https://real/x", "source_date": "", "why": "", "confidence": "high",
         "what_changed": "", "thin_source": False, "thin_source_reason": "",
         "roles": [], "lifecycle": [], "reads": [], "linkedin_stub": "s", "sanitize_flags": []}]}
    out = writer.write_self_contained_review(payload)
    html = out.read_text()
    check("inline hook present", "window.__V2_DATA__ = " in html)
    check("payload '<' escaped to \\u003c", "</script><img" not in html)
    check("literal breakout neutralized", html.count("</script>") == html.count("<script>"))
    check("render guards still in template", "function esc(" in html and "function safeUrl(" in html)


# --- lightweight monkeypatch helpers (no pytest) ---
def _make_monkeypatch_fetchers():
    import sources
    def _patch(mapping):
        for name in ("fetch_federal_register", "fetch_openfda_510k",
                     "fetch_openfda_enforcement", "fetch_genomeweb", "fetch_360dx",
                     "fetch_rss", "fetch_federal_register_ivd", "fetch_cap",
                     "fetch_eu_mdcg", "fetch_eu_presscorner"):
            setattr(sources, name, (lambda items=mapping.get(name, []): list(items)))
    return _patch


def _make_capture_prompt():
    import claude_client
    box = {}
    class _Blk:
        type = "text"; text = "[]"
    class _Msg:
        content = [_Blk()]
    class _Messages:
        def create(self, *a, **k):
            box["prompt"] = k["messages"][0]["content"]
            return _Msg()
    class _Client:
        messages = _Messages()
    claude_client._get_client = lambda: _Client()
    return lambda: box.get("prompt", "")


def _make_tmp_docs():
    import tempfile
    d = pathlib.Path(tempfile.mkdtemp())
    # minimal template carrying the markers the packager and page rely on
    (d / "index_v2.html").write_text(
        "<style></style>\n"
        "<script>\nfunction esc(s){return s}\nfunction safeUrl(u){return u}\n"
        "async function load(){if(window.__V2_DATA__){}else{fetch('./drafts_v2.json')}}\n"
        "load();\n</script>\n")
    config.DOCS_DIR = d
    return d


import pathlib  # noqa: E402 (used by _make_tmp_docs)


if __name__ == "__main__":
    print("V2 tests (no API key required):")
    test_sanitizer_strips_and_flags()
    test_sanitizer_new_citation_forms()
    test_sanitizer_preserves_legit_numbers_and_ranges()
    test_sanitizer_em_dash()
    test_sanitizer_leaves_clean_text()
    test_role_validation_and_caveat()
    test_thin_source_collapses_reads()
    test_tagging()
    test_practitioner_postprocess_with_mock(_make_monkeypatch())
    test_writer_v2_output_no_em_dash()
    test_fedreg_ivd_fetcher_dedup_and_resilience()
    test_fetch_all_v2_url_dedup(_make_monkeypatch_fetchers())
    test_score_and_select_prompt_flag(_make_capture_prompt)
    test_self_contained_review_escapes_script(_make_tmp_docs())
    print(f"\nAll good: {_passed} checks passed.")
