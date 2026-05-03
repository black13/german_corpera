"""WSGI entrypoint for Render's existing `gunicorn app:app` service command."""

import os
import random
from html import escape
from urllib.parse import parse_qs

import runner


_loaded = False
_DEFAULT_LAST_DAYS = int(os.environ.get("RENDER_DEFAULT_DAYS", "1"))
_WORD_KB_INDEX = None


def _ensure_loaded():
    global _loaded
    if not _loaded:
        runner.load_existing_outputs()
        _loaded = True


def _response(start_response, status, body, content_type="text/plain; charset=utf-8", headers=None):
    payload = body.encode("utf-8")
    response_headers = [
        ("Content-Type", content_type),
        ("Content-Length", str(len(payload))),
    ]
    if headers:
        response_headers.extend(headers)
    start_response(status, response_headers)
    return [payload]


def _is_truthy(value):
    return str(value).lower() in {"1", "true", "yes", "all"}


def _one_day(query):
    target = (query.get("day") or query.get("kann") or [""])[0].strip()
    if not target:
        return None
    try:
        day_num, _ = runner.resolve_run_target(target)
    except ValueError:
        return None
    return [day for day in runner.live["days"] if int(day.get("day", 0)) == day_num]


def _latest_days(query):
    requested = (query.get("last") or [""])[0].strip()
    try:
        count = int(requested) if requested else _DEFAULT_LAST_DAYS
    except ValueError:
        count = _DEFAULT_LAST_DAYS
    count = max(1, min(count, len(runner.live["days"])))
    return runner.live["days"][-count:]


def _selected_days(query):
    if _is_truthy((query.get("all") or [""])[0]):
        return runner.live["days"]
    one_day = _one_day(query)
    if one_day is not None:
        return one_day
    if "last" in query:
        return _latest_days(query)
    return runner.live["days"][-_DEFAULT_LAST_DAYS:]


def _index_html(all_days, selected_days):
    selected = {int(day.get("day", 0)) for day in selected_days}
    links = []
    for day in all_days:
        day_num = int(day.get("day", 0))
        kann_id = day.get("kann_id", "")
        kann_text = day.get("kann_text", "")
        active = day_num in selected
        style = (
            "display:block;padding:3px 4px;border-radius:4px;"
            f"background:{'#e6f4f1' if active else 'transparent'};"
            f"font-weight:{'700' if active else '400'};"
            "color:#123;text-decoration:none;line-height:1.35;"
        )
        label = f"{day_num}. {kann_id}: {kann_text}"
        links.append(f'<a href="/?day={day_num}" style="{style}">{escape(label)}</a>')
    return (
        '<div class="sidebar-section">'
        '<div class="sidebar-title">Kann Index</div>'
        '<div class="status-text">Showing one conversation at a time. '
        'Use this list to open any saved KB.</div>'
        '<div style="max-height:320px;overflow:auto;margin-top:8px;font-size:.76em">'
        + "".join(links) +
        '</div></div>'
    )


def _render_windowed_html(query_string):
    query = parse_qs(query_string or "")
    all_days = runner.live["days"]
    selected_days = _selected_days(query)
    original_days = runner.live["days"]
    original_status = runner.live["status"]
    original_current = {
        key: runner.live.get(key)
        for key in (
            "current_day",
            "current_kann",
            "current_kann_text",
            "current_kann_focus",
        )
    }
    runner.live["days"] = selected_days
    if selected_days:
        selected = selected_days[-1]
        runner.live["current_day"] = selected.get("day", 0)
        runner.live["current_kann"] = selected.get("kann_id", "")
        runner.live["current_kann_text"] = selected.get("kann_text", "")
        runner.live["current_kann_focus"] = selected.get("kann_focus", {})
    runner.live["status"] = (
        f"{original_status} Showing {len(selected_days)} of {len(all_days)} saved days. "
        "Use the Kann Index or query ?day=175 / ?day=K176."
    )
    try:
        html = runner.render_html()
        return html.replace(
            '<div class="sidebar" id="sidebar">',
            '<div class="sidebar" id="sidebar">' + _index_html(all_days, selected_days),
            1,
        )
    finally:
        runner.live["days"] = original_days
        runner.live["status"] = original_status
        for key, value in original_current.items():
            runner.live[key] = value


# ---------------------------------------------------------------------------
# Word -> KB lookup index (lazy)
# ---------------------------------------------------------------------------
def _build_word_kb_index():
    global _WORD_KB_INDEX
    if _WORD_KB_INDEX is not None:
        return _WORD_KB_INDEX
    idx = {}
    for kann in runner.all_kanns:
        kid = kann["id"]
        focus = runner.derive_kann_focus(kann)
        guide = focus.get("quick_guide", {})
        reduction = focus.get("reduction", {})
        terms = set()
        for t in kann.get("kann", "").lower().split():
            t = t.strip(".,;:!?()\"'")
            if len(t) >= 2: terms.add(t)
        for t in focus.get("speech_acts", []):
            for w in t.lower().split():
                w = w.strip(".,;:!?()\"'/")
                if len(w) >= 2: terms.add(w)
        for t in focus.get("grammar_targets", []):
            for w in t.lower().split():
                w = w.strip(".,;:!?()\"'/")
                if len(w) >= 2: terms.add(w)
        for t in focus.get("wortfeld_targets", []):
            terms.add(t.lower())
        for ex in focus.get("example_bank", []):
            txt = ex.get("text", "") if isinstance(ex, dict) else str(ex)
            for w in txt.lower().split():
                w = w.strip(".,;:!?()\"'")
                if len(w) >= 2: terms.add(w)
        for w in (guide.get("word_bank", []) + guide.get("core_phrases", []) + guide.get("grammar_tools", [])):
            for part in w.lower().split():
                part = part.strip(".,;:!?()\"'/")
                if len(part) >= 2: terms.add(part)
        for key2 in ("identifier", "carrier", "channel", "operation", "output", "persistence", "rips", "memory"):
            val = reduction.get(key2, "")
            if val:
                for w in val.lower().replace("-", " ").replace("/", " ").split():
                    w = w.strip(".,;:")
                    if len(w) >= 2: terms.add(w)
        for t in terms:
            idx.setdefault(t, set()).add(kid)
    for field, words in runner.wortfelder.items():
        for w in words:
            w = w.lower().strip(".,;:!?()\"'")
            if len(w) >= 2:
                idx.setdefault(w, set()).add(f"wortfeld:{field}")
    _WORD_KB_INDEX = idx
    return idx


# ---------------------------------------------------------------------------
# Short memorable rubric for a KB
# ---------------------------------------------------------------------------
def _rubric_for(kann):
    cat = kann.get("category", "")
    text = kann.get("kann", "")
    kid = kann["id"]
    overrides = runner.kann_reductions_cfg.get("manual_overrides", {})
    defaults = runner.kann_reductions_cfg.get("category_defaults", {})
    ov = overrides.get(kid, {})
    cat_def = defaults.get(cat, {})

    cat_rubrics = {
        "Interaktion muendlich": "↔ sprechen",
        "Interaktion schriftlich": "↔ schreiben",
        "Rezeption muendlich": "👂 hören",
        "Rezeption schriftlich": "👁 lesen",
        "Produktion muendlich": "🗣 sagen",
        "Produktion schriftlich": "✎ schreiben",
        "Sprachmittlung muendlich": "🔀 weitergeben",
    }
    base = cat_rubrics.get(cat, "")

    identifier = ov.get("identifier", "")
    if identifier:
        base += " · " + identifier[:25]
    elif kid <= "K009":
        if "langsam" in text and "klar" in text: base += " · Partner hilft"
        elif "auswendig" in text: base += " · auswendig gelernt"
        elif "Fragen" in text and "reagieren" in text: base += " · Fragen + Antworten"
        elif "Fragen" in text and "stellen" in text: base += " · Fragen stellen"
        elif "aussprechen" in text: base += " · Aussprache"
        elif "Pausen" in text: base += " · kurze Sätze"
        elif "Intonation" in text and "interpretieren" in text: base += " · Tonfall hören"
        elif "Intonation" in text and "einsetzen" in text: base += " · Tonfall zeigen"
        elif "buchstabiert" in text: base += " · buchstabieren"
        elif "Kontakte" in text: base += " · Grüße + Danke"

    op = ov.get("operation") or cat_def.get("operation", "")
    if op and op not in base:
        base += " → " + op
    return base


# ---------------------------------------------------------------------------
# /word — lookup KBs by a German word
# ---------------------------------------------------------------------------
def _word_form():
    parts = [
        '<!DOCTYPE html><html><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>Word → KB</title>',
        '<style>',
        '*{box-sizing:border-box} body{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f4f6f7;color:#1a2227}',
        '.center{max-width:500px;margin:60px auto;text-align:center}',
        '.center h1{font-size:22px;color:#0b5e55}.center p{color:#5c6b74;font-size:14px}',
        '.center input{width:100%;padding:10px 14px;border:1px solid #c8d6db;border-radius:6px;font:inherit;font-size:16px;margin-top:12px}',
        '.center button{padding:10px 20px;border:1px solid #0b5e55;background:#0b5e55;color:#fff;border-radius:6px;font:inherit;font-size:15px;cursor:pointer;margin-top:10px}',
        '.examples{margin-top:20px;font-size:13px;color:#7b8a94}',
        '.examples a{color:#0b5e55;text-decoration:none;margin:0 6px}',
        '.nav-bar{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:30px;justify-content:center}',
        '.nv{color:#0b5e55;text-decoration:none;font-size:13px;padding:3px 8px;border-radius:4px;border:1px solid #c8d6db}',
        '.nv.active,.nv:hover{background:#0b5e55;color:#fff;border-color:#0b5e55}',
        '</style></head><body><div class="center">',
        '<div class="nav-bar">',
        '<a href="/" class="nv">Classroom</a>',
        '<a href="/graph" class="nv">Graph</a>',
        '<a href="/guides" class="nv">Guides</a>',
        '<a href="/quiz" class="nv">Quiz</a>',
        '<a href="/word" class="nv active">Word→KB</a>',
        '</div>',
        '<h1>Word → Kannbeschreibung</h1>',
        '<p>Type a German word to find which A1 KBs connect to it.</p>',
        '<form action="/word" method="get"><input name="w" placeholder="gestern, Aufschrift, Fahrplan..." autofocus><button type="submit">Find KB</button></form>',
        '<div class="examples">Try: <a href="?w=gestern">gestern</a> <a href="?w=Aufschrift">Aufschrift</a> <a href="?w=Preis">Preis</a> <a href="?w=verstehen">verstehen</a> <a href="?w=Fahrplan">Fahrplan</a></div>',
        '</div></body></html>',
    ]
    return "".join(parts)


