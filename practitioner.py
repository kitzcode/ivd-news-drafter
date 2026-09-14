"""
PART 2: the concrete practitioner read (net-new in V2).

For each selected change, per affected CONFIGURED role, the model names:
  (a) the specific artifact affected (a CRF field, an EDC edit check, an SOP, a
      submission dataset, ...),
  (b) the specific action (update, revalidate, remap, add to template, ...),
  (c) where in the lifecycle it lands (planning | execution | submission).

ANTI-HALLUCINATION (tightened):
  - The model only PHRASES implications. It must not assert that a specific change
    happened, or invent a clause / date / document id / requirement. Every citation
    is code-injected from the source record; sanitize.scrub() strips any the model
    emits and flags it.
  - If the source text is too thin to name what concretely changes, the model sets
    thin_source and code collapses the read to a "watch, do not act yet" note. A
    confident wrong "update your CRF" is worse than "check applicability".
  - The model may only pick from config.ROLES; invented role ids are dropped. It
    must never say a change applies to a specific product or study.
  - CRA/monitor framing is locked (see config.CRA_CONSTRAINT).

No Claude key is required to import this module; the call happens in practitioner_read().
"""

import json

import anthropic

import config
import sanitize
from claude_client import _get_client, _extract_text, _parse_json


def _role_catalog_text():
    lines = []
    for rid, meta in config.ROLES.items():
        lines.append(f'  - id "{rid}" ({meta["label"]}): {meta["scope"]}')
    return "\n".join(lines)


def _system_prompt():
    return (
        "You help an IVD / diagnostics + clinical-data practitioner turn a regulatory "
        "or standards change into a concrete, per-role read. Practitioner voice, not "
        "teaching voice: plain, direct, the way you would flag something to a colleague. "
        "No em dashes anywhere.\n\n"
        "HARD ANTI-HALLUCINATION RULES:\n"
        "1. Use ONLY facts present in the source text provided. Invent nothing.\n"
        "2. Never output a URL, date, document number, CFR clause, or citation. Those "
        "are added by code. If you feel the urge to cite one, leave it out.\n"
        "3. Do not assert that a specific change definitely happened. Phrase implications "
        "as 'this likely means ...', a suggestion to check, never a directive or a "
        "compliance instruction. You propose, the owner decides.\n"
        "4. Never say a change applies to a specific product or study. Applicability is "
        "always the owner's call.\n"
        "5. If the source text is too thin to name what concretely changes, set "
        "\"thin_source\": true and do NOT invent a specific artifact.\n"
        f"6. {config.CRA_CONSTRAINT}\n\n"
        "ROLES you may pick from (use the id exactly; pick only roles genuinely "
        "affected, you may pick none):\n" + _role_catalog_text() + "\n\n"
        "For each affected role name the SPECIFIC artifact (e.g. an ethnicity CRF/EDC "
        "field, an EDC edit check, the data management plan, a method-validation doc, an "
        "SOP, a coding/mapping spec, an analysis dataset), the SPECIFIC suggested action "
        "(update, revalidate, remap, add to a future-build template, ...), and the "
        "lifecycle phase(s) it lands in from exactly: planning, execution, submission."
    )


def _user_prompt(item):
    return (
        "SOURCE ITEM (use only what is here):\n"
        f"TITLE: {item.get('title','')}\n"
        f"SOURCE: {item.get('source','')}\n"
        f"REGION: {item.get('region','US')}\n"
        f"TEXT: {item.get('summary','')}\n\n"
        "Return ONLY JSON, no prose:\n"
        "{\n"
        '  "thin_source": <true|false>,\n'
        '  "what_changed": "<one plain sentence of what the source says, grounded only '
        'in the text above; if too thin to tell, say that>",\n'
        '  "reads": [\n'
        '    {"role": "<role id>", "artifact": "<specific artifact>", '
        '"action": "<specific suggested action, phrased as likely + check>", '
        '"lifecycle": ["planning"|"execution"|"submission", ...]}\n'
        "  ],\n"
        '  "linkedin_seed": "<one bare factual sentence, no opinion, no citation>"\n'
        "}"
    )


def _clean_reads(raw_reads, thin):
    """Validate roles/lifecycle, scrub text, collapse when thin. Returns (reads, flags)."""
    reads, flags = [], set()
    if not isinstance(raw_reads, list):
        return reads, sorted(flags)

    for r in raw_reads:
        if not isinstance(r, dict):
            continue
        role = r.get("role")
        if role not in config.ROLES:            # model cannot invent a role
            if role is not None:
                print(f"  [warn] dropped read with unknown role {role!r}")
            continue

        artifact, af = sanitize.scrub(str(r.get("artifact", "")))
        action, cf = sanitize.scrub(str(r.get("action", "")))
        flags.update(af)
        flags.update(cf)

        lifecycle = [p for p in (r.get("lifecycle") or [])
                     if p in config.LIFECYCLE_PHASES]

        if thin:
            # Too thin to name a concrete artifact: do not let a confident wrong
            # instruction through. Collapse to a watch note.
            artifact = "not determinable from the source yet (thin source)"
            action = "Watch for the detail before changing anything."
            lifecycle = []

        # Code-injected applicability caveat, always present.
        if config.APPLICABILITY_CAVEAT.lower() not in action.lower():
            action = (action + " " + config.APPLICABILITY_CAVEAT).strip()

        reads.append({
            "role": role,
            "role_label": config.ROLES[role]["label"],
            "artifact": artifact,
            "action": action,
            "lifecycle": lifecycle,
        })
    return reads, sorted(flags)


def practitioner_read(item):
    """
    One Claude call. Adds to item:
      what_changed, thin_source, reads[], linkedin_seed, draft, sanitize_flags[].
    Every model-emitted string is scrubbed; citations stay code-injected.
    """
    forced_thin = bool(item.get("force_thin"))
    try:
        msg = _get_client().messages.create(
            model=config.MODEL_DRAFT,
            max_tokens=1100,
            system=_system_prompt(),
            messages=[{"role": "user", "content": _user_prompt(item)}],
        )
        out = _parse_json(_extract_text(msg))
    except Exception as e:
        print(f"  [warn] practitioner read failed for '{item.get('title','')[:50]}': {e}")
        out = {}

    model_thin = bool(out.get("thin_source"))
    thin = model_thin or forced_thin

    what_changed, wc_flags = sanitize.scrub(str(out.get("what_changed", "")))
    reads, read_flags = _clean_reads(out.get("reads"), thin)
    seed, seed_flags = sanitize.scrub(str(out.get("linkedin_seed", "")))

    flags = sorted(set(wc_flags) | set(read_flags) | set(seed_flags))

    # Bare LinkedIn stub by design: a factual seed + a marker for her own angle.
    # A polished draft invites posting unread; the voice is hers.
    if seed:
        draft = seed + "\n\n(your angle here)"
    else:
        draft = "(source facts only; add your angle)"

    item["what_changed"] = what_changed
    item["thin_source"] = thin
    item["thin_source_reason"] = ("source is announcement-level only"
                                  if forced_thin and not model_thin
                                  else ("model judged the source too thin" if thin else ""))
    item["reads"] = reads
    item["linkedin_seed"] = seed
    item["draft"] = draft
    item["sanitize_flags"] = flags
    return item