def _word_html(query_string):
    query = parse_qs(query_string or "")
    word = (query.get("w") or [""])[0].strip().lower()
    if not word:
        return _word_form()

    idx = _build_word_kb_index()
    matches = idx.get(word, set())
    if not matches:
        for k, v in idx.items():
            if word in k or k in word:
                matches.update(v)
    if not matches:
        for prefix in ("ge", "ver", "be", "er", "ent", "emp", "zer"):
            if word.startswith(prefix) and len(word) > len(prefix) + 2:
                stem = word[len(prefix):]
                if stem in idx:
                    matches.update(idx[stem])

    kb_matches = []
    text_matches = []
    all_kb_ids = {k["id"] for k in runner.all_kanns}
    for m in sorted(matches):
        if m in all_kb_ids:
            kb_matches.append(m)
        else:
            text_matches.append(m)

    if not kb_matches:
        field_targets = set()
        for m in text_matches:
            if m.startswith("wortfeld:"):
                field_targets.add(m.replace("wortfeld:", ""))
        if field_targets:
            kbs_dict_local = {k["id"]: k for k in runner.all_kanns}
            for kid in all_kb_ids:
                focus = runner.derive_kann_focus(kbs_dict_local[kid])
                if field_targets & set(t.lower() for t in focus.get("wortfeld_targets", [])):
                    kb_matches.append(kid)

    kb_matches = list(dict.fromkeys(kb_matches))[:20]
    kb_data = []
    kbs_dict = {k["id"]: k for k in runner.all_kanns}
    for kid in kb_matches:
        kann = kbs_dict[kid]
        focus = runner.derive_kann_focus(kann)
        guide = focus.get("quick_guide", {})
        reduction = focus.get("reduction", {})
        kb_data.append((kann, focus, guide, reduction))

    nav = [
        '<a href="/" class="nv">Classroom</a>',
        '<a href="/graph" class="nv">Graph</a>',
        '<a href="/guides" class="nv">Guides</a>',
        '<a href="/quiz" class="nv">Quiz</a>',
        '<a href="/word" class="nv active">Word→KB</a>',
    ]
    parts = [
        '<!DOCTYPE html><html><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f'<title>Word → KB: {escape(word)}</title>',
        '<style>',
        """
        *{box-sizing:border-box} body{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f4f6f7;color:#1a2227}
        .top{position:sticky;top:0;z-index:10;background:#fff;border-bottom:1px solid #d9e0e3;padding:12px 18px}
        .top h1{margin:0;font-size:18px;color:#0b5e55}.top p{margin:4px 0 0;color:#5c6b74;font-size:13px}
        .nav-bar{display:flex;gap:10px;flex-wrap:wrap;margin-top:8px}
        .nv{color:#0b5e55;text-decoration:none;font-size:13px;padding:3px 8px;border-radius:4px;border:1px solid #c8d6db}
        .nv.active,.nv:hover{background:#0b5e55;color:#fff;border-color:#0b5e55}
        .page{padding:14px 18px;max-width:900px}
        .search-box{margin-bottom:18px}
        .search-box input{width:300px;padding:8px 12px;border:1px solid #c8d6db;border-radius:6px;font:inherit;font-size:15px}
        .search-box button{padding:8px 14px;border:1px solid #0b5e55;background:#0b5e55;color:#fff;border-radius:6px;font:inherit;font-size:14px;cursor:pointer}
        .result-card{border:1px solid #dde4e8;border-radius:8px;background:#fff;padding:14px;margin-bottom:10px}
        .kid{font-weight:800;font-size:14px;color:#0b5e55}
        .lvl{font-size:10px;padding:2px 6px;border-radius:10px;margin-left:6px}
        .lvl.global{background:#dbeafe;color:#1e4a8a}.lvl.detailed{background:#fdeeca;color:#6b4d00}.lvl.example{background:#e8e0f0;color:#4a2870}
        .cat{font-size:12px;color:#6b7c85;margin-left:4px}
        .simple-de{font-size:15px;margin:6px 0;padding:8px 10px;background:#eaf4ea;color:#1a3a1a;border-radius:5px}
        .simple-en{font-size:14px;margin:4px 0 8px;padding:6px 10px;background:#f4f2e8;color:#3a3420;border-radius:5px}
        .rips{display:flex;flex-wrap:wrap;gap:4px;margin:6px 0}
        .rip{font-size:10px;padding:2px 6px;background:#eef4f5;border-radius:4px;color:#4a606c}
        .rip strong{color:#1a2a33}
        .section{margin-top:8px}
        .section h3{margin:0 0 3px;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:#7b8a94}
        .vals{font-size:12px;color:#3a4a53;line-height:1.5}
        .orig-toggle{font-size:11px;color:#0b5e55;cursor:pointer;border:none;background:none;padding:3px 0;margin-top:4px}
        .orig-text{font-size:11px;line-height:1.4;color:#5a6670;margin-top:3px;padding:4px 8px;background:#f8f9fa;border-radius:4px;display:none}
        .orig-text.vis{display:block}
        .no-match{margin-top:18px;padding:12px 16px;background:#fef9e7;border:1px solid #e6d88a;border-radius:8px;color:#6b5a00;font-size:14px}
        """,
        '</style></head><body>',
        f'<div class="top"><h1>Word → Kannbeschreibung</h1>',
        f'<p>Type a German word. Find which A1 KBs it connects to — and how to teach it.</p>',
        '<div class="nav-bar">' + "".join(nav) + '</div>',
        '<div class="search-box">',
        f'<form action="/word" method="get"><input name="w" value="{escape(word)}" placeholder="gestern, Aufschrift, verstehen, Fahrplan..." autofocus><button type="submit">Find KB</button></form>',
        '</div></div>',
        '<div class="page">',
    ]

    if not kb_data:
        parts.append(f'<div class="no-match">No KB match for <b>{escape(word)}</b>. ')
        if text_matches:
            parts.append(f'Found in: {escape(", ".join(text_matches[:10]))}. ')
        parts.append('Try a different word.</div>')
    else:
        parts.append(f'<p style="color:#6b7c85">{len(kb_data)} KB(s) match <b>{escape(word)}</b></p>')
        for kann, focus, guide, reduction in kb_data:
            level = kann.get("level", "")
            cat = kann.get("category", "")
            parts.append('<div class="result-card">')
            parts.append(f'<div><span class="kid">{escape(kann["id"])}</span>')
            if level: parts.append(f'<span class="lvl {escape(level)}">{escape(level)}</span>')
            if cat: parts.append(f'<span class="cat">{escape(cat)}</span>')
            parts.append('</div>')
            rips_parts = []
            for label, key in (("RIPS", "rips"), ("Carrier", "carrier"), ("Channel", "channel"), ("Persistence", "persistence"), ("Operation", "operation"), ("Output", "output")):
                val = reduction.get(key, "")
                if val: rips_parts.append(f'<span class="rip"><strong>{escape(label)}</strong> {escape(val)}</span>')
            if rips_parts: parts.append('<div class="rips">' + "".join(rips_parts) + '</div>')
            de_simple = guide.get("kb_de_simple", "")
            en_simple = guide.get("kb_en_simple", "")
            if de_simple: parts.append(f'<div class="simple-de">{escape(de_simple)}</div>')
            if en_simple: parts.append(f'<div class="simple-en">{escape(en_simple)}</div>')
            scene = guide.get("scene", "")
            roles = guide.get("roles", [])
            if scene:
                parts.append(f'<div class="section"><h3>Scene</h3><div class="vals">{escape(scene)}')
                if roles: parts.append(f' · {escape(", ".join(roles))}')
                parts.append('</div></div>')
            phrases = guide.get("core_phrases", [])
            if phrases: parts.append(f'<div class="section"><h3>Core Phrases</h3><div class="vals">{escape(" · ".join(phrases[:6]))}</div></div>')
            words_list = guide.get("word_bank", [])
            if words_list: parts.append(f'<div class="section"><h3>Word Bank</h3><div class="vals">{escape(", ".join(words_list[:12]))}</div></div>')
            orig_id = f"origword-{kann['id']}"
            parts.append(f'<button class="orig-toggle" onclick="document.getElementById(\'{orig_id}\').classList.toggle(\'vis\')">▶ Original</button>')
            parts.append(f'<div class="orig-text" id="{orig_id}">{escape(kann["kann"])}</div>')
            parts.append('</div>')

    if text_matches and kb_data:
        parts.append(f'<p style="margin-top:16px;font-size:12px;color:#6b7c85">{len(text_matches)} other references: {escape(", ".join(text_matches[:20]))}</p>')
    parts.append('</div></body></html>')
    return "".join(parts)


# ---------------------------------------------------------------------------
# /guides — quick-guide browser for all 176 KBs
# ---------------------------------------------------------------------------
def _guides_html(query_string):
    query = parse_qs(query_string or "")
    search = (query.get("q") or [""])[0].strip().lower()
    cat_filter = (query.get("cat") or [""])[0].strip()
    hand_only = (query.get("hand") or [""])[0] == "1"
    missing_only = (query.get("missing") or [""])[0] == "1"
    bare = (query.get("view") or [""])[0] == "bare"

    hand_guides = runner.kann_quick_guides_cfg.get("guides", {})
    categories = {}
    for kann in runner.all_kanns:
        cat = kann.get("category", "Unsorted")
        categories.setdefault(cat, []).append(kann)
    for items in categories.values():
        items.sort(key=lambda k: k["id"])

    nav = [
        '<a href="/" class="nv">Classroom</a>',
        '<a href="/graph" class="nv">Graph</a>',
        '<a href="/guides" class="nv active">Guides</a>',
        '<a href="/quiz" class="nv">Quiz</a>',
        '<a href="/word" class="nv">Word→KB</a>',
    ]

    parts = [
        '<!DOCTYPE html><html><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>KB Quick Guides</title>',
        '<style>',
        """
        *{box-sizing:border-box} body{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f4f6f7;color:#1a2227}
        .top{position:sticky;top:0;z-index:10;background:#fff;border-bottom:1px solid #d9e0e3;padding:12px 18px}
        .top h1{margin:0;font-size:18px;color:#0b5e55}.top p{margin:4px 0 0;color:#5c6b74;font-size:13px}
        .nav-bar{display:flex;gap:10px;flex-wrap:wrap;margin-top:8px}
        .nv{color:#0b5e55;text-decoration:none;font-size:13px;padding:3px 8px;border-radius:4px;border:1px solid #c8d6db}
        .nv.active,.nv:hover{background:#0b5e55;color:#fff;border-color:#0b5e55}
        .filters{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;align-items:center}
        .filters input,.filters select{padding:5px 8px;border:1px solid #c8d6db;border-radius:4px;font:inherit;font-size:12px}
        .filters input{width:200px}
        .filters a{padding:4px 10px;border:1px solid #c8d6db;border-radius:4px;font-size:12px;text-decoration:none;color:#3a4a53}
        .filters a.on{background:#fdeeca;border-color:#e6c33a;color:#5c4200}
        .stats{margin-top:6px;font-size:12px;color:#6b7c85}
        .page{padding:14px 18px;max-width:1400px}
        .cat-tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:14px}
        .cat-tab{font-size:12px;padding:5px 12px;border:1px solid #c8d6db;border-radius:16px;cursor:pointer;background:#fff;color:#3a4a53;text-decoration:none}
        .cat-tab:hover,.cat-tab.sel{border-color:#0b5e55;background:#e6f4f0;color:#0b5e55}
        .card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:10px}
        .card{border:1px solid #dde4e8;border-radius:8px;background:#fff;padding:12px;position:relative}
        .card.hand{border-left:3px solid #2e8b57}
        .card.fallback{border-left:3px solid #bcc7ce}
        .card-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px}
        .kid{font-weight:800;font-size:13px;color:#0b5e55}.lvl{font-size:10px;padding:1px 6px;border-radius:10px;text-transform:uppercase;letter-spacing:.03em}
        .lvl.global{background:#dbeafe;color:#1e4a8a}.lvl.detailed{background:#fdeeca;color:#6b4d00}.lvl.example{background:#e8e0f0;color:#4a2870}
        .badge{font-size:9px;padding:2px 6px;border-radius:8px;margin-left:4px;font-weight:600}
        .badge.hw{background:#2e8b57;color:#fff}.badge.fb{background:#bcc7ce;color:#4a5568}
        .simple-de,.simple-en{font-size:14px;margin:4px 0;padding:6px 10px;border-radius:5px;line-height:1.4}
        .simple-de{background:#eaf4ea;color:#1a3a1a}.simple-en{background:#f4f2e8;color:#3a3420}
        .orig-toggle{font-size:12px;color:#0b5e55;cursor:pointer;border:none;background:none;padding:4px 0;margin-top:6px;display:inline-flex;align-items:center;gap:4px}
        .orig-toggle:hover{color:#073d35}
        .orig-toggle .arrow{display:inline-block;transition:transform .2s;font-size:10px}
        .orig-toggle.open .arrow{transform:rotate(90deg)}
        .orig-text{font-size:12px;line-height:1.45;color:#5a6670;margin-top:4px;padding:6px 8px;background:#f8f9fa;border-radius:4px;display:none}
        .orig-text.vis{display:block}
        .section{margin-top:8px}.section h3{margin:0 0 3px;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:#7b8a94}
        .section .vals{font-size:12px;color:#3a4a53;line-height:1.5}
        .rips{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}
        .rip{font-size:10px;padding:2px 6px;background:#eef4f5;border-radius:4px;color:#4a606c}
        .rip strong{color:#1a2a33}
        .miss-tag{font-size:10px;padding:2px 6px;background:#fef0f0;border:1px solid #f5c6c6;border-radius:4px;color:#8b1a1a;display:inline-block;margin-top:6px}
        """,
        '</style></head><body>',
        f'<div class="top"><h1>KB Quick Guides</h1>',
        f'<p>Simple German + English for each A1 Kannbeschreibung. Click ▶ for the original Profile Deutsch text.</p>',
        '<div class="nav-bar">' + "".join(nav) + '</div>',
        '<div class="filters">',
        f'<input id="search" placeholder="Search by id, word, scene..." value="{escape(search)}">',
    ]

    if missing_only: parts.append('<a href="?missing=0" class="on">show missing only</a>')
    else: parts.append('<a href="?missing=1" class="">show missing only</a>')
    if hand_only: parts.append('<a href="?hand=0" class="on">hand-written only</a>')
    else: parts.append('<a href="?hand=1" class="">hand-written only</a>')
    if bare: parts.append('<a href="?view=full" class="on">bare view</a>')
    else: parts.append('<a href="?view=bare" class="">bare view</a>')

    all_cards = []
    for cat, items in sorted(categories.items()):
        for kann in items:
            focus = runner.derive_kann_focus(kann)
            guide = focus.get("quick_guide") or {}
            is_hand = kann["id"] in hand_guides
            all_cards.append((cat, kann, focus, guide, is_hand, kann.get("level", "")))

    hand_count = sum(1 for _, k, _, _, h, _ in all_cards if h)
    total = len(all_cards)
    parts.append(f'<div class="stats">{total} KBs · {hand_count} hand-written ({total - hand_count} fallback)</div>')
    parts.append('</div></div><div class="page">')

    parts.append('<div class="cat-tabs">')
    parts.append(f'<a href="?" class="cat-tab{" sel" if not cat_filter else ""}">All</a>')
    for cat in sorted(categories):
        cat_short = cat.replace("mündlich", "mündl.").replace("schriftlich", "schriftl.")
        sel = " sel" if cat_filter == cat else ""
        parts.append(f'<a href="?cat={escape(cat)}" class="cat-tab{sel}">{escape(cat_short)}</a>')
    parts.append('</div><div class="card-grid">')

    for cat, kann, focus, guide, is_hand, level in all_cards:
        if cat_filter and cat != cat_filter: continue
        if hand_only and not is_hand: continue
        if missing_only and is_hand: continue
        if search:
            hay = f"{kann['id']} {kann['kann']} {guide.get('kb_de_simple','')} {guide.get('kb_en_simple','')} {guide.get('scene','')} {' '.join(guide.get('word_bank',[]))} {' '.join(guide.get('core_phrases',[]))}".lower()
            if search not in hay: continue

        border_class = "hand" if is_hand else "fallback"
        ds = escape((kann["id"] + " " + kann["kann"] + " " + guide.get("kb_de_simple","") + " " + guide.get("kb_en_simple","") + " " + guide.get("scene","") + " " + " ".join(guide.get("word_bank",[])) + " " + " ".join(guide.get("core_phrases",[]))).lower())
        parts.append(f'<article class="card {border_class}" data-search="{ds}">')

        parts.append('<div class="card-head">')
        parts.append(f'<div><span class="kid">{escape(kann["id"])}</span>')
        if level: parts.append(f'<span class="lvl {escape(level)}">{escape(level)}</span>')
        if is_hand: parts.append('<span class="badge hw">hand</span>')
        else: parts.append('<span class="badge fb">auto</span>')
        parts.append('</div></div>')

        de_simple = guide.get("kb_de_simple", "")
        en_simple = guide.get("kb_en_simple", "")
        if de_simple: parts.append(f'<div class="simple-de">{escape(de_simple)}</div>')
        if en_simple: parts.append(f'<div class="simple-en">{escape(en_simple)}</div>')

        orig_id = f"orig-{kann['id']}"
        parts.append(f'<button class="orig-toggle" onclick="document.getElementById(\'{orig_id}\').classList.toggle(\'vis\');this.classList.toggle(\'open\')"><span class="arrow">▶</span> Original (Profile Deutsch)</button>')
        parts.append(f'<div class="orig-text" id="{orig_id}">{escape(kann["kann"])}</div>')

        if not bare:
            reduction = focus.get("reduction") or {}
            rips_parts = []
            for label, key in (("RIPS", "rips"), ("Carrier", "carrier"), ("Channel", "channel"), ("Persistence", "persistence"), ("Operation", "operation"), ("Output", "output")):
                val = reduction.get(key, "")
                if val: rips_parts.append(f'<span class="rip"><strong>{escape(label)}</strong> {escape(val)}</span>')
            if rips_parts: parts.append('<div class="rips">' + "".join(rips_parts) + '</div>')
            scene = guide.get("scene", "")
            roles = guide.get("roles", [])
            if scene or roles:
                parts.append('<div class="section"><h3>Scene</h3><div class="vals">' + escape(scene))
                if roles: parts.append(f' · {escape(", ".join(roles))}')
                parts.append('</div></div>')
            task = guide.get("task_shape", [])
            if task:
                parts.append('<div class="section"><h3>Task Shape</h3>')
                parts.append('<div class="vals">' + " → ".join(escape(t) for t in task[:4]) + '</div></div>')
            phrases = guide.get("core_phrases", [])
            if phrases: parts.append('<div class="section"><h3>Core Phrases</h3><div class="vals">' + escape(" · ".join(phrases[:6])) + '</div></div>')
            words_list = guide.get("word_bank", [])
            if words_list: parts.append('<div class="section"><h3>Word Bank</h3><div class="vals">' + escape(", ".join(words_list[:12])) + '</div></div>')
            grammar = guide.get("grammar_tools", [])
            if grammar: parts.append('<div class="section"><h3>Grammar Tools</h3><div class="vals">' + escape(" · ".join(grammar[:6])) + '</div></div>')
            if reduction.get("memory"):
                parts.append(f'<div class="section"><span style="font-size:10px;color:#7b8a94">Memory: </span><span style="font-size:11px">{escape(reduction["memory"])}</span></div>')
            related = guide.get("related_kbs", [])
            if related:
                parts.append('<div class="section"><h3>Related</h3>')
                rel_links = [f'<a href="?q={escape(rid)}" style="color:#0b5e55;font-size:12px">{escape(rid)}</a>' for rid in related[:6]]
                parts.append('<div class="vals">' + " ".join(rel_links) + '</div></div>')
            missing_fields = []
            for key in ("kb_de_simple", "kb_en_simple"):
                if not guide.get(key) or guide.get(key, "").startswith("Ich mache diese Aufgabe") or guide.get(key, "").startswith("I practice this can-do"):
                    missing_fields.append(key.replace("_", " "))
            if missing_fields and not is_hand:
                parts.append(f'<div class="miss-tag">needs: {escape(", ".join(missing_fields))}</div>')
        parts.append('</article>')

    parts.append('</div></div>')
    parts.append("""
    <script>
    const inp = document.getElementById('search');
    inp?.addEventListener('input', function(){
        const q = this.value.trim().toLowerCase();
        document.querySelectorAll('.card').forEach(c => {
            c.style.display = (!q || (c.getAttribute('data-search')||'').includes(q)) ? '' : 'none';
        });
    });
    </script></body></html>""")
    return "".join(parts)


# ---------------------------------------------------------------------------
# /quiz — memorize KB definitions
# ---------------------------------------------------------------------------
def _quiz_html(query_string):
    query = parse_qs(query_string or "")
    action = (query.get("a") or [""])[0].strip()
    current_kb_id = (query.get("kb") or [""])[0].strip().upper()
    guess = (query.get("g") or [""])[0].strip().upper()
    answer = (query.get("ans") or [""])[0].strip().upper()
    correct_count = int((query.get("c") or ["0"])[0])
    wrong_count = int((query.get("w") or ["0"])[0])
    direction = (query.get("d") or ["de"])[0]
    hand_only = (query.get("hand") or [""])[0] == "1"
    mc = (query.get("mc") or [""])[0]

    kbs_dict = {k["id"]: k for k in runner.all_kanns}
    hand_guides = runner.kann_quick_guides_cfg.get("guides", {})
    quiz_pool = [kid for kid in kbs_dict if not hand_only or kid in hand_guides]

    show_result = False
    was_correct = False
    if action == "guess" and answer and guess:
        show_result = True
        was_correct = (guess == answer)
        if was_correct: correct_count += 1
        else: wrong_count += 1
        current_kb_id = answer
    elif current_kb_id and current_kb_id in kbs_dict:
        pass
    else:
        current_kb_id = random.choice(quiz_pool) if quiz_pool else random.choice(list(kbs_dict.keys()))

    kann = kbs_dict.get(current_kb_id)
    if not kann:
        current_kb_id = random.choice(quiz_pool)
        kann = kbs_dict[current_kb_id]

    focus = runner.derive_kann_focus(kann)
    guide = focus.get("quick_guide", {})
    reduction = focus.get("reduction", {})
    de_simple = guide.get("kb_de_simple", "")
    en_simple = guide.get("kb_en_simple", "")
    rubric = _rubric_for(kann)

    total_qs = correct_count + wrong_count
    pct = int(100 * correct_count / total_qs) if total_qs > 0 else 0

    nav = [
        '<a href="/" class="nv">Classroom</a>',
        '<a href="/graph" class="nv">Graph</a>',
        '<a href="/guides" class="nv">Guides</a>',
        '<a href="/quiz" class="nv active">Quiz</a>',
        '<a href="/word" class="nv">Word→KB</a>',
    ]

    parts = [
        '<!DOCTYPE html><html><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>KB Quiz</title>',
        '<style>',
        """
        *{box-sizing:border-box} body{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f4f6f7;color:#1a2227}
        .top{position:sticky;top:0;z-index:10;background:#fff;border-bottom:1px solid #d9e0e3;padding:12px 18px}
        .top h1{margin:0;font-size:18px;color:#0b5e55}.top p{margin:4px 0 0;color:#5c6b74;font-size:13px}
        .nav-bar{display:flex;gap:10px;flex-wrap:wrap;margin-top:8px}
        .nv{color:#0b5e55;text-decoration:none;font-size:13px;padding:3px 8px;border-radius:4px;border:1px solid #c8d6db}
        .nv.active,.nv:hover{background:#0b5e55;color:#fff;border-color:#0b5e55}
        .page{padding:18px;max-width:720px;margin:0 auto}
        .score{text-align:center;margin-bottom:20px;font-size:14px}
        .score .num{font-weight:700;color:#0b5e55;font-size:22px}
        .score .bar{height:6px;background:#dde4e8;border-radius:3px;margin-top:6px;max-width:300px;margin-left:auto;margin-right:auto}
        .score .bar-inner{height:100%;border-radius:3px;background:#0b5e55;transition:width .3s}
        .quiz-card{background:#fff;border:1px solid #dde4e8;border-radius:10px;padding:20px;text-align:center}
        .quiz-card.correct{border-color:#2e8b57;border-width:2px}
        .quiz-card.wrong{border-color:#c44;border-width:2px}
        .rubric-hint{font-size:13px;color:#5c6b74;margin-bottom:8px}
        .prompt{font-size:20px;line-height:1.4;margin:16px 0;color:#1a3a1a;background:#eaf4ea;padding:16px;border-radius:8px}
        .prompt-id{font-size:28px;font-weight:800;color:#0b5e55;letter-spacing:2px}
        .guess-form{margin:16px 0}
        .guess-form input{width:180px;padding:10px 14px;border:2px solid #c8d6db;border-radius:6px;font:inherit;font-size:18px;text-align:center;letter-spacing:2px;font-weight:700}
        .guess-form input:focus{border-color:#0b5e55;outline:none}
        .guess-form button{padding:10px 20px;border:none;background:#0b5e55;color:#fff;border-radius:6px;font:inherit;font-size:16px;cursor:pointer;margin-left:8px}
        .mc-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:16px 0}
        .mc-btn{display:block;padding:10px 12px;border:2px solid #c8d6db;border-radius:8px;text-decoration:none;transition:border-color .15s,background .15s;text-align:left}
        .mc-btn:hover{border-color:#0b5e55;background:#e6f4f1}
        .mc-id{display:block;font-weight:800;font-size:16px;color:#0b5e55}
        .mc-rubric{display:block;font-size:11px;color:#5c6b74;margin-top:3px}
        .feedback{padding:12px;border-radius:6px;margin:12px 0;font-size:14px;text-align:left}
        .feedback.correct{background:#e6f4f0;border:1px solid #2e8b57;color:#1a3a2a}
        .feedback.wrong{background:#fef0f0;border:1px solid #e8b0b0;color:#6b2020}
        .feedback .given{font-weight:700;text-decoration:line-through;color:#c44}
        .feedback .expected{font-weight:700;color:#2e8b57}
        .detail{margin-top:12px;text-align:left}
        .detail .row{margin:4px 0;font-size:13px}
        .detail .lbl{color:#7b8a94;font-size:11px;text-transform:uppercase;letter-spacing:.04em}
        .detail .simple-de{background:#eaf4ea;padding:6px 8px;border-radius:4px;margin:4px 0;font-size:14px}
        .detail .simple-en{background:#f4f2e8;padding:6px 8px;border-radius:4px;margin:4px 0;font-size:13px}
        .detail .orig{font-size:12px;color:#5a6670;margin:4px 0;line-height:1.4}
        .next-btn{margin-top:16px;text-align:center}
        .next-btn a{padding:10px 24px;background:#0b5e55;color:#fff;border-radius:6px;text-decoration:none;font-size:15px;display:inline-block}
        .direction-toggle{margin-bottom:12px;font-size:13px}
        .direction-toggle a{padding:4px 10px;border:1px solid #c8d6db;border-radius:4px;text-decoration:none;color:#3a4a53;margin:0 4px}
        .direction-toggle a.on{background:#0b5e55;color:#fff;border-color:#0b5e55}
        """,
        '</style></head><body>',
        f'<div class="top"><h1>KB Memorization Quiz</h1>',
        f'<p>Learn the A1 Kannbeschreibungen by heart. Rubric + clue → guess KB ID.</p>',
        '<div class="nav-bar">' + "".join(nav) + '</div></div>',
        '<div class="page">',
    ]

    parts.append(f'<div class="score"><div><span class="num">{correct_count}</span> / {total_qs}</div><div class="bar"><div class="bar-inner" style="width:{pct}%"></div></div></div>')

    # Direction toggle
    parts.append('<div class="direction-toggle">Show: ')
    parts.append(f'<a href="?d=de&c={correct_count}&w={wrong_count}&hand={1 if hand_only else 0}&mc={mc}" class="{" on" if direction != "id" else ""}">Rubric → guess ID</a>')
    parts.append(f'<a href="?d=id&c={correct_count}&w={wrong_count}&hand={1 if hand_only else 0}&mc={mc}" class="{" on" if direction == "id" else ""}">KB ID → guess description</a>')
    parts.append(f'<a href="?d={direction}&c={correct_count}&w={wrong_count}&hand={0 if hand_only else 1}&mc={mc}" style="margin-left:12px;font-size:11px">{("All KBs" if hand_only else "Hand-written only")}</a>')
    parts.append('</div>')

    # Quiz card
    card_class = "correct" if (show_result and was_correct) else ("wrong" if (show_result and not was_correct) else "")
    parts.append(f'<div class="quiz-card {card_class}">')

    if direction == "id":
        parts.append(f'<div class="rubric-hint">{escape(rubric)}</div>')
        parts.append(f'<div class="prompt-id">{escape(current_kb_id)}</div>')
        parts.append('<div class="guess-form">')
        parts.append(f'<form method="get" action="/quiz">')
        parts.append(f'<input type="hidden" name="a" value="guess">')
        parts.append(f'<input type="hidden" name="kb" value="{escape(current_kb_id)}">')
        parts.append(f'<input type="hidden" name="ans" value="{escape(current_kb_id)}">')
        parts.append(f'<input type="hidden" name="d" value="{direction}">')
        parts.append(f'<input type="hidden" name="c" value="{correct_count}">')
        parts.append(f'<input type="hidden" name="w" value="{wrong_count}">')
        parts.append(f'<input type="hidden" name="hand" value="{1 if hand_only else 0}">')
        parts.append(f'<input type="hidden" name="mc" value="{mc}">')
        parts.append(f'<input name="g" placeholder="What does this KB mean?" autofocus>')
        parts.append(f'<button type="submit">Check</button>')
        parts.append('</form></div>')
    else:
        # Rubric as clue, guess KB ID
        parts.append(f'<div class="rubric-hint">{escape(rubric)}</div>')
        if de_simple and not de_simple.startswith("Ich mache diese Aufgabe"):
            parts.append(f'<div class="prompt">{escape(de_simple)}</div>')
        else:
            short = kann["kann"]
            if len(short) > 120: short = short[:117] + "..."
            parts.append(f'<div class="prompt" style="font-size:15px">{escape(short)}</div>')
        parts.append('<div class="guess-form">')

        if mc == "1":
            # COGNITIVE DISTRACTOR SELECTION
            # Pick 3 wrong answers that probe different memory dimensions:
            #   1. Same channel, different operation (e.g. verstehen vs weitergeben)
            #   2. Different channel, same operation (e.g. ear vs eye)
            #   3. Same category but far-away KB (tests granular memory)
            current_cat = kbs_dict[current_kb_id].get("category", "")
            current_reduction = runner.derive_kann_focus(kbs_dict[current_kb_id]).get("reduction", {})
            current_op = current_reduction.get("operation", "")
            current_channel = current_reduction.get("channel", "")
            current_cat_def = runner.kann_reductions_cfg.get("category_defaults", {}).get(current_cat, {})
            if not current_op: current_op = current_cat_def.get("operation", "")
            if not current_channel: current_channel = current_cat_def.get("channel", "")

            distractors = []
            # 1. Same channel, different operation (confusable carrier/sense)
            for kid in quiz_pool:
                if kid == current_kb_id: continue
                if kid in distractors: continue
                r = runner.derive_kann_focus(kbs_dict[kid]).get("reduction", {})
                kid_cat_def = runner.kann_reductions_cfg.get("category_defaults", {}).get(kbs_dict[kid].get("category", ""), {})
                kid_ch = r.get("channel") or kid_cat_def.get("channel", "")
                kid_op = r.get("operation") or kid_cat_def.get("operation", "")
                if kid_ch == current_channel and kid_op and current_op and kid_op != current_op:
                    distractors.append(kid)
                    break

            # 2. Different channel, same operation (sensory confusion)
            for kid in quiz_pool:
                if kid == current_kb_id: continue
                if kid in distractors: continue
                r = runner.derive_kann_focus(kbs_dict[kid]).get("reduction", {})
                kid_cat_def = runner.kann_reductions_cfg.get("category_defaults", {}).get(kbs_dict[kid].get("category", ""), {})
                kid_ch = r.get("channel") or kid_cat_def.get("channel", "")
                kid_op = r.get("operation") or kid_cat_def.get("operation", "")
                if kid_ch and current_channel and kid_ch != current_channel and kid_op == current_op:
                    distractors.append(kid)
                    break

            # 3+4. Same category, different KB (granular confusion from same domain)
            same_cat = [kid for kid in quiz_pool if kid != current_kb_id and kid not in distractors and kbs_dict[kid].get("category") == current_cat]
            if same_cat:
                random.shuffle(same_cat)
                distractors.extend(same_cat[:2])
            # Fill remaining slots with numeric neighbors
            current_num = int(current_kb_id[1:]) if current_kb_id[1:].isdigit() else 0
            while len(distractors) < 3:
                for kid in sorted(quiz_pool):
                    if kid == current_kb_id or kid in distractors: continue
                    kn = int(kid[1:]) if kid[1:].isdigit() else 999
                    if abs(kn - current_num) <= 10:
                        distractors.append(kid)
                        break
                else:
                    # Just pick any remaining
                    for kid in quiz_pool:
                        if kid != current_kb_id and kid not in distractors:
                            distractors.append(kid)
                            break
                    else:
                        break

            choices = [current_kb_id] + distractors[:3]
            random.shuffle(choices)
            parts.append('<div class="mc-grid">')
            for i, cid in enumerate(choices):
                c_kann = kbs_dict.get(cid, {})
                c_r = _rubric_for(c_kann) if c_kann else ""
                # Label the reason for cognitive feedback
                reason = ""
                if cid == current_kb_id:
                    reason = "✓ correct"
                elif i == 1:
                    reason = "same channel"
                elif i == 2:
                    reason = "different channel"
                else:
                    reason = "same category"
                parts.append(f'<a href="?a=guess&kb={escape(current_kb_id)}&ans={escape(current_kb_id)}&g={escape(cid)}&d={direction}&c={correct_count}&w={wrong_count}&hand={1 if hand_only else 0}&mc=1" class="mc-btn">')
                parts.append(f'<span class="mc-id">{escape(cid)}</span>')
                parts.append(f'<span class="mc-rubric">{escape(c_r[:50])}</span>')
                parts.append('</a>')
            parts.append('</div>')
            parts.append(f'<div style="margin-top:6px;font-size:11px;color:#7b8a94"><a href="?d={direction}&c={correct_count}&w={wrong_count}&hand={1 if hand_only else 0}">Switch to type-in mode</a></div>')
        else:
            parts.append(f'<form method="get" action="/quiz">')
            parts.append(f'<input type="hidden" name="a" value="guess">')
            parts.append(f'<input type="hidden" name="kb" value="{escape(current_kb_id)}">')
            parts.append(f'<input type="hidden" name="ans" value="{escape(current_kb_id)}">')
            parts.append(f'<input type="hidden" name="d" value="{direction}">')
            parts.append(f'<input type="hidden" name="c" value="{correct_count}">')
            parts.append(f'<input type="hidden" name="w" value="{wrong_count}">')
            parts.append(f'<input type="hidden" name="hand" value="{1 if hand_only else 0}">')
            parts.append(f'<input type="hidden" name="mc" value="{mc}">')
            parts.append(f'<input name="g" placeholder="K???" autofocus>')
            parts.append(f'<button type="submit">Check</button>')
            parts.append('</form>')
            parts.append(f'<div style="margin-top:6px;font-size:11px;color:#7b8a94"><a href="?d={direction}&c={correct_count}&w={wrong_count}&hand={1 if hand_only else 0}&mc=1">Switch to multiple choice</a></div>')

    if show_result:
        if was_correct:
            parts.append(f'<div class="feedback correct">✓ Correct! <span class="expected">{escape(answer)}</span></div>')
        else:
            parts.append(f'<div class="feedback wrong">✗ You wrote <span class="given">{escape(guess)}</span>, expected <span class="expected">{escape(answer)}</span></div>')

    # Details
    parts.append('<div class="detail">')
    parts.append(f'<div class="row"><span class="lbl">ID</span> {escape(kann["id"])} · {escape(kann.get("level",""))} · {escape(kann.get("category",""))}</div>')
    parts.append(f'<div class="row" style="font-size:15px;margin:6px 0;font-weight:600">{escape(rubric)}</div>')
    if de_simple: parts.append(f'<div class="simple-de">{escape(de_simple)}</div>')
    if en_simple: parts.append(f'<div class="simple-en">{escape(en_simple)}</div>')
    parts.append(f'<div class="orig">{escape(kann["kann"])}</div>')
    rips_bits = []
    for label, key in (("RIPS", "rips"), ("Carrier", "carrier"), ("Channel", "channel"), ("Persistence", "persistence"), ("Operation", "operation"), ("Output", "output")):
        val = reduction.get(key, "")
        if val: rips_bits.append(f"{label}: {val}")
    if rips_bits: parts.append(f'<div class="row" style="margin-top:4px"><span class="lbl">RIPS</span> {escape(" · ".join(rips_bits))}</div>')
    parts.append('</div>')
    parts.append('</div>')

    parts.append(f'<div class="next-btn"><a href="?d={direction}&c={correct_count}&w={wrong_count}&hand={1 if hand_only else 0}&mc={mc}">Next KB →</a></div>')
    parts.append('</div></body></html>')
    return "".join(parts)


# ---------------------------------------------------------------------------
# /drill — rapid dropdown KB quiz, 10 rounds, shows weak spots
# ---------------------------------------------------------------------------
def _drill_html(query_string):
    query = parse_qs(query_string or "")
    action = (query.get("a") or [""])[0].strip()
    current_kb_id = (query.get("kb") or [""])[0].strip().upper()
    chosen = (query.get("g") or [""])[0].strip().upper()
    round_num = int((query.get("r") or ["1"])[0])
    hand_only = (query.get("hand") or [""])[0] == "1"
    seen = (query.get("seen") or "").split(",")  # KB ids already used
    wrong = (query.get("wrong") or "").split(",")  # KB ids answered incorrectly
    wrong = [w for w in wrong if w.strip()]
    seen = [s for s in seen if s.strip()]

    kbs_dict = {k["id"]: k for k in runner.all_kanns}
    hand_guides = runner.kann_quick_guides_cfg.get("guides", {})
    pool = [kid for kid in kbs_dict if (not hand_only or kid in hand_guides) and kid not in seen]

    MAX_ROUNDS = 10
    just_answered = False
    was_correct = False
    prev_kb = None

    if action == "answer" and current_kb_id and chosen:
        just_answered = True
        was_correct = (chosen == current_kb_id)
        prev_kb = kbs_dict.get(current_kb_id)
        if not was_correct and current_kb_id not in wrong:
            wrong = wrong + [current_kb_id]
        seen = seen + [current_kb_id]
        round_num += 1

    if round_num > MAX_ROUNDS or not pool:
        # Show summary
        correct_count = MAX_ROUNDS - len(wrong)
        nav = [
            '<a href="/" class="nv">Classroom</a>',
            '<a href="/graph" class="nv">Graph</a>',
            '<a href="/guides" class="nv">Guides</a>',
            '<a href="/quiz" class="nv">Quiz</a>',
            '<a href="/drill" class="nv active">Drill</a>',
        ]
        parts = [
            '<!DOCTYPE html><html><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1">',
            '<title>Drill Results</title>',
            '<style>',
            '*{box-sizing:border-box} body{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f4f6f7;color:#1a2227}',
            '.top{position:sticky;top:0;z-index:10;background:#fff;border-bottom:1px solid #d9e0e3;padding:12px 18px}',
            '.top h1{margin:0;font-size:18px;color:#0b5e55}.nav-bar{display:flex;gap:10px;flex-wrap:wrap;margin-top:8px}',
            '.nv{color:#0b5e55;text-decoration:none;font-size:13px;padding:3px 8px;border-radius:4px;border:1px solid #c8d6db}',
            '.nv.active,.nv:hover{background:#0b5e55;color:#fff;border-color:#0b5e55}',
            '.page{padding:18px;max-width:700px;margin:0 auto}',
            '.result{font-size:28px;text-align:center;margin:20px 0}',
            '.result .big{font-weight:800;color:#0b5e55;font-size:48px}',
            '.review-card{border:1px solid #f0d0d0;border-radius:8px;background:#fff;padding:12px;margin-bottom:10px;border-left:3px solid #c44}',
            '.review-card h3{margin:0 0 4px;font-size:13px;color:#0b5e55}',
            '.review-card .text{font-size:12px;line-height:1.4;color:#3a4a53}',
            '.simple-de{font-size:14px;margin:4px 0;padding:6px 8px;background:#eaf4ea;color:#1a3a1a;border-radius:4px}',
            '</style></head><body>',
            f'<div class="top"><h1>Drill Complete</h1><div class="nav-bar">{"".join(nav)}</div></div>',
            '<div class="page">',
            f'<div class="result"><div class="big">{correct_count}/{MAX_ROUNDS}</div>correct</div>',
        ]
        if wrong:
            parts.append(f'<h3>Review these ({len(wrong)}):</h3>')
            for wid in wrong:
                kb = kbs_dict.get(wid)
                if not kb: continue
                focus = runner.derive_kann_focus(kb)
                guide = focus.get("quick_guide", {})
                de_simple = guide.get("kb_de_simple", "")
                rubric = _rubric_for(kb)
                parts.append(f'<div class="review-card"><h3>{escape(wid)} · {escape(rubric)}</h3>')
                if de_simple: parts.append(f'<div class="simple-de">{escape(de_simple)}</div>')
                parts.append(f'<div class="text">{escape(kb["kann"])}</div></div>')
        parts.append(f'<p style="text-align:center;margin-top:20px"><a href="/drill?hand={1 if hand_only else 0}" style="padding:10px 24px;background:#0b5e55;color:#fff;border-radius:6px;text-decoration:none;font-size:15px">Start New Drill</a></p>')
        parts.append('</div></body></html>')
        return "".join(parts)

    # Pick next KB
    if not current_kb_id or current_kb_id not in kbs_dict or not pool:
        current_kb_id = random.choice(pool)
    kann = kbs_dict[current_kb_id]
    focus = runner.derive_kann_focus(kann)
    guide = focus.get("quick_guide", {})
    de_simple = guide.get("kb_de_simple", "")
    rubric = _rubric_for(kann)

    # Build dropdown with all KBs from the pool
    dropdown_options = []
    for kid in sorted(pool + [current_kb_id]):
        dropdown_options.append(f'<option value="{escape(kid)}">{escape(kid)}</option>')

    nav = [
        '<a href="/" class="nv">Classroom</a>',
        '<a href="/graph" class="nv">Graph</a>',
        '<a href="/guides" class="nv">Guides</a>',
        '<a href="/quiz" class="nv">Quiz</a>',
        '<a href="/drill" class="nv active">Drill</a>',
    ]
    parts = [
        '<!DOCTYPE html><html><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>KB Drill</title>',
        '<style>',
        '*{box-sizing:border-box} body{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f4f6f7;color:#1a2227}',
        '.top{position:sticky;top:0;z-index:10;background:#fff;border-bottom:1px solid #d9e0e3;padding:12px 18px}',
        '.top h1{margin:0;font-size:18px;color:#0b5e55}.nav-bar{display:flex;gap:10px;flex-wrap:wrap;margin-top:8px}',
        '.nv{color:#0b5e55;text-decoration:none;font-size:13px;padding:3px 8px;border-radius:4px;border:1px solid #c8d6db}',
        '.nv.active,.nv:hover{background:#0b5e55;color:#fff;border-color:#0b5e55}',
        '.page{padding:18px;max-width:600px;margin:0 auto}',
        '.progress{margin-bottom:12px;font-size:13px;color:#6b7c85;text-align:center}',
        '.card{background:#fff;border:1px solid #dde4e8;border-radius:10px;padding:20px;text-align:center}',
        '.card.correct{border-color:#2e8b57;border-width:2px}',
        '.card.wrong{border-color:#c44;border-width:2px}',
        '.rubric-hint{font-size:13px;color:#5c6b74;margin-bottom:8px}',
        '.prompt{font-size:18px;line-height:1.4;margin:12px 0;color:#1a3a1a;background:#eaf4ea;padding:14px;border-radius:8px}',
        '.drill-form{margin:14px 0}',
        '.drill-form select{width:100%;padding:10px;border:2px solid #c8d6db;border-radius:6px;font:inherit;font-size:16px;text-align:center;font-weight:700;appearance:none;cursor:pointer}',
        '.drill-form select:focus{border-color:#0b5e55;outline:none}',
        '.drill-form button{margin-top:8px;padding:10px 24px;border:none;background:#0b5e55;color:#fff;border-radius:6px;font:inherit;font-size:15px;cursor:pointer}',
        '.feedback{padding:10px;border-radius:6px;margin:10px 0;font-size:13px}',
        '.feedback.correct{background:#e6f4f0;border:1px solid #2e8b57;color:#1a3a2a}',
        '.feedback.wrong{background:#fef0f0;border:1px solid #e8b0b0;color:#6b2020}',
        '.detail{text-align:left;margin-top:8px;font-size:12px;line-height:1.4;color:#3a4a53}',
        '.next-btn{margin-top:14px;text-align:center}',
        '.next-btn a{padding:10px 24px;background:#0b5e55;color:#fff;border-radius:6px;text-decoration:none;font-size:15px;display:inline-block}',
        '</style></head><body>',
        f'<div class="top"><h1>KB Dropdown Drill</h1><p>Pick the correct KB ID from the dropdown. {MAX_ROUNDS} rounds.</p><div class="nav-bar">{"".join(nav)}</div></div>',
        '<div class="page">',
    ]

    parts.append(f'<div class="progress">Round {round_num} of {MAX_ROUNDS} · {len(wrong)} wrong so far · <a href="?hand={0 if hand_only else 1}" style="color:#0b5e55">{("All KBs" if hand_only else "Hand-written only")}</a></div>')

    card_class = ""
    if just_answered:
        card_class = "correct" if was_correct else "wrong"
    parts.append(f'<div class="card {card_class}">')

    parts.append(f'<div class="rubric-hint">{escape(rubric)}</div>')
    if de_simple and not de_simple.startswith("Ich mache diese Aufgabe"):
        parts.append(f'<div class="prompt">{escape(de_simple)}</div>')
    else:
        short = kann["kann"][:140]
        parts.append(f'<div class="prompt" style="font-size:15px">{escape(short)}</div>')

    parts.append('<div class="drill-form">')
    parts.append(f'<form method="get" action="/drill">')
    parts.append(f'<input type="hidden" name="a" value="answer">')
    parts.append(f'<input type="hidden" name="kb" value="{escape(current_kb_id)}">')
    parts.append(f'<input type="hidden" name="r" value="{round_num}">')
    parts.append(f'<input type="hidden" name="seen" value="{escape(",".join(seen))}">')
    parts.append(f'<input type="hidden" name="wrong" value="{escape(",".join(wrong))}">')
    parts.append(f'<input type="hidden" name="hand" value="{1 if hand_only else 0}">')
    parts.append(f'<select name="g" autofocus onchange="this.form.submit()">')
    parts.append(f'<option value="">-- Pick the KB ID --</option>')
    parts.append("".join(dropdown_options))
    parts.append('</select>')
    parts.append(f'<button type="submit">Check</button>')
    parts.append('</form></div>')

    if just_answered:
        if was_correct:
            parts.append(f'<div class="feedback correct">✓ Correct! {escape(current_kb_id)}</div>')
        else:
            expected = current_kb_id
            if prev_kb:
                parts.append(f'<div class="feedback wrong">✗ You chose {escape(chosen)}. The correct answer is {escape(expected)}.</div>')
        # Show detail
        parts.append(f'<div class="detail"><b>{escape(current_kb_id)}</b>: {escape(kann["kann"])}</div>')

    parts.append('</div>')

    parts.append(f'<div class="next-btn"><a href="/drill?r={round_num}&seen={escape(",".join(seen))}&wrong={escape(",".join(wrong))}&hand={1 if hand_only else 0}">Skip / Next →</a></div>')
    parts.append('</div></body></html>')
    return "".join(parts)


# ---------------------------------------------------------------------------
# /graph — compressed KB cluster graph with bridge edges
# ---------------------------------------------------------------------------
def _graph_html(query_string):
    """Serve the KB compressed graph as a single static SVG."""
    import os
    svg_path = os.path.join(os.path.dirname(__file__), "kb_graph.svg")
    with open(svg_path, "r") as f:
        svg_content = f.read()

    nav = [
        '<a href="/" class="nv">Classroom</a>',
        '<a href="/graph" class="nv active">Graph</a>',
        '<a href="/guides" class="nv">Guides</a>',
        '<a href="/quiz" class="nv">Quiz</a>',
        '<a href="/drill" class="nv">Drill</a>',
        '<a href="/word" class="nv">Word→KB</a>',
    ]
    parts = [
        '<!DOCTYPE html><html><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>KB Graph</title>',
        '<style>',
        '*{box-sizing:border-box} body{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f4f6f7;color:#1a2227}',
        '.top{position:sticky;top:0;z-index:10;background:#fff;border-bottom:1px solid #d9e0e3;padding:12px 18px}',
        '.top h1{margin:0;font-size:18px;color:#0b5e55}.top p{margin:4px 0 0;color:#5c6b74;font-size:13px}',
        '.nav-bar{display:flex;gap:10px;flex-wrap:wrap;margin-top:8px}',
        '.nv{color:#0b5e55;text-decoration:none;font-size:13px;padding:3px 8px;border-radius:4px;border:1px solid #c8d6db}',
        '.nv.active,.nv:hover{background:#0b5e55;color:#fff;border-color:#0b5e55}',
        '.page{padding:14px 18px}',
        '.graph-container{background:#f4f6f7;border-radius:8px;overflow:hidden;border:1px solid #dde4e8}',
        '</style></head><body>',
        '<div class="top"><h1>KB Compressed Graph</h1>',
        '<p>Clusters within categories, bridges across channels.</p>',
        '<div class="nav-bar">' + "".join(nav) + '</div></div>',
        '<div class="page"><div class="graph-container">',
        svg_content,
        '</div></div></body></html>',
    ]
    return "".join(parts)


    def _graph_cluster_html():
        """Cluster graph: categories as boxes with sub-clusters, bridge edges across domains."""
        kbs_dict = {k["id"]: k for k in runner.all_kanns}
        reductions = runner.kann_reductions_cfg
        overrides = reductions.get("manual_overrides", {})
        cat_defaults = reductions.get("category_defaults", {})
        hand_guides = runner.kann_quick_guides_cfg.get("guides", {})

        CATEGORIES = [
            # Interaction: amber / gold family
            ("Interaktion mündlich",    "K001", "K041", "ear ↔ mouth",   "#fef9e7", "#f5d66e", "#8b6914"),
            ("Interaktion schriftlich", "K042", "K059", "hand ↔ eye",    "#fff8e1", "#f2c94c", "#7a5c14"),
            # Reception: blue family
            ("Rezeption mündlich",      "K060", "K083", "ear / disappears","#e8f0fe","#7899d4","#1e4a8a"),
            ("Rezeption schriftlich",   "K084", "K115", "eye / stays",   "#dce8fa","#5a7fc0","#0a3a6a"),
            # Production: green family
            ("Produktion mündlich",     "K116", "K132", "mouth / disappears","#e8f5e9","#7cba80","#2e6a2e"),
            ("Produktion schriftlich",  "K133", "K152", "hand / stays",  "#dceadc","#5e9e62","#1e4a1e"),
            # Mediation: red / coral family
            ("Sprachmittlung mündlich", "K153", "K176", "mouth after read/hear","#fef0ee","#e8847a","#a02020"),
        ]

        IM_CLUSTERS = [
            ("basic communication · Grundlagen",               ["K001","K002","K003","K004","K005","K006","K007","K008","K009"]),
            ("greetings & introductions · Begrüßung & Vorstellung", ["K010","K011","K012","K013","K014","K015","K016","K017"]),
            ("wellbeing & preferences · Befinden & Vorlieben",  ["K018","K019","K020","K021","K022","K023","K024","K025"]),
            ("requests & answers · Bitten & Antworten",         ["K026","K027","K028","K029","K030","K031","K032","K033"]),
            ("numbers & transactions · Zahlen & Geschäfte",    ["K034","K035","K036","K037"]),
            ("asking for help · um Hilfe bitten",              ["K038","K039","K040","K041"]),
        ]

        RS_CLUSTERS = [
            ("single words · einzelne Wörter",                  ["K084","K085","K086"]),
            ("numbers & tables · Zahlen & Tabellen",             ["K087","K092","K095"]),
            ("public signs · Schilder & Aufschriften",          ["K100","K101","K102","K103"]),
            ("instructions · Anleitungen",                      ["K104"]),
            ("forms · Formulare",                               ["K105","K106","K107","K108","K109","K110"]),
            ("everyday texts · Alltagstexte",                   ["K111","K112","K113","K114","K115"]),
        ]

        SM_CLUSTERS = [
            ("DE → shared language · DE → gemeinsame Sprache", ["K153","K154","K155","K156","K157","K158","K159","K160","K161","K162","K163","K164","K165","K166"]),
            ("other lang → DE · andere Sprache → DE",          ["K167","K168","K169","K170","K171","K172","K173","K174","K175","K176"]),
        ]

        # gather bridge edges from near_kbs and related_kbs
        bridges = []
        for kid, ov in overrides.items():
            for near in ov.get("near_kbs", []):
                bridges.append((kid, near, "near"))
        for kid, guide in hand_guides.items():
            for rel in guide.get("related_kbs", []):
                bridges.append((kid, rel, "related"))

        def _cid(kid):
            """Category index 0..6 for a KB id"""
            n = int(kid[1:])
            if n <= 41:  return 0
            if n <= 59:  return 1
            if n <= 83:  return 2
            if n <= 115: return 3
            if n <= 132: return 4
            if n <= 152: return 5
            return 6

        # collect cross-category edges (filter out same-category)
        cross_edges = []
        seen = set()
        for a, b, typ in bridges:
            ca, cb = _cid(a), _cid(b)
            if ca == cb: continue
            key = tuple(sorted([a, b]))
            if key in seen: continue
            seen.add(key)
            cross_edges.append((a, b, typ, ca, cb))

        # layout constants
        COL_X = [20, 250, 510, 250, 510, 250, 250]
        CAT_Y = [80, 420, 80, 420, 80, 420, 790]
        CAT_W = [220, 220, 240, 260, 240, 260, 520]
        CAT_H = [320, 120, 210, 340, 210, 210, 140]
        IM_SUB_Y = [55, 99, 143, 187, 231, 275]
        IM_SUB_H = 38
        RS_SUB_Y = [55, 105, 155, 205, 255, 305]
        RS_SUB_H = 42

        def _box_color(cat_idx):
            colors = ["#fef9e7","#fff8e1","#e8f0fe","#dce8fa","#e8f5e9","#dceadc","#fef0ee"]
            strokes = ["#f5d66e","#f2c94c","#7899d4","#5a7fc0","#7cba80","#5e9e62","#e8847a"]
            return colors[cat_idx], strokes[cat_idx]

        def _hs(kid):
            return kid in hand_guides

        def _esc(t):
            return escape(str(t))

        # --- SVG ---
        svg = []
        svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 820 960" font-family="-apple-system,Segoe UI,sans-serif">')
        svg.append(f'<rect width="820" height="960" fill="#fff"/>')
        svg.append(f'<text x="410" y="28" text-anchor="middle" font-size="15" font-weight="700" fill="#1a2227">KB Compressed Graph</text>')

        # Small legend in top-right
        svg.append(f'<g transform="translate(600,10)">')
        svg.append(f'<rect x="0" y="0" width="210" height="26" rx="4" fill="#f4f6f7" stroke="#ddd"/>')
        svg.append(f'<line x1="10" y1="10" x2="30" y2="10" stroke="#1a2227" stroke-width="2" stroke-dasharray="6,3"/>')
        svg.append(f'<text x="36" y="14" font-size="9" fill="#555">= cross-domain</text>')
        svg.append(f'<line x1="110" y1="10" x2="130" y2="10" stroke="#1a2227" stroke-width="2"/>')
        svg.append(f'<text x="136" y="14" font-size="9" fill="#555">= within-domain</text>')
        svg.append('</g>')

        # Draw bridge edges — simple orthogonal (L-shaped) lines
        for a, b, typ, ca, cb in cross_edges:
            ax = COL_X[ca] + CAT_W[ca] / 2
            ay = CAT_Y[ca] + CAT_H[ca] / 2
            bx = COL_X[cb] + CAT_W[cb] / 2
            by = CAT_Y[cb] + CAT_H[cb] / 2
            if ca == 0:
                for i, cl in enumerate(IM_CLUSTERS):
                    if a in cl[1]:
                        ay = CAT_Y[0] + IM_SUB_Y[i] + IM_SUB_H / 2
                        break
            if cb == 0:
                for i, cl in enumerate(IM_CLUSTERS):
                    if b in cl[1]:
                        by = CAT_Y[0] + IM_SUB_Y[i] + IM_SUB_H / 2
                        break
            if ca == 3:
                for i, cl in enumerate(RS_CLUSTERS):
                    if a in cl[1]:
                        ay = CAT_Y[3] + RS_SUB_Y[i] + RS_SUB_H / 2
                        break
            if cb == 3:
                for i, cl in enumerate(RS_CLUSTERS):
                    if b in cl[1]:
                        by = CAT_Y[3] + RS_SUB_Y[i] + RS_SUB_H / 2
                        break
            # orthogonal path: horizontal then vertical
            midx = (ax + bx) / 2
            ax_i, ay_i, bx_i, by_i = int(ax), int(ay), int(bx), int(by)
            midx_i = int(midx)
            domain_a = 0 if ca <= 1 else (1 if ca <= 3 else (2 if ca <= 5 else 3))
            domain_b = 0 if cb <= 1 else (1 if cb <= 3 else (2 if cb <= 5 else 3))
            dash = "6,3" if domain_a != domain_b else "none"
            mid_y = (ay_i + by_i) / 2 - 8
            label_text = "domain hop" if domain_a != domain_b else ""
            svg.append(f'<polyline points="{ax_i},{ay_i} {midx_i},{ay_i} {midx_i},{by_i} {bx_i},{by_i}" fill="none" stroke="#1a2227" stroke-width="1.8" stroke-dasharray="{dash}" opacity="0.35" marker-end="url(#a)"/>')
            # small dot at origin
            svg.append(f'<circle cx="{ax_i}" cy="{ay_i}" r="3" fill="#1a2227" opacity="0.4"/>')
            # label
            svg.append(f'<text x="{midx_i+4}" y="{int(mid_y)}" font-size="7" fill="#888">{label_text}</text>')

        # Arrow marker
        svg.append('<defs><marker id="a" markerWidth="6" markerHeight="6" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#1a2227" opacity="0.35"/></marker></defs>')

        # Category boxes
        for ci, (name, first, last, detail, bg, stroke, fg) in enumerate(CATEGORIES):
            x, y, w, h = COL_X[ci], CAT_Y[ci], CAT_W[ci], CAT_H[ci]
            count = sum(1 for k in kbs_dict.values() if _cid(k["id"]) == ci)
            hcount = sum(1 for k in kbs_dict.values() if _cid(k["id"]) == ci and k["id"] in hand_guides)
            prefix = name.replace(" muendlich"," mndl.").replace(" schriftlich"," schr.")
            svg.append(f'<g transform="translate({x},{y})">')
            svg.append(f'<rect x="0" y="0" width="{w}" height="{h}" rx="0" fill="{bg}" stroke="{stroke}" stroke-width="2"/>')
            svg.append(f'<text x="8" y="18" font-size="10" font-weight="700" fill="{fg}">{_esc(prefix)}</text>')
            svg.append(f'<text x="8" y="32" font-size="8" fill="{fg}" opacity="0.6">{first}–{last} · {detail}</text>')

            has_reduction = cat_defaults.get(name)
            note = f"{count} KBs" if not has_reduction else f"{count} KBs"
            svg.append(f'<text x="8" y="{h-6}" font-size="8" fill="{fg}" opacity="0.4">{note}</text>')

            # Sub-clusters for Im
            if ci == 0:
                for i, cl in enumerate(IM_CLUSTERS):
                    sx, sy = 8, IM_SUB_Y[i]
                    sw, sh = w - 16, IM_SUB_H
                    fill_c, str_c = _box_color(ci)
                    svg.append(f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="0" fill="{fill_c}" stroke="{str_c}" stroke-width="1"/>')
                    svg.append(f'<text x="{sx+6}" y="{sy+14}" font-size="8" font-weight="600" fill="{fg}">{_esc(cl[0])}</text>')
                    ids_text = " · ".join(f"{kid}{'✍' if _hs(kid) else ''}" for kid in cl[1])
                    svg.append(f'<text x="{sx+6}" y="{sy+28}" font-size="7" fill="{fg}" opacity="0.6">{_esc(ids_text)}</text>')
                    kid_list = ",".join(cl[1])
                    svg.append(f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="0" fill="transparent" cursor="pointer" onclick="window.location.href=\'/guides?q={kid_list}\'"/><title>{_esc(cl[0])}</title>')

            # Sub-clusters for Rs
            if ci == 3:
                for i, cl in enumerate(RS_CLUSTERS):
                    sx, sy = 8, RS_SUB_Y[i]
                    sw, sh = w - 16, RS_SUB_H
                    fill_c, str_c = _box_color(ci)
                    svg.append(f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="0" fill="{fill_c}" stroke="{str_c}" stroke-width="1"/>')
                    svg.append(f'<text x="{sx+6}" y="{sy+14}" font-size="8" font-weight="600" fill="{fg}">{_esc(cl[0])}</text>')
                    ids_text = " · ".join(f"{kid}{'✍' if _hs(kid) else ''}" for kid in cl[1])
                    svg.append(f'<text x="{sx+6}" y="{sy+28}" font-size="7" fill="{fg}" opacity="0.6">{_esc(ids_text)}</text>')
                    kid_list = ",".join(cl[1])
                    svg.append(f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="0" fill="transparent" cursor="pointer" onclick="window.location.href=\'/guides?q={kid_list}\'"/><title>{_esc(cl[0])}</title>')

            # Sub-clusters for Sm
            if ci == 6:
                for i, cl in enumerate(SM_CLUSTERS):
                    sx, sy = 8 + i * 255, 48
                    sw, sh = 242, 82
                    fill_c, str_c = _box_color(ci)
                    svg.append(f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="0" fill="{fill_c}" stroke="{str_c}" stroke-width="1"/>')
                    svg.append(f'<text x="{sx+6}" y="{sy+14}" font-size="8" font-weight="600" fill="#a02020">{_esc(cl[0])}</text>')
                    id_samples = " · ".join(f"{kid}{'✍' if _hs(kid) else ''}" for kid in cl[1][:5])
                    svg.append(f'<text x="{sx+6}" y="{sy+28}" font-size="7" fill="#a02020" opacity="0.6">{_esc(id_samples)}</text>')
                    if i == 1:
                        svg.append(f'<text x="{sx+6}" y="{sy+42}" font-size="7" fill="#a02020" opacity="0.5">shop door → toilet → hotel board</text>')
                    kid_list = ",".join(cl[1])
                    svg.append(f'<rect x="{sx}" y="{sy}" width="{sw}" height="{sh}" rx="0" fill="transparent" cursor="pointer" onclick="window.location.href=\'/guides?q={kid_list}\'"/><title>{_esc(cl[0])}</title>')

            svg.append('</g>')

        svg.append('</svg>')

        # --- HTML wrapper ---
    nav = [
        '<a href="/" class="nv">Classroom</a>',
        '<a href="/graph" class="nv active">Graph</a>',
        '<a href="/graph?v=original" class="nv">Original</a>',
        '<a href="/graph?v=matrix" class="nv">Matrix</a>',
        '<a href="/guides" class="nv">Guides</a>',
        '<a href="/quiz" class="nv">Quiz</a>',
        '<a href="/drill" class="nv">Drill</a>',
        '<a href="/word" class="nv">Word→KB</a>',
    ]
    parts = [
        '<!DOCTYPE html><html><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>KB Graph</title>',
            '<style>',
            '*{box-sizing:border-box} body{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f4f6f7;color:#1a2227}',
            '.top{position:sticky;top:0;z-index:10;background:#fff;border-bottom:1px solid #d9e0e3;padding:12px 18px}',
            '.top h1{margin:0;font-size:18px;color:#0b5e55}.top p{margin:4px 0 0;color:#5c6b74;font-size:13px}',
            '.nav-bar{display:flex;gap:10px;flex-wrap:wrap;margin-top:8px}',
            '.nv{color:#0b5e55;text-decoration:none;font-size:13px;padding:3px 8px;border-radius:4px;border:1px solid #c8d6db}',
            '.nv.active,.nv:hover{background:#0b5e55;color:#fff;border-color:#0b5e55}',
            '.page{padding:14px 18px;max-width:860px}',
            '.legend-note{font-size:11px;color:#6b7c85;margin-top:4px}',
            '</style></head><body>',
            '<div class="top"><h1>KB Compressed Graph</h1>',
            '<p>Clusters within categories, bridge edges across channels. Click any cluster to open its KBs in the Guides view.</p>',
            '<div class="nav-bar">' + "".join(nav) + '</div></div>',
            '<div class="page">',
            '<p class="legend-note">Dashed edges = cross-domain bridges. Solid edges = within-domain connections. Click any cluster to open its KBs.</p>',
            "".join(svg),
        '</div></body></html>',
    ]
    return "".join(parts)


def _graph_matrix_html():
    """Carrier × Operation matrix: rows=physical objects, cols=what you can do."""
    kbs_dict = {k["id"]: k for k in runner.all_kanns}
    reductions = runner.kann_reductions_cfg
    overrides = reductions.get("manual_overrides", {})
    hand_guides = runner.kann_quick_guides_cfg.get("guides", {})
    _esc = lambda t: escape(str(t))
    _hs = lambda kid: "✍" if kid in hand_guides else ""

    # Carrier → KB mapping from manual_overrides + carrier_matrix
    carrier_kb = {}
    carrier_channel = {}
    for kid, ov in overrides.items():
        carr = ov.get("carrier", "")
        if carr:
            carrier_kb.setdefault(carr, []).append(kid)
            ckeys = ov.get("carrier_matrix_keys", [])
            for ck in ckeys:
                carrier_kb.setdefault(ck, []).append(kid)

    # carrier_matrix channel assignments
    cm = reductions.get("carrier_matrix", {})
    for cname, cdata in cm.items():
        carrier_channel[cname] = cdata.get("channel", "")
        if cname not in carrier_kb:
            carrier_kb[cname] = []

    # Also assign remaining KBs by keyword matching in kann text
    CARRIER_KW = [
        (["schild","aufschrift","eingang","ausgang","wc","apotheke","verboten","rauchen","parken","geschlossen","geöffnet","tür"], 0),
        (["aushang","tafel","notiz","notieren","stichpunkt","aufschreiben","prospekt","anzeige"], 1),
        (["fahrplan","abfahrt","gleis","zug","bus","haltestelle","reiseplan","reiseroute","busverkehr"], 2),
        (["formular","fragebogen","anmeldung","anmeldeformular"], 3),
        (["informationstafel","informationstext","hotel","rezeption","frühstück","checkout","breakfast","zimmerservice","zimmer","unterkunft","informationstafel"], 4),
        (["durchsage","ansage","aufruf","angesagt","durchgesagt","telefonansage","nachricht","mitteilung","information","hören","gesprochen","hörtext"], 5),
        (["gespräch","frage","antwort","sprechen","sagen","erzählen","mitteilen","unterhalten","kolleg","bekannt","freund","gruß","begrüßung","verabschiedung","vorstellen","vorlieben","abneigungen","bitten","danken"], 6),
        (["anleitung","anweisung","drücken","ziehen","öffnen","schließen","start","stopp","benutzen","gebrauch","bedienung","instruktion","programm","kopieren"], 7),
    ]
    for kid, kb in kbs_dict.items():
        if kid in overrides: continue  # already placed via manual overrides
        if kid in hand_guides: continue  # already placed via scenes
        txt = kb.get("kann", "").lower()
        cat = kb.get("category", "")
        if "Rezeption" in cat:   op_col = 0
        elif "Produktion" in cat and "schriftlich" in cat: op_col = 2
        elif "Produktion" in cat: op_col = 1
        elif "Interaktion" in cat: op_col = 1
        elif "Sprachmittlung" in cat: op_col = 3
        else: continue
        for keywords, row in CARRIER_KW:
            if any(kw in txt for kw in keywords):
                matrix[(row, op_col)].add(kid)
                break

    # Define matrix grid
    # Colors: row bg matches the dominant domain for that carrier row
    CARRIERS = [
        ("Schild / Aufschrift",    "sign / label",      "#e0f2f1", "#80cbc4"),  # reception (reading)
        ("Aushang / Tafel",        "notice / board",    "#e0f2f1", "#80cbc4"),  # reception (reading)
        ("Fahrplan",               "timetable",         "#e0f2f1", "#80cbc4"),  # reception (reading)
        ("Formular",               "form",              "#f3e5f5", "#ce93d8"),  # interaction (written)
        ("Informationstafel",      "info board",        "#fbe9e7", "#ff8a65"),  # mediation
        ("Durchsage / Ansage",     "announcement",      "#e3f2fd", "#90caf9"),  # reception (listening)
        ("Gespräch / Frage",       "conversation",      "#fff3e0", "#ffcc80"),  # interaction (spoken)
        ("Anweisung",              "instruction",       "#fff8e1", "#ffcc80"),  # interaction (listen+do)
    ]

    OPERATIONS = [
        ("verstehen",      "understand",       "#e0f2f1"),  # reception
        ("sagen / sprechen","say / speak",      "#fff3e0"),  # interaction/production spoken
        ("aufschreiben",   "write down",        "#fce4ec"),  # production written
        ("weitergeben",    "pass on / relay",   "#fbe9e7"),  # mediation
    ]

    # Assign KBs to cells: combine overrides + carrier_matrix operations
    # Build explicit cell assignments
    matrix = {}
    for ri, carr in enumerate(CARRIERS):
        for ci, op in enumerate(OPERATIONS):
            matrix[(ri, ci)] = set()

    # From overrides + carrier_matrix
    for kid, ov in overrides.items():
        carrier = ov.get("carrier", "")
        ckeys = ov.get("carrier_matrix_keys", [])
        # map carrier text to row
        row = None
        for ri, (cname, _, _, _) in enumerate(CARRIERS):
            if cname.lower().startswith(carrier.lower().split(" ")[0]) or carrier.lower() in cname.lower():
                row = ri
                break
            for ck in ckeys:
                if ck.lower() in cname.lower():
                    row = ri
                    break
            if row is not None:
                break
        if row is None:
            # try matching by carrier_matrix key
            for ck in ckeys:
                for ri, (cname, _, _, _) in enumerate(CARRIERS):
                    if ck.lower() in cname.lower():
                        row = ri
                        break
                if row is not None:
                    break
        if row is None: continue

        # operation column
        # look up from carrier_matrix
        op_col = None
        for ck in ckeys:
            cdata = cm.get(ck, {})
            cm_op = cdata.get("operation", "")
            for ci, (op_de, _, _) in enumerate(OPERATIONS):
                if op_de in cm_op or any(w in cm_op for w in op_de.split(" / ")):
                    op_col = ci
                    break
            if op_col is not None: break
        # fallback: derive from category
        if op_col is None:
            cat_op = ov.get("operation", "")
            for ci, (op_de, _, _) in enumerate(OPERATIONS):
                if op_de in cat_op or any(w in cat_op for w in op_de.split(" / ")):
                    op_col = ci
                    break
        if op_col is None: continue
        matrix[(row, op_col)].add(kid)

    # Additional: assign KBs from hand-written guide scenes
    SCENE_CARRIER_MAP = [
        (["schild","aufschrift","türschild","eingang","ausgang"], 0),
        (["aushang","prospekt","tafel","notiz","anzeige"], 1),
        (["fahrplan","reiseplan","reiseroute"], 2),
        (["formular","fragebogen","anmeldeformular","liste","tabelle","fragebogen"], 3),
        (["informationstafel","hotel","rezeption","informationstext","info"], 4),
        (["durchsage","ansage","aufruf","gesprochen","langsam","hör"], 5),
        (["gespräch","sprechen","frage","kolleg","bekannt","freund","party","kurs","treffen","restaurant","geschäft"], 6),
        (["anleitung","anweisung","gebäude","bedienung","instruktion"], 7),
    ]
    for kid, guide in hand_guides.items():
        scene = guide.get("scene", "").lower()
        kb = kbs_dict.get(kid, {})
        cat = kb.get("category", "")
        # determine operation column from category
        if "Rezeption" in cat:   op_col = 0  # verstehen
        elif "Produktion" in cat: op_col = 2 if "schriftlich" in cat else 1  # aufschreiben or sagen
        elif "Interaktion" in cat: op_col = 1  # sagen/sprechen
        elif "Sprachmittlung" in cat: op_col = 3  # weitergeben
        else: continue
        for keywords, row in SCENE_CARRIER_MAP:
            if any(kw in scene for kw in keywords):
                matrix[(row, op_col)].add(kid)
                break

    # --- SVG ---
    MX, MY = 20, 70
    ROW_H = 50
    COL_W = 170
    LABEL_W = 160
    LABEL_X = MX
    GRID_X = MX + LABEL_W + 4

    svg_w = GRID_X + COL_W * 4 + 20
    svg_h = MY + ROW_H * (len(CARRIERS) + 1) + 50
    svg_w_int = int(svg_w)
    svg_h_int = int(svg_h)

    svg = []
    svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {svg_w_int} {svg_h_int}" font-family="-apple-system,Segoe UI,sans-serif">')
    svg.append(f'<rect width="{svg_w_int}" height="{svg_h_int}" fill="#fff"/>')
    svg.append(f'<text x="{int(svg_w)//2}" y="28" text-anchor="middle" font-size="15" font-weight="700" fill="#1a2227">Carrier × Operation Matrix</text>')
    svg.append(f'<text x="{int(svg_w)//2}" y="48" text-anchor="middle" font-size="10" fill="#888">What object do you encounter? What can you do with it?</text>')

    # Column headers
    for ci, (op_de, op_en, col_bg) in enumerate(OPERATIONS):
        x = GRID_X + ci * COL_W
        svg.append(f'<rect x="{x}" y="{MY}" width="{COL_W}" height="28" rx="0" fill="{col_bg}" stroke="#ccc" stroke-width="1"/>')
        svg.append(f'<text x="{x+COL_W//2}" y="{MY+12}" text-anchor="middle" font-size="9" font-weight="700" fill="#333">{_esc(op_de)}</text>')
        svg.append(f'<text x="{x+COL_W//2}" y="{MY+23}" text-anchor="middle" font-size="8" fill="#666">{_esc(op_en)}</text>')

    # Rows
    for ri, (carrier_de, carrier_en, row_bg, row_stroke) in enumerate(CARRIERS):
        y = MY + 28 + ri * ROW_H
        # Row label
        svg.append(f'<rect x="{LABEL_X}" y="{y}" width="{LABEL_W}" height="{ROW_H}" rx="0" fill="{row_bg}" stroke="{row_stroke}" stroke-width="1.5"/>')
        svg.append(f'<text x="{LABEL_X+8}" y="{y+18}" font-size="10" font-weight="700" fill="#333">{_esc(carrier_de)}</text>')
        svg.append(f'<text x="{LABEL_X+8}" y="{y+34}" font-size="8" fill="#666">{_esc(carrier_en)}</text>')
        # channel icon
        ch = carrier_channel.get(carrier_de.split(" / ")[0], "") or carrier_channel.get(carrier_de, "")
        icon = "👁" if ch == "written" else ("👂" if ch == "spoken" else "")
        if icon:
            svg.append(f'<text x="{LABEL_X+LABEL_W-22}" y="{y+18}" font-size="11">{icon}</text>')

    # Grid cells
    for ri in range(len(CARRIERS)):
        for ci in range(len(OPERATIONS)):
            y = MY + 28 + ri * ROW_H
            x = GRID_X + ci * COL_W
            cell_bg = "#fff" if (ri + ci) % 2 == 0 else "#fafafa"
            svg.append(f'<rect x="{x}" y="{y}" width="{COL_W}" height="{ROW_H}" rx="0" fill="{cell_bg}" stroke="#e0e0e0" stroke-width="0.5"/>')
            kb_set = matrix.get((ri, ci), set())
            if kb_set:
                kbs_sorted = sorted(kb_set)[:8]
                ids_text = " ".join(f"{kid}{_hs(kid)}" for kid in kbs_sorted)
                svg.append(f'<text x="{x+6}" y="{y+14}" font-size="8" fill="#1a2227" font-weight="600">{_esc(ids_text)}</text>')
                # count if more
                if len(kb_set) > 8:
                    svg.append(f'<text x="{x+6}" y="{y+30}" font-size="7" fill="#999">+{len(kb_set)-8} more</text>')
                # clickable
                kid_list = ",".join(sorted(kb_set))
                svg.append(f'<rect x="{x}" y="{y}" width="{COL_W}" height="{ROW_H}" rx="0" fill="transparent" cursor="pointer" onclick="window.location.href=\'/guides?q={kid_list}\'"/>')
                svg.append(f'<title>{_esc(f"{CARRIERS[ri][0]} × {OPERATIONS[ci][0]}: {len(kb_set)} KBs")}</title>')

    svg.append('</svg>')

    # --- HTML wrapper ---
    nav = [
        '<a href="/" class="nv">Classroom</a>',
        '<a href="/graph" class="nv active">Graph</a>',
        '<a href="/graph?v=matrix" class="nv" id="tog">Matrix view</a>',
        '<a href="/guides" class="nv">Guides</a>',
        '<a href="/quiz" class="nv">Quiz</a>',
        '<a href="/word" class="nv">Word→KB</a>',
    ]
    parts = [
        '<!DOCTYPE html><html><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>KB Graph — Matrix</title>',
        '<style>',
        '*{box-sizing:border-box} body{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f4f6f7;color:#1a2227}',
        '.top{position:sticky;top:0;z-index:10;background:#fff;border-bottom:1px solid #d9e0e3;padding:12px 18px}',
        '.top h1{margin:0;font-size:18px;color:#0b5e55}.top p{margin:4px 0 0;color:#5c6b74;font-size:13px}',
        '.nav-bar{display:flex;gap:10px;flex-wrap:wrap;margin-top:8px}',
        '.nv{color:#0b5e55;text-decoration:none;font-size:13px;padding:3px 8px;border-radius:4px;border:1px solid #c8d6db}',
        '.nv.active,.nv:hover{background:#0b5e55;color:#fff;border-color:#0b5e55}',
        '.page{padding:14px 18px}',
        '</style></head><body>',
        '<div class="top"><h1>KB Matrix View</h1>',
        '<p>Rows = carriers (physical objects you encounter). Columns = operations (what you can do). '
        '<span style="background:#fff3e0;padding:1px 6px;border-radius:3px;border:1px solid #f5d66e;font-size:11px">Interaction</span> '
        '<span style="background:#e3f2fd;padding:1px 6px;border-radius:3px;border:1px solid #90caf9;font-size:11px">Reception</span> '
        '<span style="background:#fff8e1;padding:1px 6px;border-radius:3px;border:1px solid #ffcc80;font-size:11px">Production</span> '
        '<span style="background:#fbe9e7;padding:1px 6px;border-radius:3px;border:1px solid #ff8a65;font-size:11px">Mediation</span> '
        '<a href="/graph" style="color:#0b5e55">→ cluster view</a></p>',
        '<div class="nav-bar">' + "".join(nav[:3]) + '<a href="/guides" class="nv">Guides</a><a href="/quiz" class="nv">Quiz</a><a href="/word" class="nv">Word→KB</a></div></div>',
        '<div class="page">',
        "".join(svg),
        '</div></body></html>',
    ]
    return "".join(parts)


def _graph_original_html():
    """Serve the original hand-crafted KB cluster SVG."""
    import os
    svg_path = os.path.join(os.path.dirname(__file__), "kb_graph.svg")
    with open(svg_path, "r") as f:
        svg_content = f.read()

    nav = [
        '<a href="/" class="nv">Classroom</a>',
        '<a href="/graph" class="nv">Graph</a>',
        '<a href="/graph?v=original" class="nv active">Original</a>',
        '<a href="/graph?v=matrix" class="nv">Matrix</a>',
        '<a href="/guides" class="nv">Guides</a>',
        '<a href="/quiz" class="nv">Quiz</a>',
        '<a href="/word" class="nv">Word→KB</a>',
    ]
    parts = [
        '<!DOCTYPE html><html><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>KB Graph — Original</title>',
        '<style>',
        '*{box-sizing:border-box} body{margin:0;font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f4f6f7;color:#1a2227}',
        '.top{position:sticky;top:0;z-index:10;background:#fff;border-bottom:1px solid #d9e0e3;padding:12px 18px}',
        '.top h1{margin:0;font-size:18px;color:#0b5e55}.top p{margin:4px 0 0;color:#5c6b74;font-size:13px}',
        '.nav-bar{display:flex;gap:10px;flex-wrap:wrap;margin-top:8px}',
        '.nv{color:#0b5e55;text-decoration:none;font-size:13px;padding:3px 8px;border-radius:4px;border:1px solid #c8d6db}',
        '.nv.active,.nv:hover{background:#0b5e55;color:#fff;border-color:#0b5e55}',
        '.page{padding:14px 18px}',
        '.graph-container{max-width:1440px;margin:0 auto;background:#f4f6f7;border-radius:8px;overflow:hidden;border:1px solid #dde4e8}',
        '</style></head><body>',
        '<div class="top"><h1>KB Compressed Graph — Original</h1>',
        '<p>Hand-crafted cluster map with bezier bridges, shadowed boxes, and colored edge types. <a href="/graph" style="color:#0b5e55">→ generated view</a></p>',
        '<div class="nav-bar">' + "".join(nav) + '</div></div>',
        '<div class="page"><div class="graph-container">',
        svg_content,
        '</div></div></body></html>',
    ]
    return "".join(parts)


def _prompt_text(query_string):
    """Generate a copy-paste prompt for DeepSeek based on exam module and KB cluster."""
    query = parse_qs(query_string or "")
    module = (query.get("m") or ["lesen"])[0].strip()
    teil = (query.get("t") or ["1"])[0].strip()
    kbid = (query.get("kb") or [""])[0].strip().upper()

    kbs_dict = {k["id"]: k for k in runner.all_kanns}
    wf = runner.wortfelder
    grammatik = runner.grammatik
    red = runner.kann_reductions_cfg
    overrides = red.get("manual_overrides", {})

    def _grammar_txt():
        lines = []
        for cat, rules in grammatik.items():
            lines.append(f"{cat}:")
            for r in rules:
                lines.append(f"  - {r}")
        return "\n".join(lines)

    def _vocab_txt(fields, max_items=10):
        lines = []
        for f in fields:
            words = wf.get(f, [])[:max_items]
            lines.append(f"{f}: {', '.join(words)}")
        return "\n".join(lines)

    # Per-KB prompt
    if kbid and kbid in kbs_dict:
        kb = kbs_dict[kbid]
        ov = overrides.get(kbid, {})
        near = ov.get("near_kbs", [])
        examples = ov.get("examples", [])
        ex_txt = "\n".join(f"  - {e}" for e in examples[:6])

        return f"""You are a telc Deutsch A1 tutor. Help me master this one Kannbeschreibung from {kb['category']}.

KB {kb['id']}: {kb['kann'][:400]}
Level: {kb.get('level','')}

Carrier: {ov.get('carrier','(not specified)')}
Operation: {ov.get('operation','(not specified)')}
Output: {ov.get('output','(not specified)')}

Examples from this KB:
{ex_txt}

Near KBs (can be confused with): {', '.join(near) if near else '(none)'}

A1 Grammar constraints:
{_grammar_txt()}

Available vocabulary:
{_vocab_txt(['person','familie','beruf','einkaufen','lebensmittel','getraenke','restaurant','wohnen','moebel','verkehr','zeit','freizeit','zahlen'])}

Your task: Generate 8 short practice questions in the telc A1 exam format that test EXACTLY this KB. Make distractors that test whether the learner confuses this KB with the near KBs.

Include answer key.
"""

    # Module prompts
    prompts = {
        "lesen_1": ("Lesen Teil 1 — Kurze Texte (Richtig/Falsch)",
            "Two short texts (notes, emails, invitations). Richtig/Falsch statements. FALSE because of ONE word like vielleicht, leider, aber, nicht, noch nicht, schon.",
            ["person","familie","wohnen","verkehr","zeit","freizeit"],
            ["K111","K112","K113","K114","K115"]),
        "lesen_2": ("Lesen Teil 2 — Kleinanzeigen (a oder b)",
            "10 ads, 5 situations, pick a or b. Ads: Wohnungen, Jobs, Autos, Möbel, Kurse, Reisen.",
            ["wohnen","einkaufen","freizeit","verkehr","beruf","restaurant"],
            ["K087","K092","K095"]),
        "lesen_3": ("Lesen Teil 3 — Schilder und Aushänge (Richtig/Falsch)",
            "5 short signs. One statement each. Signs: Heute geschlossen, Aufzug außer Betrieb, Parken verboten, etc.",
            ["verkehr","einkaufen","wohnen","restaurant"],
            ["K100","K101","K102","K103","K104"]),
        "horen_1": ("Hören Teil 1 — Kurze Gespräche (a/b/c)",
            "6 short everyday conversations. One question each with 3 options. Provide the spoken text, question, options, answer.",
            ["person","familie","beruf","einkaufen","restaurant","verkehr","zeit","freizeit"],
            ["K060","K068","K069"]),
        "horen_2": ("Hören Teil 2 — Durchsagen (Richtig/Falsch)",
            "4 public announcements. Heard ONCE. Provide the spoken announcement text, statement, Richtig/Falsch.",
            ["verkehr","zeit","einkaufen","zahlen"],
            ["K063","K064","K074"]),
        "horen_3": ("Hören Teil 3 — Telefonansagen (a/b/c)",
            "5 answering machine messages. One question each. Wer ruft an? Warum? Was soll der Hörer tun?",
            ["person","beruf","zeit","wohnen","restaurant"],
            ["K076","K079"]),
        "sprechen_1": ("Sprechen Teil 1 — Sich vorstellen",
            "Prompt me: give me 4 Stichwörter. I introduce myself. Score me 1-3 per item: Name/Alter/Herkunft/Wohnort/Beruf/Hobby/Buchstabieren/Nummer.",
            ["person","familie","beruf","wohnen","freizeit"],
            ["K121","K122","K014","K015","K016","K017"]),
        "sprechen_2": ("Sprechen Teil 2 — Fragen und Antworten",
            "Topics: Einkaufen, Essen/Trinken, Freizeit/Wochenende. Give me 8 Handlungskarten with model questions and answers.",
            ["einkaufen","lebensmittel","getraenke","restaurant","freizeit","zeit"],
            ["K022","K023","K024","K025"]),
        "sprechen_3": ("Sprechen Teil 3 — Bitten formulieren",
            "Give me 8 Bildkarten (one word each). I make a polite request. You show model Bitte + Antwort(+/-).",
            ["einkaufen","restaurant","wohnen","lebensmittel","getraenke"],
            ["K026","K027","K028","K029"]),
        "schreiben_1": ("Schreiben Teil 1 — Formular ausfüllen",
            "A situation text + a form with 5 blanks. I fill them in. Score 1 point per correct field.",
            ["person","wohnen","verkehr","zeit"],
            ["K137","K138"]),
        "schreiben_2": ("Schreiben Teil 2 — Kurzmitteilung (~30 Wörter)",
            "A situation + 3 Inhaltspunkte. I write ~30 words. Score me: 3 per Inhaltspunkt + 1 for Anrede/Gruß. Total 10.",
            ["person","familie","wohnen","verkehr","zeit","freizeit","beruf"],
            ["K149","K150","K151","K152"]),
    }

    key = f"{module}_{teil}"
    if key not in prompts:
        keys = "\n".join(f"  /prompt?m={k.split('_')[0]}&t={k.split('_')[1]} — {v[0]}" for k,v in sorted(prompts.items()))
        return f"Unknown {module}/{teil}.\n\nAvailable:\n{keys}\n\nOr use /prompt?kb=K100 for a single KB."

    title, desc, fields, kb_ids = prompts[key]
    kb_list = [kbs_dict[kid] for kid in kb_ids if kid in kbs_dict]
    kb_txt = "\n".join(f"  {k['id']}: {k['kann'][:150]}..." for k in kb_list)

    # Phone-optimized: about 1500-2500 chars fits on one screen
    phone_vocab = _vocab_txt(fields, max_items=8)

    return f"""You are a telc Deutsch A1 tutor on mobile. Keep responses tight.

{title}
{desc}

TARGET: {', '.join(kb_ids)}

VOCABULARY — A1 only:
{phone_vocab}

GRAMMAR: Present tense. Modal verbs (können, müssen, möchten). W-Fragen. Negation with nicht/kein. Prepositions (in, aus, nach, zu, bei, an, auf, mit, von, bis). No subjunctive. No passive. Max 10 words per sentence.

Generate now. Include answer key.
"""


# ---------------------------------------------------------------------------
# WSGI app
# ---------------------------------------------------------------------------
def app(environ, start_response):
    """Serve the runner UI without starting runner.py's built-in HTTP server."""
    _ensure_loaded()
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO", "/")

    if method in {"GET", "HEAD"} and path in {"/healthz", "/api/status"}:
        if method == "HEAD":
            return _response(start_response, "200 OK", "")
        return _response(start_response, "200 OK", "ok")

    if method in {"GET", "HEAD"} and path == "/guides":
        if method == "HEAD":
            return _response(start_response, "200 OK", "", content_type="text/html; charset=utf-8")
        return _response(start_response, "200 OK", _guides_html(environ.get("QUERY_STRING", "")), content_type="text/html; charset=utf-8")

    if method in {"GET", "HEAD"} and path == "/quiz":
        if method == "HEAD":
            return _response(start_response, "200 OK", "", content_type="text/html; charset=utf-8")
        return _response(start_response, "200 OK", _quiz_html(environ.get("QUERY_STRING", "")), content_type="text/html; charset=utf-8")

    if method in {"GET", "HEAD"} and path == "/word":
        if method == "HEAD":
            return _response(start_response, "200 OK", "", content_type="text/html; charset=utf-8")
        return _response(start_response, "200 OK", _word_html(environ.get("QUERY_STRING", "")), content_type="text/html; charset=utf-8")

    if method in {"GET", "HEAD"} and path == "/drill":
        if method == "HEAD":
            return _response(start_response, "200 OK", "", content_type="text/html; charset=utf-8")
        return _response(start_response, "200 OK", _drill_html(environ.get("QUERY_STRING", "")), content_type="text/html; charset=utf-8")

    if method in {"GET", "HEAD"} and path == "/graph":
        if method == "HEAD":
            return _response(start_response, "200 OK", "", content_type="text/html; charset=utf-8")
        return _response(start_response, "200 OK", _graph_html(environ.get("QUERY_STRING", "")), content_type="text/html; charset=utf-8")

    if method in {"GET", "HEAD"} and path == "/prompt":
        if method == "HEAD":
            return _response(start_response, "200 OK", "", content_type="text/plain; charset=utf-8")
        return _response(start_response, "200 OK", _prompt_text(environ.get("QUERY_STRING", "")), content_type="text/plain; charset=utf-8")

    if method == "POST" and path == "/run":
        try:
            length = int(environ.get("CONTENT_LENGTH") or "0")
        except ValueError:
            length = 0
        body = environ["wsgi.input"].read(length).decode("utf-8")
        target = parse_qs(body).get("target", [""])[0]
        try:
            _, message = runner.start_single_day_run(target)
            runner.live["status"] = message
        except Exception as exc:
            runner.live["status"] = f"Could not start run: {exc}"
        return _response(start_response, "303 See Other", "", headers=[("Location", "/")])

    if method == "HEAD":
        return _response(start_response, "200 OK", "", content_type="text/html; charset=utf-8")

    if method == "GET":
        return _response(start_response, "200 OK", _render_windowed_html(environ.get("QUERY_STRING", "")), content_type="text/html; charset=utf-8")

    return _response(start_response, "404 Not Found", "not found")
