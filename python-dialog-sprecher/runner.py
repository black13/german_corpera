"""
runner.py v2 — Classroom model. One Kann per day, configured student group.
Disposable. Reads JSON, calls APIs, writes JSON, serves HTTP.
Contains ZERO rules about German. All meaning is in the JSON files.
"""
import json, os, re, sys, threading, time, traceback, functools
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from openai import OpenAI

BASE = Path(__file__).parent

# ── JSON helpers ───────────────────────────────────────────────────
def load(path):
    with open(BASE / path) as f:
        return json.load(f)

def load_optional(path, default):
    p = BASE / path
    if not p.exists():
        return default
    with open(p) as f:
        return json.load(f)

def save(path, data):
    p = BASE / path
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


runtime_cfg = load("config/runtime.json")

# ── API clients ────────────────────────────────────────────────────
# Well-known providers: name → (base_url, env var for API key)
_PROVIDERS = {
    "openai":   (None, "OPENAI_API_KEY"),                       # default SDK url
    "deepseek": ("https://api.deepseek.com", "DEEPSEEK_API_KEY"),
    "together": ("https://api.together.xyz/v1", "TOGETHER_API_KEY"),
    "groq":     ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "ollama":   ("http://localhost:11434/v1", None),             # no key needed
}

_client_cache = {}
_DEEPSEEK_PRICING_USD_PER_MILLION = {
    "deepseek-chat": {
        "input_cache_hit": 0.07,
        "input_cache_miss": 0.27,
        "output": 1.10,
    },
    "deepseek-reasoner": {
        "input_cache_hit": 0.14,
        "input_cache_miss": 0.55,
        "output": 2.19,
    },
}

def _get_client(base_url=None, api_key_env=None):
    """Return a cached OpenAI-compatible client for any endpoint."""
    cache_key = (base_url or "default", api_key_env or "")
    if cache_key not in _client_cache:
        kwargs = {}
        if base_url:
            kwargs["base_url"] = base_url
        if api_key_env:
            kwargs["api_key"] = os.environ.get(api_key_env, "")
        elif base_url and not api_key_env:
            # endpoints like ollama / local vLLM don't need a key
            kwargs["api_key"] = "none"
        _client_cache[cache_key] = OpenAI(**kwargs)
    return _client_cache[cache_key]


def _usage_to_dict(usage):
    if not usage:
        return {}
    prompt_tokens = getattr(usage, "prompt_tokens", None)
    completion_tokens = getattr(usage, "completion_tokens", None)
    total_tokens = getattr(usage, "total_tokens", None)
    details = getattr(usage, "prompt_tokens_details", None)
    cached_tokens = getattr(details, "cached_tokens", None) if details else None
    payload = {
        "prompt_tokens": prompt_tokens or 0,
        "completion_tokens": completion_tokens or 0,
        "total_tokens": total_tokens or ((prompt_tokens or 0) + (completion_tokens or 0)),
    }
    if cached_tokens is not None:
        payload["cached_tokens"] = cached_tokens
        payload["uncached_prompt_tokens"] = max(payload["prompt_tokens"] - cached_tokens, 0)
    return payload


def _estimate_cost_usd(api, model, usage_dict):
    if api != "deepseek" or not usage_dict:
        return None
    pricing = _DEEPSEEK_PRICING_USD_PER_MILLION.get(model)
    if not pricing:
        return None
    prompt_tokens = usage_dict.get("prompt_tokens", 0)
    cached_tokens = usage_dict.get("cached_tokens", 0)
    uncached_prompt_tokens = usage_dict.get("uncached_prompt_tokens", max(prompt_tokens - cached_tokens, 0))
    completion_tokens = usage_dict.get("completion_tokens", 0)
    estimate = (
        (cached_tokens / 1_000_000) * pricing["input_cache_hit"] +
        (uncached_prompt_tokens / 1_000_000) * pricing["input_cache_miss"] +
        (completion_tokens / 1_000_000) * pricing["output"]
    )
    return round(estimate, 6)


def _jsonify_response(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _jsonify_response(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonify_response(v) for v in obj]
    if hasattr(obj, "model_dump"):
        try:
            return _jsonify_response(obj.model_dump(mode="json"))
        except TypeError:
            return _jsonify_response(obj.model_dump())
    if hasattr(obj, "to_dict"):
        try:
            return _jsonify_response(obj.to_dict())
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        return {
            str(k): _jsonify_response(v)
            for k, v in vars(obj).items()
            if not str(k).startswith("_")
        }
    return str(obj)


def _build_call_meta(step_name, api, model, usage_dict, raw_text=None, response_json=None):
    meta = {
        "step": step_name,
        "api": api,
        "model": model,
    }
    if raw_text is not None:
        meta["raw_text"] = raw_text
    if usage_dict:
        meta["usage"] = usage_dict
    if response_json is not None:
        meta["response_json"] = response_json
    estimated_cost = _estimate_cost_usd(api, model, usage_dict)
    if estimated_cost is not None:
        meta["estimated_cost_usd"] = estimated_cost
    return meta

def chat(api, model, messages, temperature=0.8, max_tokens=500,
         base_url=None, api_key_env=None, step_name=None, return_meta=False,
         request_timeout=None):
    """Call any OpenAI-compatible endpoint.

    Resolution order for base_url / api_key_env:
      1. Explicit base_url / api_key_env args (from config JSON)
      2. Well-known provider lookup via `api` name
      3. Falls back to default OpenAI client
    """
    if not base_url and api in _PROVIDERS:
        base_url, default_key_env = _PROVIDERS[api]
        if not api_key_env:
            api_key_env = default_key_env
    client = _get_client(base_url, api_key_env)
    create_kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    timeout = request_timeout if request_timeout is not None else runtime_cfg.get("request_timeout", 180)
    if timeout:
        create_kwargs["timeout"] = timeout
    r = client.chat.completions.create(**create_kwargs)
    content = r.choices[0].message.content or ""
    usage_dict = _usage_to_dict(getattr(r, "usage", None))
    response_json = _jsonify_response(r)
    if not return_meta:
        return content
    return {
        "content": content,
        "meta": _build_call_meta(
            step_name or "chat",
            api,
            model,
            usage_dict,
            raw_text=content,
            response_json=response_json,
        ),
    }


def chat_from_config(step_name, messages, return_meta=False):
    cfg = runtime_cfg["models"][step_name]
    return chat(
        cfg.get("api", "openai"),
        cfg["model"],
        messages,
        temperature=cfg.get("temperature", 0.8),
        max_tokens=cfg.get("max_tokens", 500),
        base_url=cfg.get("base_url"),
        api_key_env=cfg.get("api_key_env"),
        step_name=step_name,
        return_meta=return_meta,
        request_timeout=cfg.get("request_timeout"),
    )

def parse_json(raw):
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
    if s.endswith("```"):
        s = s[:-3]
    return json.loads(s.strip())


def clean_spoken_text(text):
    raw = re.sub(r"\r\n?", "\n", str(text or "")).strip()
    if not raw:
        return ""
    cleaned_lines = []
    for line in raw.split("\n"):
        line = re.sub(r"^\s*(?:\[[^\]]+\]|\([^)]+\))\s*", "", line).strip()
        if line:
            cleaned_lines.append(line)
    cleaned = "\n\n".join(cleaned_lines).strip()
    return cleaned or raw


def make_billing_bucket():
    return {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cached_tokens": 0,
        "uncached_prompt_tokens": 0,
        "estimated_cost_usd": 0.0,
        "by_step": {},
    }


def add_call_meta_to_billing(billing_bucket, call_meta):
    usage = call_meta.get("usage", {})
    step = call_meta.get("step", "chat")
    step_bucket = billing_bucket["by_step"].setdefault(step, {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cached_tokens": 0,
        "uncached_prompt_tokens": 0,
        "estimated_cost_usd": 0.0,
        "models": {},
    })
    model_key = f'{call_meta.get("api", "?")}:{call_meta.get("model", "?")}'
    model_bucket = step_bucket["models"].setdefault(model_key, {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cached_tokens": 0,
        "uncached_prompt_tokens": 0,
        "estimated_cost_usd": 0.0,
    })
    for bucket in (billing_bucket, step_bucket, model_bucket):
        bucket["calls"] += 1
        bucket["prompt_tokens"] += usage.get("prompt_tokens", 0)
        bucket["completion_tokens"] += usage.get("completion_tokens", 0)
        bucket["total_tokens"] += usage.get("total_tokens", 0)
        bucket["cached_tokens"] += usage.get("cached_tokens", 0)
        bucket["uncached_prompt_tokens"] += usage.get("uncached_prompt_tokens", 0)
        bucket["estimated_cost_usd"] = round(
            bucket["estimated_cost_usd"] + call_meta.get("estimated_cost_usd", 0.0),
            6,
        )


def _norm_text(value):
    text = re.sub(r"\s+", " ", str(value or "").strip())
    lowered = text.lower()
    lowered = re.sub(r"[^\wäöüß]+", " ", lowered, flags=re.UNICODE)
    return re.sub(r"\s+", " ", lowered).strip()


def _dedupe_strings(values, limit=None):
    seen = set()
    result = []
    for value in values:
        text = re.sub(r"\s+", " ", str(value or "").strip())
        if not text:
            continue
        key = _norm_text(text)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(text)
        if limit and len(result) >= limit:
            break
    return result


def _dedupe_learning_items(items, field):
    merged = {}
    for idx, item in enumerate(items or []):
        raw = re.sub(r"\s+", " ", str(item.get(field, "")).strip())
        if not raw:
            continue
        key = _norm_text(raw)
        if not key:
            continue
        entry = merged.setdefault(key, {
            field: raw,
            "stable": bool(item.get("stable")),
            "mentions": 0,
            "last_index": idx,
        })
        entry[field] = raw
        entry["stable"] = bool(item.get("stable"))
        entry["mentions"] += 1
        entry["last_index"] = idx
    ordered = sorted(
        merged.values(),
        key=lambda item: (not item["stable"], -item["mentions"], -item["last_index"], item[field].lower()),
    )
    return [{field: item[field], "stable": item["stable"], "mentions": item["mentions"]} for item in ordered]


def _take_learning_bucket(items, field, stable, limit):
    return [item for item in items if item.get("stable") is stable][:limit]


def _format_learning_bucket(title, items, field):
    if not items:
        return ""
    lines = [f"{title}:"]
    for item in items:
        label = item[field]
        mentions = item.get("mentions", 1)
        if mentions > 1:
            label += f" (seen {mentions}x)"
        lines.append(f"  - {label}")
    return "\n".join(lines)


def _sample_wortfeld_examples(targets, limit_per_field=6):
    samples = []
    for target in targets or []:
        if target in wortfelder:
            samples.append({
                "field": target,
                "examples": wortfelder[target][:limit_per_field],
            })
    return samples


def _needle_matches(text, needle):
    norm_text = _norm_text(text)
    norm_needle = _norm_text(needle)
    if not norm_text or not norm_needle:
        return False
    tokens = norm_text.split()
    needle_tokens = norm_needle.split()
    if not needle_tokens:
        return False
    if len(needle_tokens) == 1:
        return any(token.startswith(needle_tokens[0]) for token in tokens)
    width = len(needle_tokens)
    for idx in range(len(tokens) - width + 1):
        window = tokens[idx: idx + width]
        if all(window[pos].startswith(needle_tokens[pos]) for pos in range(width)):
            return True
    return False


def _derive_kann_relationships(kann, limit=4):
    relationships = []
    kann_id = kann["id"]
    category = kann.get("category", "")
    for idx, rel in enumerate(kann_relationship_cfg.get("relationship_groups", [])):
        score = 0
        if kann_id in rel.get("kann_ids", []):
            score = max(score, 4)
        if kann_id in rel.get("bridge_to_kann_ids", []):
            score = max(score, 3)
        if any(_needle_matches(kann["kann"], needle) for needle in rel.get("match_any", [])):
            score = max(score, 2)
        if category in rel.get("scope_categories", []):
            score = max(score, 1)
        if not score:
            continue
        relationships.append((
            -score,
            idx,
            {
                "id": rel.get("id", ""),
                "name": rel.get("name", ""),
                "kann_ids": rel.get("kann_ids", []),
                "bridge_to_kann_ids": rel.get("bridge_to_kann_ids", []),
                "summary": rel.get("summary", ""),
                "teacher_guidance": rel.get("teacher_guidance", ""),
                "grader_guidance": rel.get("grader_guidance", ""),
            },
        ))
    relationships.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in relationships[:limit]]


def _derive_syllabus_branches(kann, focus, limit=3):
    branches = []
    kann_id = kann["id"]
    category = kann.get("category", "")
    rel_ids = {rel.get("id", "") for rel in focus.get("global_relationships", [])}
    bridge_ids = {
        bridge_id
        for rel in focus.get("global_relationships", [])
        for bridge_id in rel.get("bridge_to_kann_ids", [])
    }
    wortfeld_targets = set(focus.get("wortfeld_targets", []))
    for idx, branch in enumerate(a1_syllabus_cfg.get("branches", [])):
        score = 0
        if kann_id in branch.get("kann_ids", []):
            score = max(score, 5)
        if kann_id in branch.get("bridge_to_kann_ids", []):
            score = max(score, 4)
        if bridge_ids.intersection(branch.get("bridge_to_kann_ids", [])):
            score = max(score, 3)
        if rel_ids.intersection(branch.get("relationship_ids", [])):
            score = max(score, 3)
        if wortfeld_targets.intersection(branch.get("wortfeld_targets", [])):
            score = max(score, 2)
        if any(_needle_matches(kann["kann"], needle) for needle in branch.get("match_any", [])):
            score = max(score, 4)
        if category in branch.get("scope_categories", []):
            score = max(score, 1)
        if not score:
            continue
        branches.append((
            -score,
            idx,
            {
                "id": branch.get("id", ""),
                "name": branch.get("name", ""),
                "summary": branch.get("summary", ""),
                "teacher_language": branch.get("teacher_language", ""),
                "relationship_ids": branch.get("relationship_ids", []),
                "fruit_clusters": branch.get("fruit_clusters", []),
            },
        ))
    branches.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in branches[:limit]]


def _derive_kann_quick_guide(kann, focus):
    guide = dict(kann_quick_guides_cfg.get("guides", {}).get(kann["id"], {}) or {})
    guide["kb_de"] = guide.get("kb_de") or kann["kann"]

    if not guide.get("kb_de_simple"):
        guide["kb_de_simple"] = "Ich mache diese Aufgabe in einer einfachen Alltagsszene."
    if not guide.get("kb_en_simple"):
        guide["kb_en_simple"] = "I practice this can-do statement in one simple everyday scene."
    if not guide.get("scene"):
        guide["scene"] = kann.get("category", "Alltagsszene")

    speech_acts = focus.get("speech_acts", [])
    if not guide.get("task_shape"):
        guide["task_shape"] = [
            "Die Situation erkennen.",
            "Die passende Sprachhandlung wählen.",
            "Einen kurzen A1-Satz sagen oder schreiben.",
        ]
    if not guide.get("core_phrases"):
        guide["core_phrases"] = speech_acts[:4]

    if not guide.get("word_bank"):
        words = []
        for sample in focus.get("wortfeld_samples", []):
            words.extend(sample.get("examples", []))
        guide["word_bank"] = _dedupe_strings(words, limit=12)
    if not guide.get("grammar_tools"):
        guide["grammar_tools"] = focus.get("grammar_targets", [])[:6]
    if not guide.get("related_kbs"):
        related = []
        for rel in focus.get("global_relationships", []):
            related.extend(rel.get("kann_ids", []))
            related.extend(rel.get("bridge_to_kann_ids", []))
        guide["related_kbs"] = [kid for kid in _dedupe_strings(related, limit=10) if kid != kann["id"]]

    for key in ("roles", "task_shape", "core_phrases", "word_bank", "grammar_tools", "related_kbs"):
        guide[key] = _dedupe_strings(guide.get(key, []), limit=12)
    return guide


def derive_kann_focus(kann):
    focus = {
        "kann_id": kann["id"],
        "kann_text": kann["kann"],
        "category": kann.get("category", ""),
        "grammar_targets": [],
        "wortfeld_targets": [],
        "speech_acts": [],
        "example_bank": [],
        "global_relationships": [],
        "syllabus_branches": [],
        "quick_guide": {},
    }

    category_defaults = kann_map_cfg.get("category_defaults", {})
    defaults = category_defaults.get(kann.get("category", ""), {})
    for key in ("grammar_targets", "wortfeld_targets", "speech_acts", "example_bank"):
        focus[key].extend(defaults.get(key, []))

    for rule in kann_map_cfg.get("keyword_rules", []):
        needles = rule.get("match_any", [])
        if needles and not any(_needle_matches(kann["kann"], needle) for needle in needles):
            continue
        for key in ("grammar_targets", "wortfeld_targets", "speech_acts", "example_bank"):
            focus[key].extend(rule.get(key, []))

    manual = kann_map_cfg.get("manual_overrides", {}).get(kann["id"], {})
    for key in ("grammar_targets", "wortfeld_targets", "speech_acts", "example_bank"):
        focus[key].extend(manual.get(key, []))

    focus["grammar_targets"] = _dedupe_strings(focus["grammar_targets"], limit=8)
    focus["wortfeld_targets"] = _dedupe_strings(focus["wortfeld_targets"], limit=6)
    focus["speech_acts"] = _dedupe_strings(focus["speech_acts"], limit=6)
    focus["global_relationships"] = _derive_kann_relationships(kann)
    focus["syllabus_branches"] = _derive_syllabus_branches(kann, focus)

    examples = []
    for example in focus["example_bank"]:
        if isinstance(example, str):
            examples.append({"text": example, "source": "seed"})
        elif isinstance(example, dict):
            text = re.sub(r"\s+", " ", str(example.get("text", "")).strip())
            if text:
                examples.append({
                    "text": text,
                    "source": str(example.get("source", "seed")).strip() or "seed",
                })
    seen_examples = set()
    deduped_examples = []
    for example in examples:
        key = _norm_text(example["text"])
        if not key or key in seen_examples:
            continue
        seen_examples.add(key)
        deduped_examples.append(example)
        if len(deduped_examples) >= 4:
            break
    focus["example_bank"] = deduped_examples
    focus["wortfeld_samples"] = _sample_wortfeld_examples(focus["wortfeld_targets"])
    focus["quick_guide"] = _derive_kann_quick_guide(kann, focus)
    return focus


def build_student_summary(student_id, learned_state, progress_entries):
    vocab_items = _dedupe_learning_items(learned_state.get("vocabulary_acquired", []), "word")
    grammar_items = _dedupe_learning_items(learned_state.get("grammar_acquired", []), "rule")
    recent_attempts = []
    for kann_id, info in learned_state.get("kannbeschreibungen_attempted", {}).items():
        if not isinstance(info, dict):
            continue
        recent_attempts.append({
            "kann_id": kann_id,
            "day": info.get("day", 0),
            "result": info.get("result", ""),
            "kann_text": KANN_BY_ID.get(kann_id, {}).get("kann", ""),
        })
    recent_attempts.sort(key=lambda item: item.get("day", 0), reverse=True)

    recent_highlights = []
    for entry in reversed(progress_entries[-3:]):
        highlight = re.sub(r"\s+", " ", str(entry.get("session_highlight", "")).strip())
        if highlight:
            recent_highlights.append(highlight)

    return {
        "student": student_id,
        "day": learned_state.get("day", 0),
        "days_completed": learned_state.get("day", 0),
        "stable_vocabulary": _take_learning_bucket(vocab_items, "word", True, 10),
        "unstable_vocabulary": _take_learning_bucket(vocab_items, "word", False, 8),
        "stable_grammar": _take_learning_bucket(grammar_items, "rule", True, 8),
        "unstable_grammar": _take_learning_bucket(grammar_items, "rule", False, 6),
        "persistent_errors": _dedupe_strings(learned_state.get("persistent_errors", []), limit=8),
        "emotional_state": learned_state.get("emotional_state", ""),
        "recent_kanns": recent_attempts[:5],
        "recent_highlights": recent_highlights,
        "totals": {
            "vocabulary": len(vocab_items),
            "grammar": len(grammar_items),
        },
    }


def summarize_prior_progress(progress_entries, limit=5):
    if not progress_entries:
        return "No prior data."
    lines = []
    for entry in progress_entries[-limit:]:
        result = entry.get("kann_result", "")
        highlight = re.sub(r"\s+", " ", str(entry.get("session_highlight", "")).strip())
        errors = ", ".join(_dedupe_strings(entry.get("persistent_errors", []), limit=3))
        line = f"Day {entry.get('day', '?')}: {result}"
        if highlight:
            line += f" | {highlight}"
        if errors:
            line += f" | Errors: {errors}"
        lines.append(line)
    return "\n".join(lines)


def format_kann_focus_for_prompt(kann_focus):
    blocks = []
    guide = kann_focus.get("quick_guide") or {}
    if guide:
        guide_lines = [
            f"  - Original DE: {guide.get('kb_de', kann_focus.get('kann_text', ''))}",
            f"  - Simple DE: {guide.get('kb_de_simple', '')}",
            f"  - Simple EN: {guide.get('kb_en_simple', '')}",
            f"  - Scene: {guide.get('scene', '')}",
        ]
        if guide.get("task_shape"):
            guide_lines.append("  - Task shape: " + " / ".join(guide["task_shape"][:4]))
        if guide.get("core_phrases"):
            guide_lines.append("  - Core phrases: " + "; ".join(guide["core_phrases"][:6]))
        if guide.get("word_bank"):
            guide_lines.append("  - Word bank: " + ", ".join(guide["word_bank"][:12]))
        if guide.get("grammar_tools"):
            guide_lines.append("  - Grammar tools: " + "; ".join(guide["grammar_tools"][:6]))
        blocks.append("KB quick guide:\n" + "\n".join(line for line in guide_lines if line.strip()))
    if kann_focus.get("global_relationships"):
        rel_lines = []
        for rel in kann_focus["global_relationships"]:
            ids = ", ".join(rel.get("kann_ids", []))
            bridge_ids = ", ".join(rel.get("bridge_to_kann_ids", []))
            suffix = f" ({ids})" if ids else ""
            if bridge_ids:
                suffix += f" -> bridges to {bridge_ids}"
            rel_lines.append(f"  - {rel.get('name', rel.get('id', 'relationship'))}{suffix}: {rel.get('summary', '')}")
            if rel.get("teacher_guidance"):
                rel_lines.append(f"    Teacher: {rel['teacher_guidance']}")
        blocks.append("Global KB relationships:\n" + "\n".join(rel_lines))
    if kann_focus.get("syllabus_branches"):
        branch_lines = []
        for branch in kann_focus["syllabus_branches"]:
            branch_lines.append(f"  - {branch.get('name', branch.get('id', 'branch'))}: {branch.get('summary', '')}")
            if branch.get("teacher_language"):
                branch_lines.append(f"    Teacher may say: {branch['teacher_language']}")
            for cluster in branch.get("fruit_clusters", [])[:2]:
                words = ", ".join(cluster.get("words", [])[:8])
                tools = ", ".join(cluster.get("grammar_tools", [])[:5])
                branch_lines.append(f"    Fruit cluster - {cluster.get('id', 'cluster')}: {words} | grammar/tools: {tools}")
        blocks.append("A1 syllabus branches:\n" + "\n".join(branch_lines))
    if kann_focus.get("speech_acts"):
        blocks.append("Target speech acts:\n" + "\n".join(f"  - {item}" for item in kann_focus["speech_acts"]))
    if kann_focus.get("grammar_targets"):
        blocks.append("Target grammar:\n" + "\n".join(f"  - {item}" for item in kann_focus["grammar_targets"]))
    if kann_focus.get("wortfeld_samples"):
        word_lines = []
        for sample in kann_focus["wortfeld_samples"]:
            words = ", ".join(sample["examples"])
            word_lines.append(f"  - {sample['field']}: {words}")
        blocks.append("Target vocabulary fields:\n" + "\n".join(word_lines))
    if kann_focus.get("example_bank"):
        blocks.append(
            "Example bank:\n" +
            "\n".join(
                f"  - {example['text']} [{example.get('source', 'seed')}]"
                for example in kann_focus["example_bank"]
            )
        )
    return "\n\n".join(blocks) if blocks else "No additional Kann focus mapping."


def build_kann_progress_entry(kann, kann_focus, day_num, day_summary, grader_reports):
    vocab_used = []
    for report in grader_reports:
        vocab_used.extend(report.get("wortfeld_used", []))
    grammar_notes = []
    for report in grader_reports:
        grammar_notes.extend(report.get("grammar_notes", []))
    return {
        "day": day_num,
        "kann_id": kann["id"],
        "kann_text": kann["kann"],
        "category": kann.get("category", ""),
        "result": day_summary.get("kann_result", "teilweise"),
        "speech_acts": kann_focus.get("speech_acts", []),
        "grammar_targets": kann_focus.get("grammar_targets", []),
        "wortfeld_targets": kann_focus.get("wortfeld_targets", []),
        "global_relationships": [
            {
                "id": rel.get("id", ""),
                "name": rel.get("name", ""),
                "kann_ids": rel.get("kann_ids", []),
                "bridge_to_kann_ids": rel.get("bridge_to_kann_ids", []),
            }
            for rel in kann_focus.get("global_relationships", [])
        ],
        "syllabus_branches": [
            {
                "id": branch.get("id", ""),
                "name": branch.get("name", ""),
                "relationship_ids": branch.get("relationship_ids", []),
            }
            for branch in kann_focus.get("syllabus_branches", [])
        ],
        "wortfeld_used": _dedupe_strings(vocab_used, limit=8),
        "grammar_learned": day_summary.get("grammar_learned", []),
        "vocabulary_learned": day_summary.get("vocabulary_learned", []),
        "persistent_errors": _dedupe_strings(day_summary.get("persistent_errors", []), limit=8),
        "grammar_notes": _dedupe_strings(grammar_notes, limit=8),
        "session_highlight": day_summary.get("session_highlight", ""),
    }

# ── load canon + prompts (read-only) ──────────────────────────────
kann_data    = load("canon/kannbeschreibungen_full.json")
all_kanns    = kann_data["kannbeschreibungen"]
KANN_BY_ID   = {k["id"]: k for k in all_kanns}
TOTAL_KANNS  = len(all_kanns)
canon_bewert = load("canon/bewertung.json")
canon_gram   = load("canon/grammatik.json")
kann_map_cfg = load_optional("canon/kann_map.json", {
    "category_defaults": {},
    "keyword_rules": [],
    "manual_overrides": {},
})
kann_relationship_cfg = load_optional("canon/kann_relationships.json", {
    "relationship_groups": [],
})
a1_syllabus_cfg = load_optional("canon/a1_syllabus_branches.json", {
    "branches": [],
})
kann_quick_guides_cfg = load_optional("canon/kann_quick_guides.json", {
    "guides": {},
})
sprachacts   = load("canon/sprachhandlungen.json")
teacher_pers = load("prompts/teacher/persona.json")
rounds_tmpl  = load("prompts/teacher/round_frames.json")["rounds"]
wrapup_tmpl  = load("prompts/teacher/wrapup.json")
bridges      = load("prompts/interstitials/bridges.json")
grader_round = load("prompts/grader/per_round.json")
grader_day   = load("prompts/grader/day_summary.json")
overlay_tmpl = load("prompts/students/learning_overlay.json")
wortfelder   = load("canon/wortfelder.json")

STUDENT_IDS = runtime_cfg["classroom"]["students"]
student_configs = {sid: load(f"prompts/students/{sid}.json") for sid in STUDENT_IDS}
observer_cfg = runtime_cfg["classroom"].get("observer", {})
NOTE_TAKER_ENABLED = bool(observer_cfg.get("enabled"))
NOTE_TAKER_ID = observer_cfg.get("id", "note_taker")
NOTE_TAKER_NAME = observer_cfg.get("name", "Note Taker")
note_taker_tmpl = load_optional(f"prompts/observers/{NOTE_TAKER_ID}.json", {})

# ── live state ─────────────────────────────────────────────────────
live = {
    "status": "starting",
    "current_day": 0,
    "current_kann": "",
    "current_kann_text": "",
    "current_kann_focus": {},
    "current_round": 0,
    "current_round_name": "",
    "active_student": "",
    "student_summaries": {},
    "days": [],  # [{day, kann_id, kann_text, category, rounds, summaries}]
    "done": False
}
run_lock = threading.Lock()

# ── HTML rendering ─────────────────────────────────────────────────
def _esc(s):
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def _attr(s):
    return _esc(s).replace('"', "&quot;")

STUDENT_COLORS = {"marta": "#dcf8c6", "james": "#d4e6f1", "yuki": "#f9e79f"}
STUDENT_LABEL_COLORS = {"marta": "#2e7d32", "james": "#1565c0", "yuki": "#e65100"}
STUDENT_NAMES = {sid: student_configs[sid]["name"] for sid in STUDENT_IDS}

# ── CSS (plain string — no f-string escaping needed) ──────────────
_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
:root{--sidebar-width:320px}
html,body{height:100%;overflow:hidden}
body{font-family:-apple-system,'Segoe UI',Roboto,Helvetica,sans-serif;background:#f0f0f0;color:#222;
  -webkit-user-select:text;user-select:text;-webkit-touch-callout:default}
button,input{font:inherit}

/* ── sticky header ── */
.live-header{
  position:fixed;top:0;left:0;right:0;z-index:200;
  display:flex;justify-content:space-between;align-items:center;
  padding:9px 20px;background:#075e54;color:#fff;
  font-size:0.88em;box-shadow:0 2px 6px rgba(0,0,0,.18);
}
.lh-left{display:flex;align-items:baseline;gap:6px;min-width:0;flex-wrap:wrap}
.lh-tag{font-weight:700}
.lh-sep{opacity:.4;margin:0 4px}
.lh-round{}
.lh-kann{opacity:.85;font-size:.92em;white-space:normal}
.lh-right{display:flex;align-items:center;gap:12px;flex-shrink:0}
.lh-student{font-weight:700;color:#a5d6a7}
.lh-updated{opacity:.65;font-size:.82em}

/* ── two-pane layout ── */
.layout{
  display:grid;grid-template-columns:1fr 12px var(--sidebar-width);
  height:calc(100vh - 42px);margin-top:42px;
}
.transcript{overflow-y:auto;padding:16px 28px 40px 28px;background:#f0f0f0;min-width:0}
.splitter{
  position:relative;background:#eef1f3;cursor:col-resize;
  border-left:1px solid #d6dbe0;border-right:1px solid #d6dbe0;
  touch-action:none;
}
.splitter::before{
  content:'';position:absolute;top:0;bottom:0;left:50%;transform:translateX(-50%);
  width:2px;border-radius:999px;background:#b5bec7;transition:background .15s ease;
}
.splitter:hover::before,.splitter.dragging::before{background:#075e54}
.sidebar{overflow-y:auto;padding:14px;background:#fff;border-left:1px solid #ddd;min-width:0}
body.resizing{cursor:col-resize}
body.resizing *{cursor:col-resize !important;user-select:none !important}

/* ── view controls ── */
.view-controls{display:flex;gap:4px;margin-bottom:14px}
.vbtn{flex:1;padding:7px 4px;border:1px solid #ccc;background:#f8f8f8;
  cursor:pointer;font-size:.74em;border-radius:5px;transition:all .15s;font-weight:600}
.vbtn:hover{background:#e8e8e8}
.vbtn.active{background:#075e54;color:#fff;border-color:#075e54}

/* ── sidebar sections ── */
.sidebar-section{margin-bottom:16px}
.sidebar-title{font-weight:700;font-size:.78em;color:#666;margin-bottom:6px;
  text-transform:uppercase;letter-spacing:.5px}

/* ── compact scorecard ── */
.scorecard{width:100%;border-collapse:collapse;font-size:.72em}
.scorecard th{background:#075e54;color:#fff;padding:3px 5px;text-align:left;position:sticky;top:0}
.scorecard td{padding:2px 5px;border:1px solid #e0e0e0}
.scorecard-tools{display:flex;gap:6px;margin:0 0 8px 0}
.scorecard-scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.scorecard-tool{
  border:1px solid #cfd6dc;background:#f8f9fa;color:#34444c;border-radius:5px;
  padding:5px 7px;font-size:.72em;font-weight:700;cursor:pointer;
}
.scorecard-tool:hover{background:#eef3f5;border-color:#aeb9c2}
.sc-day{font-weight:700;width:28px}
.sc-kann{min-width:240px;white-space:normal;line-height:1.35}
.scorecard-row{cursor:pointer}
.scorecard-row:hover .sc-kann{background:#eef8f6}
.scorecard-link{
  display:block;width:100%;border:0;background:transparent;color:inherit;
  font:inherit;text-align:left;line-height:inherit;cursor:pointer;padding:0;
}
.scorecard-link:focus{outline:2px solid #075e54;outline-offset:2px;border-radius:3px}
.pass{background:#d4edda;color:#155724;font-weight:700}
.partial{background:#fff3cd;color:#856404;font-weight:700}
.fail{background:#f8d7da;color:#721c24;font-weight:700}
.pending{background:#f5f5f5;color:#aaa}

/* ── day blocks ── */
.day-block{background:#fff;border-radius:10px;margin:12px 0;box-shadow:0 1px 4px rgba(0,0,0,.07)}
.day-block.day-highlight{box-shadow:0 0 0 3px rgba(7,94,84,.22),0 1px 4px rgba(0,0,0,.07)}
.day-block>summary{
  padding:13px 18px;cursor:pointer;font-weight:600;font-size:.95em;color:#333;
  list-style:none;
}
.day-block>summary::-webkit-details-marker{display:none}
.day-block>summary::before{content:'\u25b6';margin-right:10px;font-size:.65em;
  transition:transform .2s;display:inline-block;color:#999}
.day-block[open]>summary::before{transform:rotate(90deg)}
.day-block[open]>summary{border-bottom:1px solid #eee}
.day-content{padding:14px 20px}

/* ── kann banner ── */
.kann-banner{
  background:#e8f5e9;border-left:4px solid #2e7d32;border-radius:6px;
  padding:10px 14px;margin-bottom:16px;line-height:1.5;
}
.kann-id{font-weight:700;color:#2e7d32;font-size:.88em}
.kann-cat{font-size:.78em;color:#666;margin-left:8px}
.kann-text{margin-top:4px;font-size:.95em;color:#333;-webkit-user-select:text;user-select:text;cursor:text}

/* ── round headers ── */
.round-header{
  text-align:center;color:#555;font-size:.88em;font-weight:600;
  margin:24px 0 10px 0;padding:6px 0;
  border-bottom:2px solid #e0e0e0;
}

/* ── exchange groups (spacer between each teacher-student pair) ── */
.exchange-group{margin:0 0 20px 0;padding-bottom:16px;border-bottom:1px solid #eee}
.exchange-group:last-child{border-bottom:none;margin-bottom:0;padding-bottom:0}

/* ── messages ── */
.msg{padding:12px 16px;border-radius:12px;margin:8px 0;line-height:1.65;font-size:1em;
  -webkit-user-select:text;user-select:text;cursor:text}
.text{-webkit-user-select:text;user-select:text;cursor:text}
.teacher-msg{
  background:#fff;border-left:4px solid #075e54;max-width:85%;
  box-shadow:0 1px 2px rgba(0,0,0,.04);
}
.student-msg{
  max-width:85%;margin-left:auto;
  border-right:4px solid rgba(0,0,0,.08);
  box-shadow:0 1px 2px rgba(0,0,0,.04);
}
.speaker{font-weight:700;font-size:.82em;margin-bottom:4px;
  -webkit-user-select:text;user-select:text}
.teacher-label{color:#075e54}

/* ── grader ── */
.grader-block{
  background:#fff8e1;max-width:90%;margin:8px auto;border-radius:8px;
  border-left:4px solid #ffc107;padding:8px 14px;font-size:.85em;
}
.grader-label{font-weight:700;font-size:.75em;color:#856404;margin-bottom:2px}
.grader-text{color:#5d4037;-webkit-user-select:text;user-select:text;cursor:text}

/* ── quiet note-taker ── */
.observer-block{
  background:#eef6ff;max-width:92%;margin:8px auto;border-radius:8px;
  border-left:4px solid #4f8fcf;padding:8px 14px;font-size:.85em;
}
.observer-label{font-weight:700;font-size:.75em;color:#24527a;margin-bottom:4px}
.observer-text{color:#25384a;line-height:1.5;-webkit-user-select:text;user-select:text;cursor:text}
.observer-row{margin:2px 0}
.observer-row b{color:#183a59}

/* ── prompt boxes (debug) ── */
.prompt-details{margin-top:6px}
.prompt-toggle{font-size:.72em;color:#075e54;cursor:pointer;text-decoration:underline}
.prompt-box{
  background:#1a1a2e;color:#0f0;font-family:'SF Mono',Menlo,Consolas,monospace;
  font-size:.72em;padding:10px;border-radius:6px;margin:4px 0;
  max-height:220px;overflow-y:auto;white-space:pre-wrap;word-wrap:break-word;
}

/* ── day summaries ── */
.day-summaries{margin-top:18px;padding-top:14px;border-top:2px solid #e0e0e0}
.summaries-label{font-weight:700;font-size:.88em;color:#555;margin-bottom:8px}
.summary-item{
  padding:8px 14px;border-radius:6px;margin:5px 0;font-size:.9em;
  border-left:4px solid #999;background:#fafafa;
  -webkit-user-select:text;user-select:text;cursor:text;
}
.summary-item.pass{border-left-color:#28a745;background:#f0faf2}
.summary-item.partial{border-left-color:#ffc107;background:#fffdf0}
.summary-item.fail{border-left-color:#dc3545;background:#fef0f0}

/* ── status in sidebar ── */
.status-text{font-size:.82em;color:#666;padding:8px 10px;background:#f8f9fa;border-radius:5px;line-height:1.5}
.run-form{
  display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px;
  background:#f8f9fa;border:1px solid #e3e7ea;border-radius:8px;padding:10px;
}
.run-input{
  width:100%;border:1px solid #cfd6dc;border-radius:5px;padding:7px 8px;
  font-size:.82em;background:#fff;color:#1f2d35;
}
.run-button{
  border:1px solid #075e54;background:#075e54;color:#fff;border-radius:5px;
  padding:7px 10px;font-size:.78em;font-weight:700;cursor:pointer;
}
.run-button:hover{background:#064d45}
.run-help{font-size:.74em;color:#66757f;line-height:1.45;margin-top:6px}

/* ── reader workbench ── */
.workbench-card{
  background:#f8f9fa;border:1px solid #e3e7ea;border-radius:8px;padding:10px 12px;
}
.workbench-textarea{
  width:100%;min-height:150px;resize:vertical;border:1px solid #cfd6dc;border-radius:6px;
  padding:9px 10px;background:#fff;color:#1f2d35;font-size:.84em;line-height:1.45;
}
.workbench-textarea:focus{outline:2px solid rgba(7,94,84,.22);border-color:#075e54}
.workbench-tools{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.workbench-button{
  border:1px solid #cfd6dc;background:#fff;color:#34444c;border-radius:5px;
  padding:6px 8px;font-size:.74em;font-weight:700;cursor:pointer;
}
.workbench-button:hover{background:#eef3f5;border-color:#aeb9c2}

/* ── billing ── */
.billing-card{
  background:#f8f9fa;border:1px solid #e3e7ea;border-radius:8px;padding:10px 12px;
}
.billing-card + .billing-card{margin-top:8px}
.billing-amount{font-size:1.15em;font-weight:700;color:#075e54}
.billing-meta{font-size:.76em;color:#5f6b73;line-height:1.45;margin-top:4px}
.billing-breakdown{margin-top:8px;border-top:1px solid #e3e7ea;padding-top:8px}
.billing-row{
  display:flex;justify-content:space-between;gap:10px;align-items:flex-start;
  font-size:.74em;line-height:1.4;padding:4px 0;
}
.billing-step{color:#33444d}
.billing-step strong{display:block;font-size:.98em;color:#1f2d35}
.billing-cost{white-space:nowrap;color:#075e54;font-weight:700}

/* ── kann focus + student summaries ── */
.focus-card,.student-card{
  background:#f8f9fa;border:1px solid #e3e7ea;border-radius:8px;padding:10px 12px;
}
.focus-card + .focus-card,.student-card + .student-card{margin-top:8px}
.focus-lead{font-size:.82em;color:#444;line-height:1.45;margin-bottom:8px}
.focus-subtitle{font-size:.75em;font-weight:700;color:#4f5b62;text-transform:uppercase;letter-spacing:.4px;margin:8px 0 4px 0}
.focus-list{font-size:.78em;color:#333;line-height:1.45;padding-left:16px}
.focus-list li{margin:2px 0}
.quick-guide{
  background:#fff;border:1px solid #dce7e3;border-left:4px solid #075e54;
  border-radius:8px;padding:9px 10px;margin:8px 0 10px 0;
}
.quick-title{font-weight:800;color:#075e54;font-size:.84em;margin-bottom:6px}
.quick-line{font-size:.79em;color:#27363d;line-height:1.45;margin:4px 0}
.quick-tags{display:flex;flex-wrap:wrap;gap:4px;margin:4px 0 6px 0}
.quick-tag{
  font-size:.72em;line-height:1.3;padding:3px 6px;border-radius:999px;
  background:#eef8f6;color:#1d4c45;border:1px solid #d1e5df;
}
.syllabus-browser-card{
  background:#f8f9fa;border:1px solid #e3e7ea;border-radius:8px;padding:10px 12px;
}
.syllabus-search{
  width:100%;border:1px solid #cfd6dc;border-radius:6px;padding:8px 9px;
  font-size:.84em;background:#fff;color:#1f2d35;
}
.syllabus-search:focus{outline:2px solid rgba(7,94,84,.22);border-color:#075e54}
.syllabus-tools{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}
.syllabus-tool,.syllabus-action,.syllabus-related{
  border:1px solid #cfd6dc;background:#fff;color:#34444c;border-radius:5px;
  padding:5px 7px;font-size:.72em;font-weight:700;cursor:pointer;
}
.syllabus-tool:hover,.syllabus-action:hover,.syllabus-related:hover{background:#eef3f5;border-color:#aeb9c2}
.syllabus-count{font-size:.74em;color:#66757f;line-height:1.4;margin-bottom:8px}
.syllabus-list{display:flex;flex-direction:column;gap:6px;max-height:48vh;overflow-y:auto;padding-right:2px}
.syllabus-item{
  background:#fff;border:1px solid #e1e6ea;border-radius:8px;overflow:hidden;
}
.syllabus-item.active{border-color:#075e54;box-shadow:0 0 0 2px rgba(7,94,84,.12)}
.syllabus-item.highlight{box-shadow:0 0 0 3px rgba(7,94,84,.22)}
.syllabus-item[hidden]{display:none}
.syllabus-item>summary{
  list-style:none;cursor:pointer;padding:8px 10px;line-height:1.35;
}
.syllabus-item>summary::-webkit-details-marker{display:none}
.syllabus-summary-main{display:flex;gap:6px;align-items:baseline;margin-bottom:3px}
.syllabus-kid{font-weight:800;color:#075e54;font-size:.82em;white-space:nowrap}
.syllabus-cat{font-size:.7em;color:#66757f;white-space:nowrap}
.syllabus-summary-text{font-size:.78em;color:#2d3a40}
.syllabus-body{border-top:1px solid #edf0f2;padding:9px 10px}
.syllabus-body .quick-tags{margin-bottom:8px}
.syllabus-related-row{display:flex;gap:4px;flex-wrap:wrap;margin-top:6px}
.syllabus-actions{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
.student-card.active{border-color:#075e54;background:#eef8f6}
.student-head{display:flex;justify-content:space-between;gap:10px;align-items:baseline}
.student-name{font-weight:700;font-size:.86em}
.student-meta{font-size:.74em;color:#666}
.student-row{font-size:.76em;color:#444;line-height:1.45;margin-top:6px}
.student-tags{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}
.student-tag{font-size:.7em;padding:2px 6px;border-radius:999px;background:#e9ecef;color:#495057}
.student-tag.fail{background:#fdecea;color:#b42318}
.student-tag.partial{background:#fff3cd;color:#856404}
.student-tag.pass{background:#d4edda;color:#155724}

/* ── view mode filtering ── */
body.view-conversation .grader-block{display:none}
body.view-conversation .prompt-details{display:none}
body.view-syllabus .grader-block{display:none}
body.view-syllabus .prompt-details{display:none}
body.view-grader .prompt-details{display:none}
/* body.view-debug — everything visible */

/* ── mobile / iPhone ── */
@media(max-width:768px){
  .layout{display:block;height:auto;margin-top:0}
  .live-header{position:sticky;flex-wrap:wrap;padding:8px 12px;font-size:.82em}
  .splitter{display:none}
  .lh-sep{display:none}
  .lh-left{gap:4px}
  .lh-right{width:100%;justify-content:space-between;margin-top:4px}
  .lh-kann{display:block;width:100%;line-height:1.35}
  html,body{height:auto;overflow:auto}
  .transcript{padding:10px 12px 30px 12px;min-height:0}
  .sidebar{border-left:none;border-top:1px solid #ddd;padding:12px}
  .day-content{padding:10px 12px}
  .msg{max-width:100% !important;padding:10px 12px;font-size:.96em;line-height:1.58}
  .teacher-msg{max-width:100%}
  .student-msg{max-width:100%;margin-left:0}
  .grader-block{max-width:100%}
  .observer-block{max-width:100%}
  .kann-banner{padding:8px 10px}
  .round-header{margin:16px 0 8px 0}
  .exchange-group{margin-bottom:14px;padding-bottom:12px}
  .prompt-box{max-height:150px;font-size:.65em}
  .day-block>summary{padding:12px 12px;font-size:.9em;line-height:1.35}
  .scorecard{font-size:.72em;min-width:620px}
  .scorecard-tools{flex-wrap:wrap}
  .scorecard-tool,.vbtn,.run-button,.workbench-button{min-height:44px}
  .run-input{min-height:44px;font-size:16px}
  .workbench-textarea{font-size:16px;min-height:180px}
  .syllabus-search{font-size:16px;min-height:44px}
  .syllabus-list{max-height:none;overflow:visible}
  .syllabus-tool,.syllabus-action,.syllabus-related{min-height:38px}
  .vbtn{padding:8px 6px;font-size:.76em}
  .prompt-toggle{display:inline-block;padding:8px 0}
}
@media(max-width:430px){
  .live-header{padding:6px 10px;font-size:.78em}
  .lh-tag,.lh-round{font-size:.85em}
  .lh-kann{font-size:.8em}
  .transcript{padding:8px 8px 24px 8px}
  .day-content{padding:8px 10px}
  .msg{padding:9px 10px;font-size:.93em;border-radius:8px}
  .speaker{font-size:.78em}
  .kann-text{font-size:.88em}
  .sidebar{padding:10px}
  .run-form{grid-template-columns:1fr}
}
"""

# ── JS (plain string — no f-string escaping needed) ───────────────
_JS = """
(function(){
  var currentView = localStorage.getItem('sprecher-view') || 'conversation';
  var sidebarWidth = parseInt(localStorage.getItem('sprecher-sidebar-width') || '320', 10);
  var lastUpdate = Date.now();
  var dayOpenState = loadDayOpenState();
  var workbenchKey = 'sprecher-workbench-notes';

  function loadDayOpenState() {
    try {
      return JSON.parse(localStorage.getItem('sprecher-day-open-state') || '{}') || {};
    } catch (e) {
      return {};
    }
  }

  function saveDayOpenState() {
    localStorage.setItem('sprecher-day-open-state', JSON.stringify(dayOpenState));
  }

  function setWorkbenchValue(value) {
    var box = document.getElementById('workbench-notes');
    if (!box) return;
    box.value = value;
    localStorage.setItem(workbenchKey, value);
  }

  function currentKbNote() {
    var tag = document.querySelector('.lh-tag');
    var round = document.querySelector('.lh-round');
    var kann = document.querySelector('.lh-kann');
    var parts = [];
    if (tag && tag.textContent.trim()) parts.push(tag.textContent.trim());
    if (round && round.textContent.trim()) parts.push(round.textContent.trim());
    if (kann && kann.textContent.trim()) parts.push(kann.textContent.trim());
    return parts.join(' | ');
  }

  function currentKbId() {
    var kann = document.querySelector('.lh-kann');
    var text = kann ? kann.textContent : '';
    var match = text.match(/K\d{3}/);
    return match ? match[0] : '';
  }

  function appendWorkbenchText(text) {
    var box = document.getElementById('workbench-notes');
    if (!box || !text) return;
    var prefix = box.value && !box.value.endsWith('\n') ? '\n\n' : '';
    setWorkbenchValue(box.value + prefix + text);
    box.focus();
  }

  function initWorkbench() {
    var box = document.getElementById('workbench-notes');
    if (!box) return;
    var saved = localStorage.getItem(workbenchKey);
    if (saved !== null) box.value = saved;
    box.addEventListener('input', function(){
      localStorage.setItem(workbenchKey, box.value);
    });
  }

  function updateSyllabusCount() {
    var count = document.getElementById('syllabus-count');
    if (!count) return;
    var visible = document.querySelectorAll('.syllabus-item:not([hidden])').length;
    var total = document.querySelectorAll('.syllabus-item').length;
    count.textContent = visible + ' / ' + total + ' KBs visible';
  }

  function filterSyllabus(value) {
    var needle = (value || '').trim().toLowerCase();
    document.querySelectorAll('.syllabus-item').forEach(function(item){
      var haystack = (item.getAttribute('data-search') || '').toLowerCase();
      item.hidden = needle && haystack.indexOf(needle) === -1;
    });
    updateSyllabusCount();
  }

  function openSyllabusItem(kid) {
    if (!kid) return;
    var item = document.getElementById('syllabus-' + kid);
    if (!item) return;
    item.hidden = false;
    item.open = true;
    item.scrollIntoView({behavior:'smooth', block:'start'});
    item.classList.add('highlight');
    window.setTimeout(function(){ item.classList.remove('highlight'); }, 1800);
  }

  function highlightCurrentSyllabus() {
    var kid = currentKbId();
    document.querySelectorAll('.syllabus-item').forEach(function(item){
      item.classList.toggle('active', item.getAttribute('data-kb-id') === kid);
    });
  }

  function initSyllabusBrowser() {
    var search = document.getElementById('syllabus-filter');
    if (search) {
      var saved = localStorage.getItem('sprecher-syllabus-filter') || '';
      search.value = saved;
      filterSyllabus(saved);
      search.addEventListener('input', function(){
        localStorage.setItem('sprecher-syllabus-filter', search.value);
        filterSyllabus(search.value);
      });
    }
    highlightCurrentSyllabus();
  }

  function applySidebarWidth(px) {
    if (!Number.isFinite(px)) return;
    var maxW = Math.floor(window.innerWidth * 0.75);
    var clamped = Math.max(200, Math.min(maxW, px));
    sidebarWidth = clamped;
    document.documentElement.style.setProperty('--sidebar-width', clamped + 'px');
  }

  function initSplitter() {
    var splitter = document.getElementById('splitter');
    var layout = document.querySelector('.layout');
    if (!splitter || !layout || window.innerWidth <= 768) return;

    var dragging = false;

    function onMove(clientX) {
      var rect = layout.getBoundingClientRect();
      applySidebarWidth(rect.right - clientX);
    }

    function handlePointerMove(e) {
      if (!dragging) return;
      onMove(e.clientX);
    }

    function stopDrag() {
      if (!dragging) return;
      dragging = false;
      splitter.classList.remove('dragging');
      document.body.classList.remove('resizing');
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', stopDrag);
      localStorage.setItem('sprecher-sidebar-width', String(sidebarWidth));
    }

    splitter.addEventListener('pointerdown', function(e){
      if (window.innerWidth <= 768) return;
      dragging = true;
      splitter.classList.add('dragging');
      document.body.classList.add('resizing');
      window.addEventListener('pointermove', handlePointerMove);
      window.addEventListener('pointerup', stopDrag);
      e.preventDefault();
    });
  }

  applySidebarWidth(sidebarWidth);

  function setView(v) {
    currentView = v;
    localStorage.setItem('sprecher-view', v);
    document.body.classList.remove('view-conversation', 'view-syllabus', 'view-grader', 'view-debug');
    document.body.classList.add('view-' + v);
    document.querySelectorAll('.vbtn').forEach(function(b){
      b.classList.toggle('active', b.getAttribute('data-view') === v);
    });
    if (v === 'syllabus') {
      var target = document.getElementById('syllabus-browser-section') || document.getElementById('syllabus-section');
      if (target) target.scrollIntoView({behavior:'smooth', block:'start'});
      highlightCurrentSyllabus();
    }
  }
  setView(currentView);

  // button clicks via delegation
  document.addEventListener('click', function(e){
    if (e.target.classList.contains('vbtn')) {
      setView(e.target.getAttribute('data-view'));
      return;
    }

    var workbenchButton = e.target.closest ? e.target.closest('.workbench-button') : null;
    if (workbenchButton) {
      if (workbenchButton.getAttribute('data-workbench-action') === 'insert-kann') {
        appendWorkbenchText(currentKbNote());
      }
      if (workbenchButton.getAttribute('data-workbench-action') === 'clear') {
        var box = document.getElementById('workbench-notes');
        if (box && (!box.value || window.confirm('Clear workbench notes?'))) {
          setWorkbenchValue('');
        }
      }
      return;
    }

    var syllabusAction = e.target.closest ? e.target.closest('[data-syllabus-action]') : null;
    if (syllabusAction) {
      var action = syllabusAction.getAttribute('data-syllabus-action');
      if (action === 'current') {
        setView('syllabus');
        openSyllabusItem(currentKbId());
      }
      if (action === 'clear-filter') {
        var sf = document.getElementById('syllabus-filter');
        if (sf) {
          sf.value = '';
          localStorage.setItem('sprecher-syllabus-filter', '');
          filterSyllabus('');
          sf.focus();
        }
      }
      return;
    }

    var kbOpen = e.target.closest ? e.target.closest('[data-kb-open]') : null;
    if (kbOpen) {
      e.preventDefault();
      setView('syllabus');
      openSyllabusItem(kbOpen.getAttribute('data-kb-open'));
      return;
    }

    var kbRun = e.target.closest ? e.target.closest('[data-syllabus-run]') : null;
    if (kbRun) {
      var input = document.querySelector('.run-input');
      if (input) {
        input.value = kbRun.getAttribute('data-syllabus-run');
        input.focus();
      }
      return;
    }

    var tool = e.target.closest ? e.target.closest('.scorecard-tool') : null;
    if (tool) {
      if (tool.getAttribute('data-day-action') === 'collapse-all') setAllDays(false);
      if (tool.getAttribute('data-day-action') === 'expand-all') setAllDays(true);
      if (tool.getAttribute('data-day-action') === 'latest') openLatestDay();
      return;
    }

    var link = e.target.closest ? e.target.closest('.scorecard-link') : null;
    if (link) {
      e.preventDefault();
      scrollToDay(link.getAttribute('data-target-day'));
      return;
    }

    var row = e.target.closest ? e.target.closest('.scorecard-row') : null;
    if (row) {
      scrollToDay(row.getAttribute('data-target-day'));
    }
  });

  // track manual close of day blocks
  document.addEventListener('toggle', function(e){
    if (e.target.classList && e.target.classList.contains('day-block')) {
      dayOpenState[e.target.id] = !!e.target.open;
      saveDayOpenState();
    }
  }, true);

  function setAllDays(open) {
    document.querySelectorAll('.day-block').forEach(function(day){
      day.open = open;
      dayOpenState[day.id] = open;
    });
    saveDayOpenState();
  }

  function applyDayOpenState(day) {
    if (!day || !day.id) return;
    if (Object.prototype.hasOwnProperty.call(dayOpenState, day.id)) {
      day.open = !!dayOpenState[day.id];
    } else if (day.getAttribute('data-latest') === '1') {
      day.open = true;
      dayOpenState[day.id] = true;
      saveDayOpenState();
    }
  }

  function openLatestDay() {
    var allDays = document.querySelectorAll('.day-block');
    if (!allDays.length) return;
    var latest = allDays[allDays.length - 1];
    latest.open = true;
    dayOpenState[latest.id] = true;
    saveDayOpenState();
    scrollToDay(latest.id, false);
  }

  function scrollToDay(dayId, shouldOpen) {
    if (!dayId) return;
    var day = document.getElementById(dayId);
    if (!day) return;
    if (shouldOpen !== false) {
      day.open = true;
      dayOpenState[day.id] = true;
      saveDayOpenState();
    }
    day.scrollIntoView({behavior:'smooth', block:'start'});
    day.classList.add('day-highlight');
    window.setTimeout(function(){ day.classList.remove('day-highlight'); }, 1800);
  }

  document.querySelectorAll('.day-block').forEach(applyDayOpenState);

  function isNearBottom() {
    var t = document.getElementById('transcript');
    if (!t) return true;
    return t.scrollHeight - t.scrollTop - t.clientHeight < 150;
  }

  // Incremental update for the active day — only append new children,
  // never replace existing content.  This prevents jitter when reading.
  function updateActiveDay(oldDay, newDay) {
    // update summary text (e.g. "Tag 5: K005 — ...")
    var oldSum = oldDay.querySelector('summary');
    var newSum = newDay.querySelector('summary');
    if (oldSum && newSum && oldSum.textContent !== newSum.textContent) {
      oldSum.textContent = newSum.textContent;
    }

    var oldContent = oldDay.querySelector('.day-content');
    var newContent = newDay.querySelector('.day-content');
    if (!oldContent && newContent) {
      oldDay.appendChild(newContent.cloneNode(true));
      return;
    }
    if (!oldContent || !newContent) return;

    var oldKids = Array.from(oldContent.children);
    var newKids = Array.from(newContent.children);

    // append children that are new
    for (var j = oldKids.length; j < newKids.length; j++) {
      oldContent.appendChild(newKids[j].cloneNode(true));
    }

    // the last pre-existing child might have gained sub-content
    // (e.g. a grader result or student reply appeared inside it)
    if (oldKids.length > 0 && newKids.length >= oldKids.length) {
      var li = oldKids.length - 1;
      if (oldKids[li].innerHTML !== newKids[li].innerHTML) {
        oldKids[li].innerHTML = newKids[li].innerHTML;
      }
    }
  }

  function poll() {
    var wasNearBottom = isNearBottom();

    fetch(location.pathname + '?poll=1').then(function(r){ return r.text(); }).then(function(html){
      var parser = new DOMParser();
      var doc = parser.parseFromString(html, 'text/html');

      // header (fixed position — no layout shift)
      var h = document.querySelector('.live-header');
      var nh = doc.querySelector('.live-header');
      if (h && nh) h.innerHTML = nh.innerHTML;

      // sidebar sections (separate scroll context — no transcript shift)
      var secs = document.querySelectorAll('.sidebar-section');
      var nsecs = doc.querySelectorAll('.sidebar-section');
      for (var i = 0; i < nsecs.length && i < secs.length; i++) {
        if (secs[i].getAttribute('data-static')) continue;
        secs[i].innerHTML = nsecs[i].innerHTML;
      }
      highlightCurrentSyllabus();

      // transcript — append-only strategy
      var trans = document.getElementById('transcript');
      var ntrans = doc.getElementById('transcript');
      if (trans && ntrans) {
        var days = Array.from(trans.querySelectorAll('.day-block'));
        var newDays = Array.from(ntrans.querySelectorAll('.day-block'));
        var daysById = {};
        days.forEach(function(day){ daysById[day.id] = day; });

        for (var i = 0; i < newDays.length; i++) {
          var newDay = newDays[i];
          var existingDay = daysById[newDay.id];
          if (!existingDay) {
            // brand-new day block — append whole
            var clonedDay = newDay.cloneNode(true);
            trans.appendChild(clonedDay);
            applyDayOpenState(clonedDay);
          } else if (newDay.getAttribute('data-active') === '1' || newDay.getAttribute('data-latest') === '1') {
            // Active/latest day can gain exchanges while the reader keeps other days stable.
            existingDay.setAttribute('data-active', newDay.getAttribute('data-active') || '0');
            existingDay.setAttribute('data-latest', newDay.getAttribute('data-latest') || '0');
            updateActiveDay(existingDay, newDay);
            applyDayOpenState(existingDay);
          }
          // older completed days: don't touch at all
        }
      }

      // auto-open latest day only until the user explicitly chooses otherwise.
      var allDays = document.querySelectorAll('.day-block');
      if (allDays.length > 0) {
        var last = allDays[allDays.length - 1];
        applyDayOpenState(last);
      }

      // auto-scroll only if user was already at the bottom
      if (wasNearBottom) {
        var t = document.getElementById('transcript');
        if (t) t.scrollTop = t.scrollHeight;
      }

      lastUpdate = Date.now();
    }).catch(function(){});
  }

  // "updated Xs ago" ticker
  setInterval(function(){
    var el = document.getElementById('lh-updated');
    if (el && el.textContent !== 'Complete') {
      var s = Math.round((Date.now() - lastUpdate) / 1000);
      el.textContent = s < 4 ? 'live' : 'updated ' + s + 's ago';
    }
  }, 1000);

  if (location.protocol !== 'file:') {
    setInterval(poll, 3000);
  }
  initWorkbench();
  initSyllabusBrowser();
  initSplitter();
})();
"""


def _render_focus_list(items):
    if not items:
        return ""
    return "<ul class=\"focus-list\">" + "".join(f"<li>{_esc(item)}</li>" for item in items) + "</ul>"


def _render_quick_tags(items):
    if not items:
        return ""
    return '<div class="quick-tags">' + "".join(f'<span class="quick-tag">{_esc(item)}</span>' for item in items) + "</div>"


def _render_kann_focus_html(kann_focus):
    if not kann_focus:
        return '<div class="status-text">No Kann focus available yet.</div>'
    guide = kann_focus.get("quick_guide") or {}
    parts = [
        '<div class="focus-card">',
        f'<div class="focus-lead">{_esc(kann_focus.get("kann_text", ""))}</div>',
    ]
    if guide:
        parts.append('<div class="quick-guide">')
        parts.append('<div class="quick-title">KB Quick Guide</div>')
        if guide.get("kb_de_simple"):
            parts.append(f'<div class="quick-line"><b>Einfach DE:</b> {_esc(guide["kb_de_simple"])}</div>')
        if guide.get("kb_en_simple"):
            parts.append(f'<div class="quick-line"><b>Simple EN:</b> {_esc(guide["kb_en_simple"])}</div>')
        if guide.get("scene"):
            parts.append(f'<div class="quick-line"><b>Scene:</b> {_esc(guide["scene"])}</div>')
        if guide.get("roles"):
            parts.append(f'<div class="quick-line"><b>Roles:</b> {_esc(", ".join(guide["roles"]))}</div>')
        if guide.get("task_shape"):
            parts.append('<div class="focus-subtitle">Layout</div>')
            parts.append(_render_focus_list(guide["task_shape"]))
        if guide.get("core_phrases"):
            parts.append('<div class="focus-subtitle">Core Phrases</div>')
            parts.append(_render_quick_tags(guide["core_phrases"]))
        if guide.get("word_bank"):
            parts.append('<div class="focus-subtitle">Word Bank</div>')
            parts.append(_render_quick_tags(guide["word_bank"]))
        if guide.get("grammar_tools"):
            parts.append('<div class="focus-subtitle">Grammar Tools</div>')
            parts.append(_render_focus_list(guide["grammar_tools"]))
        if guide.get("related_kbs"):
            parts.append(f'<div class="quick-line"><b>Related KBs:</b> {_esc(", ".join(guide["related_kbs"]))}</div>')
        parts.append('</div>')
    if kann_focus.get("global_relationships"):
        parts.append('<div class="focus-subtitle">Global KB Relationships</div><ul class="focus-list">')
        for rel in kann_focus["global_relationships"]:
            ids = ", ".join(rel.get("kann_ids", []))
            bridge_ids = ", ".join(rel.get("bridge_to_kann_ids", []))
            suffix = f' <span class="student-meta">[{_esc(ids)}]</span>' if ids else ""
            if bridge_ids:
                suffix += f' <span class="student-meta">bridges to {_esc(bridge_ids)}</span>'
            parts.append(f'<li><b>{_esc(rel.get("name", rel.get("id", "")))}</b>{suffix}: {_esc(rel.get("summary", ""))}</li>')
        parts.append('</ul>')
    if kann_focus.get("syllabus_branches"):
        parts.append('<div class="focus-subtitle">A1 Syllabus Branches</div><ul class="focus-list">')
        for branch in kann_focus["syllabus_branches"]:
            parts.append(f'<li><b>{_esc(branch.get("name", branch.get("id", "")))}</b>: {_esc(branch.get("summary", ""))}')
            if branch.get("fruit_clusters"):
                clusters = []
                for cluster in branch.get("fruit_clusters", [])[:2]:
                    words = ", ".join(cluster.get("words", [])[:6])
                    clusters.append(f'{cluster.get("id", "cluster")}: {words}')
                parts.append(f'<br><span class="student-meta">{_esc("; ".join(clusters))}</span>')
            parts.append('</li>')
        parts.append('</ul>')
    if kann_focus.get("speech_acts"):
        parts.append('<div class="focus-subtitle">Speech Acts</div>')
        parts.append(_render_focus_list(kann_focus["speech_acts"]))
    if kann_focus.get("grammar_targets"):
        parts.append('<div class="focus-subtitle">Grammar</div>')
        parts.append(_render_focus_list(kann_focus["grammar_targets"]))
    if kann_focus.get("wortfeld_samples"):
        parts.append('<div class="focus-subtitle">Vocabulary Fields</div><ul class="focus-list">')
        for sample in kann_focus["wortfeld_samples"]:
            parts.append(f'<li><b>{_esc(sample["field"])}</b>: {_esc(", ".join(sample["examples"]))}</li>')
        parts.append('</ul>')
    if kann_focus.get("example_bank"):
        parts.append('<div class="focus-subtitle">Examples</div><ul class="focus-list">')
        for example in kann_focus["example_bank"]:
            source = example.get("source", "seed")
            parts.append(f'<li>{_esc(example["text"])} <span class="student-meta">[{_esc(source)}]</span></li>')
        parts.append('</ul>')
    parts.append('</div>')
    return "".join(parts)


_SYLLABUS_FOCUS_CACHE = None


def _get_syllabus_focus_cache():
    global _SYLLABUS_FOCUS_CACHE
    if _SYLLABUS_FOCUS_CACHE is None:
        _SYLLABUS_FOCUS_CACHE = [
            {
                "day": idx + 1,
                "kann": kann,
                "focus": derive_kann_focus(kann),
            }
            for idx, kann in enumerate(all_kanns)
        ]
    return _SYLLABUS_FOCUS_CACHE


def _render_syllabus_browser_html(current_kann_id):
    parts = [
        '<div class="syllabus-browser-card">',
        '<input id="syllabus-filter" class="syllabus-search" type="search" '
        'placeholder="Search KB, word, scene, grammar..." autocomplete="off">',
        '<div class="syllabus-tools">',
        '<button type="button" class="syllabus-tool" data-syllabus-action="current">Current KB</button>',
        '<button type="button" class="syllabus-tool" data-syllabus-action="clear-filter">Clear Search</button>',
        '</div>',
        '<div id="syllabus-count" class="syllabus-count"></div>',
        '<div class="syllabus-list">',
    ]
    for item in _get_syllabus_focus_cache():
        day = item["day"]
        kann = item["kann"]
        focus = item["focus"]
        guide = focus.get("quick_guide") or {}
        kid = kann["id"]
        active = " active" if kid == current_kann_id else ""
        opened = " open" if kid == current_kann_id else ""
        search_bits = [
            kid,
            str(day),
            kann.get("category", ""),
            kann.get("kann", ""),
            guide.get("kb_de_simple", ""),
            guide.get("kb_en_simple", ""),
            guide.get("scene", ""),
            " ".join(guide.get("roles", [])),
            " ".join(guide.get("task_shape", [])),
            " ".join(guide.get("core_phrases", [])),
            " ".join(guide.get("word_bank", [])),
            " ".join(guide.get("grammar_tools", [])),
            " ".join(guide.get("related_kbs", [])),
        ]
        parts.append(
            f'<details class="syllabus-item{active}" id="syllabus-{_attr(kid)}" '
            f'data-kb-id="{_attr(kid)}" data-search="{_attr(" ".join(search_bits))}"{opened}>'
        )
        parts.append(
            '<summary>'
            '<div class="syllabus-summary-main">'
            f'<span class="syllabus-kid">Tag {day} / {_esc(kid)}</span>'
            f'<span class="syllabus-cat">{_esc(kann.get("category", ""))}</span>'
            '</div>'
            f'<div class="syllabus-summary-text">{_esc(guide.get("kb_de_simple") or kann.get("kann", ""))}</div>'
            '</summary>'
        )
        parts.append('<div class="syllabus-body">')
        parts.append(f'<div class="quick-line"><b>Original DE:</b> {_esc(kann.get("kann", ""))}</div>')
        if guide.get("kb_en_simple"):
            parts.append(f'<div class="quick-line"><b>Simple EN:</b> {_esc(guide["kb_en_simple"])}</div>')
        if guide.get("scene"):
            parts.append(f'<div class="quick-line"><b>Scene:</b> {_esc(guide["scene"])}</div>')
        if guide.get("roles"):
            parts.append(f'<div class="quick-line"><b>Roles:</b> {_esc(", ".join(guide["roles"]))}</div>')
        if guide.get("task_shape"):
            parts.append('<div class="focus-subtitle">Layout</div>')
            parts.append(_render_focus_list(guide["task_shape"]))
        if guide.get("core_phrases"):
            parts.append('<div class="focus-subtitle">Core Phrases</div>')
            parts.append(_render_quick_tags(guide["core_phrases"]))
        if guide.get("word_bank"):
            parts.append('<div class="focus-subtitle">Word Bank</div>')
            parts.append(_render_quick_tags(guide["word_bank"]))
        if guide.get("grammar_tools"):
            parts.append('<div class="focus-subtitle">Grammar Tools</div>')
            parts.append(_render_focus_list(guide["grammar_tools"]))
        if guide.get("related_kbs"):
            parts.append('<div class="focus-subtitle">Related KBs</div><div class="syllabus-related-row">')
            for related in guide["related_kbs"][:10]:
                parts.append(f'<button type="button" class="syllabus-related" data-kb-open="{_attr(related)}">{_esc(related)}</button>')
            parts.append('</div>')
        parts.append('<div class="syllabus-actions">')
        parts.append(f'<button type="button" class="syllabus-action" data-syllabus-run="{_attr(kid)}">Put {kid} in run box</button>')
        parts.append('</div>')
        parts.append('</div></details>')
    parts.append('</div></div>')
    return "".join(parts)


def _render_student_summary_cards(student_summaries, active_student):
    cards = []
    for sid in STUDENT_IDS:
        summary = student_summaries.get(sid, {})
        active = " active" if STUDENT_NAMES.get(sid, sid) == active_student else ""
        totals = summary.get("totals", {})
        errors = summary.get("persistent_errors", [])
        stable_vocab = [item["word"] for item in summary.get("stable_vocabulary", [])[:4]]
        unstable_grammar = [item["rule"] for item in summary.get("unstable_grammar", [])[:3]]
        cards.append(f'<div class="student-card{active}">')
        cards.append(
            f'<div class="student-head"><div class="student-name">{_esc(STUDENT_NAMES.get(sid, sid))}</div>'
            f'<div class="student-meta">Day {summary.get("day", 0)}</div></div>'
        )
        cards.append(
            f'<div class="student-row">Vocab {totals.get("vocabulary", 0)} | Grammar {totals.get("grammar", 0)}</div>'
        )
        if stable_vocab:
            cards.append(f'<div class="student-row">Stable: {_esc(", ".join(stable_vocab))}</div>')
        if unstable_grammar:
            cards.append(f'<div class="student-row">Unstable grammar: {_esc(", ".join(unstable_grammar))}</div>')
        if errors:
            cards.append(f'<div class="student-row">Errors: {_esc(", ".join(errors[:3]))}</div>')
        recent_kanns = summary.get("recent_kanns", [])[:3]
        if recent_kanns:
            cards.append('<div class="student-tags">')
            for item in recent_kanns:
                cls = {"bestanden": "pass", "teilweise": "partial", "nicht_bestanden": "fail"}.get(item.get("result", ""), "")
                cards.append(f'<span class="student-tag {cls}">{_esc(item["kann_id"])} {_esc(item.get("result", ""))}</span>')
            cards.append('</div>')
        cards.append('</div>')
    return "".join(cards) if cards else '<div class="status-text">No student summaries yet.</div>'


def _render_observer_note(note):
    if not note:
        return ""
    if not isinstance(note, dict):
        return f'<div class="observer-text">{_esc(note)}</div>'
    rows = []
    if any(note.get(key, "") for key in ("kb_de", "kb_de_simple", "kb_en_simple", "exchange_note")):
        for label, key in (
            ("KB", "kb_de"),
            ("Einfach", "kb_de_simple"),
            ("English", "kb_en_simple"),
            ("Note", "exchange_note"),
        ):
            value = note.get(key, "")
            if value:
                rows.append(f'<div class="observer-row"><b>{label}:</b> {_esc(value)}</div>')
        return "".join(rows)
    for label, key in (
        ("German", "german_focus"),
        ("English", "english_meaning"),
        ("Context", "context"),
        ("Note", "reader_note"),
    ):
        value = note.get(key, "")
        if value:
            rows.append(f'<div class="observer-row"><b>{label}:</b> {_esc(value)}</div>')
    return "".join(rows) if rows else f'<div class="observer-text">{_esc(json.dumps(note, ensure_ascii=False))}</div>'


def _format_usd(value):
    if value is None:
        return "n/a"
    if value >= 0.5:
        return f"${value:.2f}"
    return f"${value:.4f}"


def _merge_billing(target, source):
    if not source:
        return target
    for key in ("calls", "prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens", "uncached_prompt_tokens"):
        target[key] += source.get(key, 0)
    target["estimated_cost_usd"] = round(target["estimated_cost_usd"] + source.get("estimated_cost_usd", 0.0), 6)
    for step, step_data in source.get("by_step", {}).items():
        merged_step = target["by_step"].setdefault(step, {
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cached_tokens": 0,
            "uncached_prompt_tokens": 0,
            "estimated_cost_usd": 0.0,
            "models": {},
        })
        for key in ("calls", "prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens", "uncached_prompt_tokens"):
            merged_step[key] += step_data.get(key, 0)
        merged_step["estimated_cost_usd"] = round(
            merged_step["estimated_cost_usd"] + step_data.get("estimated_cost_usd", 0.0), 6
        )
        for model_key, model_data in step_data.get("models", {}).items():
            merged_model = merged_step["models"].setdefault(model_key, {
                "calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cached_tokens": 0,
                "uncached_prompt_tokens": 0,
                "estimated_cost_usd": 0.0,
            })
            for key in ("calls", "prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens", "uncached_prompt_tokens"):
                merged_model[key] += model_data.get(key, 0)
            merged_model["estimated_cost_usd"] = round(
                merged_model["estimated_cost_usd"] + model_data.get("estimated_cost_usd", 0.0),
                6,
            )
    return target


def _collect_billing(days):
    aggregate = make_billing_bucket()
    for day in days:
        _merge_billing(aggregate, day.get("billing", {}))
    return aggregate


def _billing_step_label(step):
    if step == "teacher":
        return "Teacher"
    if step == "grader_round":
        return "Round Grader"
    if step == "grader_day":
        return "Day Summary"
    if step == "teacher_wrapup":
        return "Wrapup"
    if step == "note_taker":
        return "Note Taker"
    if step.startswith("student:"):
        sid = step.split(":", 1)[1]
        return f"Student: {STUDENT_NAMES.get(sid, sid)}"
    return step.replace("_", " ").title()


def _render_billing_html(current_billing, session_billing):
    if not current_billing or current_billing.get("calls", 0) == 0:
        return '<div class="status-text">No billing data yet. Start or finish a run to see pricing.</div>'

    cards = []
    for title, bucket in (("Current Day", current_billing), ("Session Total", session_billing)):
        cards.append('<div class="billing-card">')
        cards.append(f'<div class="sidebar-title">{_esc(title)}</div>')
        cards.append(f'<div class="billing-amount">{_esc(_format_usd(bucket.get("estimated_cost_usd", 0.0)))}</div>')
        cards.append(
            f'<div class="billing-meta">{bucket.get("calls", 0)} calls | '
            f'{bucket.get("prompt_tokens", 0)} prompt | '
            f'{bucket.get("completion_tokens", 0)} completion</div>'
        )
        breakdown = bucket.get("by_step", {})
        if breakdown:
            cards.append('<div class="billing-breakdown">')
            ordered_steps = sorted(
                breakdown.items(),
                key=lambda item: (-item[1].get("estimated_cost_usd", 0.0), item[0]),
            )
            for step, step_data in ordered_steps:
                cards.append(
                    '<div class="billing-row">'
                    f'<div class="billing-step"><strong>{_esc(_billing_step_label(step))}</strong>'
                    f'{step_data.get("calls", 0)} calls | {step_data.get("completion_tokens", 0)} out</div>'
                    f'<div class="billing-cost">{_esc(_format_usd(step_data.get("estimated_cost_usd", 0.0)))}</div>'
                    '</div>'
                )
            cards.append('</div>')
        cards.append('</div>')
    cards.append('<div class="status-text">DeepSeek pricing is estimated from returned token usage. Other providers may not be priced yet.</div>')
    return "".join(cards)

def render_html(include_static=True):
    status = _esc(live["status"])
    cur_day = live.get("current_day", 0)
    cur_round = live.get("current_round", 0)
    cur_round_name = _esc(live.get("current_round_name", ""))
    cur_kann = _esc(live.get("current_kann", ""))
    cur_kann_text = _esc(live.get("current_kann_text", ""))
    cur_kann_focus = live.get("current_kann_focus", {})
    active_stu = _esc(live.get("active_student", ""))
    student_summaries = live.get("student_summaries", {})
    is_done = live.get("done", False)
    current_billing = live["days"][-1].get("billing", {}) if live.get("days") else {}
    session_billing = _collect_billing(live.get("days", []))

    # ── sidebar scorecard rows ──
    sc_rows = ""
    for ddata in live["days"]:
        cells = ""
        for sid in STUDENT_IDS:
            result = ddata.get("summaries", {}).get(sid, {}).get("kann_result", "\u2026")
            cls = {"bestanden": "pass", "teilweise": "partial", "nicht_bestanden": "fail"}.get(result, "pending")
            cells += f'<td class="{cls}">{_esc(result)}</td>'
        sc_label = f'{ddata["kann_id"]}: {ddata.get("kann_text","")}'
        target_day = f'd_{ddata["day"]}'
        sc_rows += (
            f'<tr class="scorecard-row" data-target-day="{target_day}">'
            f'<td class="sc-day">{ddata["day"]}</td>'
            f'<td class="sc-kann"><button class="scorecard-link" data-target-day="{target_day}">'
            f'{_esc(sc_label)}</button></td>{cells}</tr>\n'
        )

    stu_ths = "".join(f"<th>{_esc(STUDENT_NAMES[sid][:8])}</th>" for sid in STUDENT_IDS)

    # ── transcript day blocks ──
    days_html = ""
    n_days = len(live["days"])
    for idx, ddata in enumerate(live["days"]):
        day_num = ddata["day"]
        is_latest = (idx == n_days - 1)
        is_active = (day_num == cur_day)

        kann_full = _esc(ddata.get("kann_text", ""))
        kann_cat = _esc(ddata.get("category", ""))
        days_html += f'<details class="day-block" id="d_{day_num}" data-latest="{1 if is_latest else 0}" data-active="{1 if is_active else 0}">'
        days_html += f'<summary>Tag {day_num}: {_esc(ddata["kann_id"])} \u2014 {kann_full}</summary>'
        days_html += '<div class="day-content">'
        days_html += f'<div class="kann-banner"><span class="kann-id">{_esc(ddata["kann_id"])}</span> <span class="kann-cat">{kann_cat}</span><div class="kann-text">{kann_full}</div></div>'

        for rdata in ddata.get("rounds", []):
            rnd = rdata["round"]
            days_html += f'<div class="round-header">Runde {rnd}: {_esc(rdata["name"])}</div>'

            for ex in rdata.get("exchanges", []):
                sid = ex["student"]
                sname = STUDENT_NAMES.get(sid, sid)
                scolor = STUDENT_COLORS.get(sid, "#f0f0f0")
                lcolor = STUDENT_LABEL_COLORS.get(sid, "#333")

                # exchange group: teacher → student (→ grader)
                days_html += '<div class="exchange-group">'

                t_id = f"p_{day_num}_{rnd}_{sid}_t"
                days_html += (
                    f'<div class="msg teacher-msg">'
                    f'<div class="speaker teacher-label">Lehrerin Weber \u2192 {_esc(sname)}</div>'
                    f'<div class="text">{_esc(ex.get("teacher_msg") or "[missing teacher turn]")}</div>'
                    f'<details class="prompt-details" id="{t_id}"><summary class="prompt-toggle">teacher prompt</summary>'
                    f'<pre class="prompt-box">{_esc(ex.get("teacher_prompt",""))}</pre></details></div>'
                )

                if ex.get("student_msg"):
                    s_id = f"p_{day_num}_{rnd}_{sid}_s"
                    days_html += (
                        f'<div class="msg student-msg" style="background:{scolor}">'
                        f'<div class="speaker" style="color:{lcolor}">{_esc(sname)}</div>'
                        f'<div class="text">{_esc(ex["student_msg"])}</div>'
                        f'<details class="prompt-details" id="{s_id}"><summary class="prompt-toggle">student prompt</summary>'
                        f'<pre class="prompt-box">{_esc(ex.get("student_prompt",""))}</pre></details></div>'
                    )

                if ex.get("observer_note"):
                    n_id = f"p_{day_num}_{rnd}_{sid}_n"
                    note_html = _render_observer_note(ex.get("observer_note"))
                    days_html += (
                        f'<div class="observer-block">'
                        f'<div class="observer-label">{_esc(NOTE_TAKER_NAME)} notes</div>'
                        f'<div class="observer-text">{note_html}</div>'
                        f'<details class="prompt-details" id="{n_id}"><summary class="prompt-toggle">note prompt</summary>'
                        f'<pre class="prompt-box">{_esc(ex.get("observer_prompt",""))}</pre></details></div>'
                    )

                # grader
                if ex.get("grader"):
                    g = normalize_grader_result(dict(ex["grader"]))
                    gtext = f'{g.get("verdict","")} | Sprachhandlung: {g.get("sprachhandlung","")} | Wortfeld: {", ".join(g.get("wortfeld_used",[]))}'
                    g_id = f"p_{day_num}_{rnd}_{sid}_g"
                    days_html += (
                        f'<div class="grader-block">'
                        f'<div class="grader-label">Grader \u2192 {_esc(sname)}</div>'
                        f'<div class="grader-text">{_esc(gtext)}</div>'
                        f'<details class="prompt-details" id="{g_id}"><summary class="prompt-toggle">grader prompt</summary>'
                        f'<pre class="prompt-box">{_esc(ex.get("grader_prompt",""))}</pre></details></div>'
                    )

                days_html += '</div>'  # close .exchange-group

        # day summaries
        summaries_html = ""
        for sid in STUDENT_IDS:
            summ = ddata.get("summaries", {}).get(sid)
            if summ:
                sname = STUDENT_NAMES.get(sid, sid)
                result = summ.get("kann_result", "")
                cls = {"bestanden": "pass", "teilweise": "partial", "nicht_bestanden": "fail"}.get(result, "pending")
                summaries_html += f'<div class="summary-item {cls}"><b>{_esc(sname)}</b>: {_esc(result)} \u2014 {_esc(summ.get("session_highlight",""))}</div>'
        if summaries_html:
            days_html += f'<div class="day-summaries"><div class="summaries-label">Tageszusammenfassung</div>{summaries_html}</div>'

        days_html += '</div></details>\n'

    # ── assemble page ──
    header_right = ""
    if active_stu:
        header_right += f'<span class="lh-student">\u2192 {active_stu}</span>'
    header_right += '<span class="lh-updated" id="lh-updated">' + ("Complete" if is_done else "live") + "</span>"

    kann_display = cur_kann
    if cur_kann_text:
        kann_display += ": " + cur_kann_text
    kann_focus_html = _render_kann_focus_html(cur_kann_focus)
    syllabus_browser_html = _render_syllabus_browser_html(cur_kann) if include_static else ""
    student_summary_html = _render_student_summary_cards(student_summaries, active_stu)
    billing_html = _render_billing_html(current_billing, session_billing)

    parts = []
    parts.append('<!DOCTYPE html>\n<html><head><meta charset="utf-8">'
                  '<meta name="viewport" content="width=device-width,initial-scale=1">')
    parts.append('<title>Sprecher \u2014 A1 Klassenzimmer</title>\n<style>')
    parts.append(_CSS)
    parts.append('</style></head>\n<body class="view-conversation">')

    parts.append(f"""
<div class="live-header">
  <div class="lh-left">
    <span class="lh-tag">Tag {cur_day}/{TOTAL_KANNS}</span>
    <span class="lh-sep">\u2502</span>
    <span class="lh-round">Runde {cur_round}/7{(": " + cur_round_name) if cur_round_name else ""}</span>
    <span class="lh-sep">\u2502</span>
    <span class="lh-kann" title="{cur_kann_text}">{kann_display}</span>
  </div>
  <div class="lh-right">{header_right}</div>
</div>
<div class="layout">
  <div class="transcript" id="transcript">
    {days_html}
  </div>
  <div class="splitter" id="splitter" aria-label="Resize summary panel" role="separator"></div>
  <div class="sidebar" id="sidebar">
    <div class="view-controls">
      <button class="vbtn" data-view="conversation">Conversation</button>
      <button class="vbtn" data-view="syllabus">Syllabus</button>
      <button class="vbtn" data-view="grader">+ Grader</button>
      <button class="vbtn" data-view="debug">Full Debug</button>
    </div>
    <div class="sidebar-section">
      <div class="sidebar-title">Run One Kann</div>
      <form class="run-form" method="post" action="/run">
        <input class="run-input" name="target" placeholder="165 or K163" autocomplete="off">
        <button class="run-button" type="submit">Run</button>
      </form>
      <div class="run-help">Runs one selected day/Kann only. It does not start the full course.</div>
    </div>
    <div class="sidebar-section" id="syllabus-section">
      <div class="sidebar-title">Current KB Syllabus</div>
      {kann_focus_html}
    </div>
    <div class="sidebar-section" id="syllabus-browser-section" data-static="syllabus-browser">
      <div class="sidebar-title">Full KB Syllabus Browser</div>
      {syllabus_browser_html}
    </div>
    <div class="sidebar-section" data-static="workbench">
      <div class="sidebar-title">Workbench Notes</div>
      <div class="workbench-card">
        <textarea id="workbench-notes" class="workbench-textarea" placeholder="Write while watching: KB relationships, word branches, grammar tools, teacher ideas..."></textarea>
        <div class="workbench-tools">
          <button type="button" class="workbench-button" data-workbench-action="insert-kann">Insert Current KB</button>
          <button type="button" class="workbench-button" data-workbench-action="clear">Clear</button>
        </div>
        <div class="run-help">Saved in this browser only. Live updates will not erase it.</div>
      </div>
    </div>
    <div class="sidebar-section">
      <div class="sidebar-title">Student Progress</div>
      {student_summary_html}
    </div>
    <div class="sidebar-section">
      <div class="sidebar-title">Billing</div>
      {billing_html}
    </div>
    <div class="sidebar-section">
      <div class="sidebar-title">Scorecard</div>
      <div class="scorecard-tools">
        <button class="scorecard-tool" data-day-action="collapse-all">Collapse Days</button>
        <button class="scorecard-tool" data-day-action="expand-all">Expand Days</button>
        <button class="scorecard-tool" data-day-action="latest">Latest</button>
      </div>
      <div class="scorecard-scroll">
        <table class="scorecard">
          <thead><tr><th>Tag</th><th>Kann</th>{stu_ths}</tr></thead>
          <tbody>{sc_rows}</tbody>
        </table>
      </div>
    </div>
    <div class="sidebar-section">
      <div class="sidebar-title">Status</div>
      <div class="status-text">{status}</div>
    </div>
  </div>
</div>
""")

    parts.append("<script>")
    parts.append(_JS)
    parts.append("</script></body></html>")
    return "".join(parts)


_OUTPUT_FILE_RE = re.compile(r"day(\d+)_K\d+\.json$")


def _output_file_day(path):
    match = _OUTPUT_FILE_RE.match(path.name)
    return int(match.group(1)) if match else 0


def load_existing_outputs():
    """Populate the live UI from saved output JSON without starting generation."""
    output_dir = BASE / "output"
    days = []
    for path in sorted(output_dir.glob("day*_K*.json"), key=_output_file_day):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"Skipping unreadable output {path.name}: {exc}")
            continue
        kann = payload.get("kann", {})
        day_num = int(payload.get("day") or _output_file_day(path))
        days.append({
            "day": day_num,
            "kann_id": kann.get("id", f"K{day_num:03d}"),
            "kann_text": kann.get("kann", ""),
            "category": kann.get("category", ""),
            "kann_focus": payload.get("kann_focus", {}),
            "rounds": payload.get("rounds", []),
            "summaries": payload.get("summaries", {}),
            "summary_calls": payload.get("summary_calls", {}),
            "wrapup_calls": payload.get("wrapup_calls", {}),
            "billing": payload.get("billing", make_billing_bucket()),
        })

    live["days"] = days
    live["student_summaries"] = {
        sid: load_optional(f"state/students/{sid}_summary.json", {})
        for sid in STUDENT_IDS
    }
    live["done"] = True

    if days:
        latest = days[-1]
        live["current_day"] = latest["day"]
        live["current_kann"] = latest["kann_id"]
        live["current_kann_text"] = latest["kann_text"]
        live["current_kann_focus"] = latest.get("kann_focus", {})
        live["status"] = f"Loaded {len(days)} saved conversation days. Use Run One Kann to generate a single day."
    else:
        live["status"] = "No saved conversations found. Use Run One Kann to generate a single day."


def resolve_run_target(target):
    value = str(target or "").strip().upper()
    if not value:
        raise ValueError("Enter a day number or Kann ID, for example 165 or K163.")
    if value.startswith("K"):
        for idx, kann in enumerate(all_kanns, start=1):
            if kann["id"].upper() == value:
                return idx, kann
        raise ValueError(f"Unknown Kann ID: {value}")
    if value.isdigit():
        day_num = int(value)
        if day_num < 1 or day_num > TOTAL_KANNS:
            raise ValueError(f"Day must be between 1 and {TOTAL_KANNS}.")
        return day_num, all_kanns[day_num - 1]
    raise ValueError("Use a day number like 165 or a Kann ID like K163.")


def start_single_day_run(target):
    day_num, kann = resolve_run_target(target)
    if not run_lock.acquire(blocking=False):
        return False, "A run is already active. Wait for it to finish before starting another."

    def worker():
        try:
            live["done"] = False
            live["status"] = f"Queued single run: day {day_num} — {kann['id']}"
            run_day(day_num, kann)
            live["done"] = True
            live["status"] = f"Finished single run: day {day_num} — {kann['id']}"
        except Exception as exc:
            print(f"\n  ERROR on single run day {day_num}: {exc}")
            traceback.print_exc()
            live["done"] = True
            live["status"] = f"ERROR day {day_num}: {exc}"
        finally:
            run_lock.release()

    threading.Thread(target=worker, daemon=True).start()
    return True, f"Started single run: day {day_num} — {kann['id']}"


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        query = parse_qs(parsed.query)
        include_static = query.get("poll", ["0"])[0] != "1"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(render_html(include_static=include_static).encode())

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/run":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            fields = parse_qs(body)
            target = fields.get("target", [""])[0]
            _, message = start_single_day_run(target)
            live["status"] = message
        except Exception as exc:
            live["status"] = f"Could not start run: {exc}"
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, *a): pass

def start_server(host="127.0.0.1", port=8787):
    srv = HTTPServer((host, port), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv

# ── prompt builders ────────────────────────────────────────────────
def build_teacher_prompt(kann, kann_focus, round_frame, day, student_name, teacher_memories, classroom_context, interstitial=""):
    persona = teacher_pers["system_prompt"]
    canon_block = (
        f"Today's Kannbeschreibung: {kann['kann']}\n"
        f"Category: {kann.get('category','')}\n\n"
        f"{format_kann_focus_for_prompt(kann_focus)}"
    )
    round_block = f"Round {round_frame['round']} of 7: {round_frame['name']}.\n{round_frame['teacher_instruction']}"

    # memories of all students
    mem_lines = []
    for sid, mem in teacher_memories.items():
        if mem:
            mem_lines.append(f"Memory of {STUDENT_NAMES.get(sid,sid)}: {json.dumps(mem, ensure_ascii=False)[:300]}")
    memory_block = "\n".join(mem_lines) if mem_lines else "Day 1 — first meeting with all students."

    day_block = bridges["day_open"]["teacher_injection_day1"] if day == 1 else bridges["day_open"]["teacher_injection_returning"].replace("{days_completed}", str(day-1))

    # what other students said this round
    class_block = ""
    if classroom_context:
        class_block = "CLASSROOM CONTEXT (what other students said this round):\n" + "\n".join(
            f"  {STUDENT_NAMES.get(s,s)}: {msg}" for s, msg in classroom_context
        )

    full = f"{persona}\n\n--- CANON ---\n{canon_block}\n\n--- ROUND ---\n{round_block}\n\n--- MEMORY ---\n{memory_block}\n\n--- DAY ---\n{day_block}"
    if class_block:
        full += f"\n\n--- CLASSROOM ---\n{class_block}"
    if interstitial:
        full += f"\n\n--- INTERSTITIAL ---\n{interstitial}"
    turn_rules = [
        f"Speak only to {student_name} in this turn.",
        "Do not call on a different student to answer inside this turn.",
        f"If you use a name for the task prompt, it must be {student_name}. Do not begin a task prompt with another student's name.",
    ]
    if round_frame["round"] < 7:
        turn_rules.append("The lesson is not over yet. Do not say goodbye, preview next week, or wrap up the whole class.")
    else:
        turn_rules.append("Give this student one final test-like chance to perform the Kannbeschreibung before you close warmly.")
    full += "\n\n--- TURN RULES ---\n" + "\n".join(f"- {rule}" for rule in turn_rules)
    full += f"\n\nYou are now speaking to {student_name}."
    full += "\nOutput only what Frau Weber says aloud. No brackets, no stage directions, no narration."
    return full

def build_student_prompt(student_data, learned_state, student_summary, classroom_context, kann_focus):
    base = f"{student_data['base_persona']}\n\n{student_data['personality']}\n\n{student_data.get('classmates','')}\n\n{student_data['generation_rules']}"
    base += "\n\nRespond only with what you say aloud. No brackets, no stage directions, no narration."

    # what classmates said
    if classroom_context:
        base += "\n\nWHAT YOUR CLASSMATES SAID THIS ROUND:\n" + "\n".join(
            f"  {STUDENT_NAMES.get(s,s)}: {msg}" for s, msg in classroom_context
        )

    vocab_sections = []
    stable_vocab = _format_learning_bucket(
        "Stable vocabulary",
        student_summary.get("stable_vocabulary", []),
        "word",
    )
    unstable_vocab = _format_learning_bucket(
        "Unstable vocabulary",
        student_summary.get("unstable_vocabulary", []),
        "word",
    )
    if stable_vocab:
        vocab_sections.append(stable_vocab)
    if unstable_vocab:
        vocab_sections.append(unstable_vocab)
    if kann_focus.get("wortfeld_samples"):
        vocab_sections.append(
            "Today's target vocabulary:\n" +
            "\n".join(
                f"  - {sample['field']}: {', '.join(sample['examples'])}"
                for sample in kann_focus["wortfeld_samples"]
            )
        )

    grammar_sections = []
    stable_grammar = _format_learning_bucket(
        "Stable grammar",
        student_summary.get("stable_grammar", []),
        "rule",
    )
    unstable_grammar = _format_learning_bucket(
        "Unstable grammar",
        student_summary.get("unstable_grammar", []),
        "rule",
    )
    if stable_grammar:
        grammar_sections.append(stable_grammar)
    if unstable_grammar:
        grammar_sections.append(unstable_grammar)
    if kann_focus.get("grammar_targets"):
        grammar_sections.append(
            "Today's target grammar:\n" +
            "\n".join(f"  - {item}" for item in kann_focus["grammar_targets"])
        )

    errors = student_summary.get("persistent_errors", [])
    focus_block = "TODAY'S KANN FOCUS:\n" + format_kann_focus_for_prompt(kann_focus)
    recent_kanns = student_summary.get("recent_kanns", [])
    recent_block = ""
    if recent_kanns:
        recent_block = "RECENT KANN RESULTS:\n" + "\n".join(
            f"  - {item['kann_id']} ({item.get('result','')} on day {item.get('day','?')})"
            for item in recent_kanns
        )

    if learned_state.get("day", 0) > 0:
        overlay = overlay_tmpl["template"]
        overlay = overlay.replace("{base_persona}", base)
        overlay = overlay.replace("{days_completed}", str(student_summary.get("days_completed", learned_state.get("day", 0))))
        overlay = overlay.replace("{vocabulary_section}", "\n\n".join(vocab_sections) if vocab_sections else "")
        overlay = overlay.replace("{grammar_section}", "\n\n".join(grammar_sections) if grammar_sections else "")
        overlay = overlay.replace("{errors_section}", "Errors:\n" + "\n".join(f"  - {e}" for e in errors) if errors else "")
        overlay = overlay.replace("{emotional_section}", f"Feeling: {student_summary.get('emotional_state', '')}")
        extra_blocks = [focus_block]
        if recent_block:
            extra_blocks.append(recent_block)
        return overlay + "\n\n" + "\n\n".join(extra_blocks)

    return base + "\n\n" + focus_block

def build_grader_prompt(kann, kann_focus, round_frame, day, teacher_msg, student_msg, prior_progress):
    sys_p = grader_round["system_prompt"]
    user_p = grader_round["user_template"]
    user_p = user_p.replace("{kann_text}", kann["kann"])
    wordfield_text = "\n".join(
        f"- {sample['field']}: {', '.join(sample['examples'])}"
        for sample in kann_focus.get("wortfeld_samples", [])
    ) or ", ".join(kann_focus.get("wortfeld_targets", [])) or "No explicit target Wortfeld."
    speech_act_text = "\n".join(f"- {item}" for item in kann_focus.get("speech_acts", [])) or "No explicit target speech acts."
    relationship_text = "\n".join(
        f"- {rel.get('name', rel.get('id', 'relationship'))}: {rel.get('summary', '')} Grader: {rel.get('grader_guidance', '')}"
        for rel in kann_focus.get("global_relationships", [])
    ) or "No explicit global KB relationships."
    user_p = user_p.replace("{wortfeld}", wordfield_text)
    user_p = user_p.replace("{sprachhandlungen}", speech_act_text)
    user_p = user_p.replace("{kann_relationships}", relationship_text)
    user_p = user_p.replace("{current_day}", str(day))
    user_p = user_p.replace("{current_round}", str(round_frame["round"]))
    user_p = user_p.replace("{round_name}", round_frame["name"])
    user_p = user_p.replace("{prior_progress}", prior_progress)
    user_p = user_p.replace("{teacher_message}", teacher_msg)
    user_p = user_p.replace("{student_message}", student_msg)
    return sys_p, user_p


def build_note_taker_prompt(kann, kann_focus, round_frame, teacher_msg, student_msg):
    if not NOTE_TAKER_ENABLED or not note_taker_tmpl:
        return None, None
    sys_p = note_taker_tmpl.get("system_prompt", "")
    user_p = note_taker_tmpl.get("user_template", "")
    user_p = user_p.replace("{kann_text}", kann["kann"])
    user_p = user_p.replace("{kann_focus}", format_kann_focus_for_prompt(kann_focus))
    user_p = user_p.replace("{current_round}", str(round_frame["round"]))
    user_p = user_p.replace("{round_name}", round_frame["name"])
    user_p = user_p.replace("{teacher_message}", teacher_msg)
    user_p = user_p.replace("{student_message}", student_msg)
    return sys_p, user_p


def run_note_taker(kann, kann_focus, round_frame, teacher_msg, student_msg, day_live):
    sys_p, user_p = build_note_taker_prompt(kann, kann_focus, round_frame, teacher_msg, student_msg)
    if not sys_p or not user_p:
        return None, None
    note_call = chat_from_config("note_taker", [
        {"role": "system", "content": sys_p},
        {"role": "user", "content": user_p},
    ], return_meta=True)
    note_raw = note_call["content"]
    add_call_meta_to_billing(day_live["billing"], note_call["meta"])
    try:
        note = parse_json(note_raw)
    except:
        note = {
            "kb_de": kann["kann"],
            "kb_de_simple": "",
            "kb_en_simple": "",
            "exchange_note": clean_spoken_text(note_raw),
        }
    return note, {
        "prompt": f"SYSTEM:\n{sys_p}\n\nUSER:\n{user_p}",
        "call": note_call["meta"],
    }


_GRADER_VERDICTS = ("ON TRACK", "NEEDS REDIRECT", "DRIFTING")


def normalize_grader_result(grader_result):
    if not isinstance(grader_result, dict):
        grader_result = {"verdict": "parse_error", "grammar_notes": [str(grader_result)]}
    verdict_raw = str(grader_result.get("verdict", "")).strip()
    if verdict_raw == "parse_error":
        return grader_result
    verdict_upper = verdict_raw.upper()
    for label in _GRADER_VERDICTS:
        if verdict_upper == label or verdict_upper.startswith(label + ".") or verdict_upper.startswith(label + " ") or verdict_upper.startswith(label + "-"):
            detail = verdict_raw[len(label):].lstrip(" .:-")
            grader_result["verdict"] = label
            if detail:
                grader_result["verdict_raw"] = verdict_raw
                if not grader_result.get("steering"):
                    grader_result["steering"] = detail
            return grader_result
    if verdict_raw:
        grader_result["verdict_raw"] = verdict_raw
    grader_result["verdict"] = "NEEDS REDIRECT" if grader_result.get("canon_aligned") is False else "DRIFTING"
    if verdict_raw and not grader_result.get("steering"):
        grader_result["steering"] = verdict_raw
    return grader_result


# ── run one day (one Kann, all students) ───────────────────────────
def run_day(day_num, kann):
    # load state
    teacher_mems = {sid: load(f"state/teacher/memory_{sid}.json") for sid in STUDENT_IDS}
    learned = {sid: load(f"state/students/{sid}_learned.json") for sid in STUDENT_IDS}
    progress = load("state/grader/progress.json")
    course_state = load("state/course/course_state.json")
    kann_progress = load_optional("state/course/kann_progress.json", {
        "students": {sid: {} for sid in STUDENT_IDS}
    })
    for sid in STUDENT_IDS:
        progress.setdefault(sid, [])
        kann_progress.setdefault("students", {}).setdefault(sid, {})
    course_state.setdefault("current_day", {})
    course_state.setdefault("areas_covered", {})
    for sid in STUDENT_IDS:
        course_state["current_day"].setdefault(sid, 0)
        course_state["areas_covered"].setdefault(sid, [])
    student_summaries = {
        sid: load_optional(
            f"state/students/{sid}_summary.json",
            build_student_summary(sid, learned[sid], progress.get(sid, [])),
        )
        for sid in STUDENT_IDS
    }
    kann_focus = derive_kann_focus(kann)

    day_live = {
        "day": day_num, "kann_id": kann["id"], "kann_text": kann["kann"],
        "category": kann.get("category", ""), "kann_focus": kann_focus,
        "rounds": [], "summaries": {}, "billing": make_billing_bucket(),
        "summary_calls": {}, "wrapup_calls": {}
    }
    full_kann_label = f'{kann["id"]}: {kann["kann"]}'
    live["days"] = [day for day in live["days"] if day.get("day") != day_num]
    live["days"].append(day_live)
    live["days"].sort(key=lambda day: day.get("day", 0))
    live["current_day"] = day_num
    live["current_kann"] = kann["id"]
    live["current_kann_text"] = kann["kann"]
    live["current_kann_focus"] = kann_focus
    live["student_summaries"] = student_summaries
    live["status"] = f"Tag {day_num}/{TOTAL_KANNS} \u2014 {full_kann_label} \u2014 Starting..."

    print(f"\n{'='*70}")
    print(f"  Tag {day_num} \u2014 {full_kann_label}")
    print(f"{'='*70}")

    # per-student conversation histories (teacher sees all, student sees own)
    teacher_history = []  # all exchanges in order
    student_histories = {sid: [] for sid in STUDENT_IDS}
    grader_reports = {sid: [] for sid in STUDENT_IDS}
    interstitial_text = ""

    for rf in rounds_tmpl:
        rnd = rf["round"]
        live["status"] = f"Tag {day_num} \u2014 Runde {rnd}/7: {rf['name']} \u2014 {full_kann_label}"
        live["current_round"] = rnd
        live["current_round_name"] = rf["name"]
        round_live = {"round": rnd, "name": rf["name"], "exchanges": []}
        day_live["rounds"].append(round_live)

        # This round's classroom context builds up as each student speaks
        round_context = []

        for sid in STUDENT_IDS:
            sdata = student_configs[sid]
            sname = sdata["name"]
            live["active_student"] = sname

            # ── Teacher speaks to this student ────────────────────
            t_prompt = build_teacher_prompt(
                kann, kann_focus, rf, day_num, sname, teacher_mems, round_context, interstitial_text
            )
            t_messages = [{"role": "system", "content": t_prompt}]

            # teacher conversation history (all students)
            for ex in teacher_history:
                t_messages.append({"role": "assistant", "content": f"[To {ex['student_name']}] {ex['teacher_msg']}"})
                t_messages.append({"role": "user", "content": f"[{ex['student_name']}] {ex['student_msg']}"})

            if rnd == 1 and not teacher_history:
                t_messages.append({"role": "user", "content": f"Begin the lesson. Address {sname} first."})

            teacher_call = chat_from_config("teacher", t_messages, return_meta=True)
            teacher_msg = clean_spoken_text(teacher_call["content"])
            add_call_meta_to_billing(day_live["billing"], teacher_call["meta"])
            print(f"\n  [R{rnd} {rf['name']}] Lehrerin \u2192 {sname}: {teacher_msg}")

            # ── Student responds ──────────────────────────────────
            s_prompt = build_student_prompt(
                sdata, learned[sid], student_summaries[sid], round_context, kann_focus
            )
            s_messages = [{"role": "system", "content": s_prompt}]
            for ex in student_histories[sid]:
                s_messages.append({"role": "user", "content": ex["teacher_msg"]})
                s_messages.append({"role": "assistant", "content": ex["student_msg"]})
            s_messages.append({"role": "user", "content": teacher_msg})

            student_call = chat(
                sdata.get("api", "openai"),
                sdata["model"],
                s_messages,
                temperature=sdata.get("temperature", 0.8),
                max_tokens=sdata.get("max_tokens", 500),
                base_url=sdata.get("base_url"),
                api_key_env=sdata.get("api_key_env"),
                step_name=f"student:{sid}",
                return_meta=True,
                request_timeout=sdata.get("request_timeout"),
            )
            student_msg = clean_spoken_text(student_call["content"])
            add_call_meta_to_billing(day_live["billing"], student_call["meta"])
            print(f"  {sname}: {student_msg}")

            observer_note = None
            observer_prompt = ""
            observer_call = {}
            if NOTE_TAKER_ENABLED:
                try:
                    observer_note, observer_meta = run_note_taker(
                        kann, kann_focus, rf, teacher_msg, student_msg, day_live
                    )
                    if observer_meta:
                        observer_prompt = observer_meta["prompt"]
                        observer_call = observer_meta["call"]
                    if observer_note:
                        note_line = observer_note.get("reader_note", "") if isinstance(observer_note, dict) else str(observer_note)
                        print(f"  Notes \u2192 {NOTE_TAKER_NAME}: {note_line[:120]}")
                except Exception as exc:
                    observer_note = {
                        "german_focus": "",
                        "english_meaning": "",
                        "context": "",
                        "reader_note": f"Note-taker unavailable: {type(exc).__name__}: {exc}",
                    }

            # ── Grade ─────────────────────────────────────────────
            prior_progress_text = summarize_prior_progress(progress.get(sid, []))
            g_sys, g_user = build_grader_prompt(
                kann, kann_focus, rf, day_num, teacher_msg, student_msg,
                prior_progress_text
            )
            try:
                grader_call = chat_from_config("grader_round", [
                    {"role": "system", "content": g_sys},
                    {"role": "user", "content": g_user}
                ], return_meta=True)
                grader_raw = grader_call["content"]
                add_call_meta_to_billing(day_live["billing"], grader_call["meta"])

                try:
                    grader_result = parse_json(grader_raw)
                except:
                    grader_result = {"verdict": "parse_error", "wortfeld_used": [], "grammar_notes": [grader_raw], "steering": "proceed", "canon_aligned": True, "sprachhandlung": ""}
            except Exception as exc:
                grader_call = {
                    "meta": _build_call_meta("grader_round", runtime_cfg["models"]["grader_round"].get("api", "openai"), runtime_cfg["models"]["grader_round"].get("model", "unknown"), {}),
                }
                grader_raw = f"{type(exc).__name__}: {exc}"
                grader_result = {
                    "canon_aligned": True,
                    "wortfeld_used": [],
                    "sprachhandlung": "",
                    "grammar_notes": [grader_raw],
                    "progress_vs_prior": "",
                    "verdict": "NEEDS REDIRECT",
                    "steering": "Grader call failed or timed out; continue the classroom run and inspect this exchange manually.",
                }
            grader_result = normalize_grader_result(grader_result)

            print(f"  Grader \u2192 {sname}: {grader_result.get('verdict','')}")

            # ── Record ────────────────────────────────────────────
            exchange = {
                "student": sid, "teacher_msg": teacher_msg, "student_msg": student_msg,
                "grader": grader_result,
                "teacher_prompt": t_prompt, "student_prompt": s_prompt,
                "grader_prompt": f"SYSTEM:\n{g_sys}\n\nUSER:\n{g_user}",
                "teacher_call": teacher_call["meta"],
                "student_call": student_call["meta"],
                "grader_call": grader_call["meta"],
                "observer_note": observer_note,
                "observer_prompt": observer_prompt,
                "observer_call": observer_call,
            }
            round_live["exchanges"].append(exchange)

            teacher_history.append({"student_name": sname, "student_id": sid, "teacher_msg": teacher_msg, "student_msg": student_msg})
            student_histories[sid].append({"teacher_msg": teacher_msg, "student_msg": student_msg})
            grader_reports[sid].append(grader_result)
            round_context.append((sid, student_msg))

        # interstitial for next round
        interstitial_text = ""
        # check if any student needs redirect
        any_redirect = any(
            ex.get("grader", {}).get("steering", "") in ("gentle_redirect", "explicit_reteach")
            for ex in round_live["exchanges"]
        )
        interstitial_key = rf.get("interstitial_after", "")
        if any_redirect and "correction_bridge" in bridges:
            interstitial_text = bridges["correction_bridge"]["teacher_injection"]
        elif interstitial_key == "round_transition" and "round_transition" in bridges:
            interstitial_text = bridges["round_transition"]["teacher_injection"]
        elif interstitial_key == "day_close" and "day_close" in bridges:
            interstitial_text = bridges["day_close"]["teacher_injection"]

    # ── Day summaries per student ─────────────────────────────────
    live["current_round"] = 0
    live["current_round_name"] = ""
    live["active_student"] = ""
    live["status"] = f"Tag {day_num} \u2014 Summarizing \u2014 {full_kann_label}"
    for sid in STUDENT_IDS:
        summary_user = grader_day["user_template"]
        summary_user = summary_user.replace("{student_name}", STUDENT_NAMES[sid])
        summary_user = summary_user.replace("{current_day}", str(day_num))
        summary_user = summary_user.replace("{subject_area}", kann.get("category", ""))
        summary_user = summary_user.replace("{kann_text}", kann["kann"])
        summary_user = summary_user.replace("{all_grader_reports}", json.dumps(grader_reports[sid], ensure_ascii=False))
        summary_user = summary_user.replace("{prior_progress}", summarize_prior_progress(progress.get(sid, []), limit=6))
        summary_call = chat_from_config("grader_day", [
            {"role": "system", "content": grader_day["system_prompt"]},
            {"role": "user", "content": summary_user}
        ], return_meta=True)
        summary_raw = summary_call["content"]
        add_call_meta_to_billing(day_live["billing"], summary_call["meta"])

        try:
            day_summary = parse_json(summary_raw)
        except:
            day_summary = {"day": day_num, "kann_result": "teilweise", "session_highlight": summary_raw,
                           "vocabulary_learned": [], "grammar_learned": [], "persistent_errors": [],
                           "improvements_from_prior": [], "emotional_state": ""}

        day_live["summaries"][sid] = day_summary
        day_live["summary_calls"][sid] = summary_call["meta"]
        print(f"  Summary {STUDENT_NAMES[sid]}: {day_summary.get('kann_result','')} \u2014 {day_summary.get('session_highlight','')[:60]}")

    # ── Teacher wrapup per student ────────────────────────────────
    for sid in STUDENT_IDS:
        wrapup_user = wrapup_tmpl["user_template"]
        wrapup_user = wrapup_user.replace("{student_name}", STUDENT_NAMES[sid])
        wrapup_user = wrapup_user.replace("{current_day}", str(day_num))
        wrapup_user = wrapup_user.replace("{subject_area}", kann.get("category", ""))
        wrapup_user = wrapup_user.replace("{conversation}", json.dumps(
            [h for h in teacher_history if h["student_id"] == sid], ensure_ascii=False))
        wrapup_user = wrapup_user.replace("{grader_reports}", json.dumps(grader_reports[sid], ensure_ascii=False))
        wrapup_user = wrapup_user.replace("{prior_memory}", json.dumps(teacher_mems[sid], ensure_ascii=False))
        wrapup_call = chat_from_config("teacher_wrapup", [
            {"role": "system", "content": wrapup_tmpl["system_prompt"]},
            {"role": "user", "content": wrapup_user}
        ], return_meta=True)
        wrapup_raw = wrapup_call["content"]
        add_call_meta_to_billing(day_live["billing"], wrapup_call["meta"])

        try:
            new_mem = parse_json(wrapup_raw)
        except:
            new_mem = {"raw": wrapup_raw}
        save(f"state/teacher/memory_{sid}.json", new_mem)
        day_live["wrapup_calls"][sid] = wrapup_call["meta"]

        # update learned state
        ds = day_live["summaries"][sid]
        new_learned = dict(learned[sid])
        new_learned["day"] = day_num
        for v in ds.get("vocabulary_learned", []):
            new_learned.setdefault("vocabulary_acquired", []).append(v)
        for g in ds.get("grammar_learned", []):
            new_learned.setdefault("grammar_acquired", []).append(g)
        new_learned["persistent_errors"] = ds.get("persistent_errors", learned[sid].get("persistent_errors", []))
        new_learned["emotional_state"] = ds.get("emotional_state", "")
        new_learned.setdefault("kannbeschreibungen_attempted", {})[kann["id"]] = {
            "day": day_num, "result": ds.get("kann_result", "teilweise")
        }
        save(f"state/students/{sid}_learned.json", new_learned)

        progress.setdefault(sid, []).append(ds)
        student_summaries[sid] = build_student_summary(sid, new_learned, progress[sid])
        save(f"state/students/{sid}_summary.json", student_summaries[sid])
        kann_progress["students"][sid][kann["id"]] = build_kann_progress_entry(
            kann, kann_focus, day_num, ds, grader_reports[sid]
        )
        live["student_summaries"] = student_summaries

    save("state/grader/progress.json", progress)
    save("state/course/kann_progress.json", kann_progress)
    for sid in STUDENT_IDS:
        course_state["current_day"][sid] = day_num
        area = kann.get("category", "")
        if area and area not in course_state["areas_covered"][sid]:
            course_state["areas_covered"][sid].append(area)
    save("state/course/course_state.json", course_state)

    # save day output
    save(f"output/day{day_num}_{kann['id']}.json", {
        "day": day_num, "kann": kann, "kann_focus": kann_focus,
        "rounds": day_live["rounds"],
        "summaries": day_live["summaries"],
        "summary_calls": day_live["summary_calls"],
        "wrapup_calls": day_live["wrapup_calls"],
        "billing": day_live["billing"],
    })
    billing = day_live["billing"]
    print(
        "  Billing:"
        f" {_format_usd(billing.get('estimated_cost_usd', 0.0))}"
        f" | {billing.get('calls', 0)} calls"
        f" | {billing.get('prompt_tokens', 0)} prompt"
        f" | {billing.get('completion_tokens', 0)} completion"
    )

    live["status"] = f"Tag {day_num}/{TOTAL_KANNS} \u2014 {full_kann_label} \u2014 DONE"

# ── run full course ────────────────────────────────────────────────
def run_course(start_day=1, end_day=None):
    if end_day is None:
        end_day = TOTAL_KANNS
    end_day = min(end_day, TOTAL_KANNS)

    for i in range(start_day - 1, end_day):
        kann = all_kanns[i]
        try:
            run_day(i + 1, kann)
        except Exception as e:
            print(f"\n  ERROR on day {i+1}: {e}")
            traceback.print_exc()
            live["status"] = f"ERROR day {i+1}: {e}"
            continue

    total_billing = _collect_billing(live.get("days", []))
    print(
        "\nSession billing:"
        f" {_format_usd(total_billing.get('estimated_cost_usd', 0.0))}"
        f" | {total_billing.get('calls', 0)} calls"
        f" | {total_billing.get('prompt_tokens', 0)} prompt"
        f" | {total_billing.get('completion_tokens', 0)} completion"
    )
    live["status"] = f"COMPLETE \u2014 Days {start_day}-{end_day}"
    live["done"] = True

# ── entry ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Force unbuffered output
    print = functools.partial(print, flush=True)

    server_cfg = runtime_cfg.get("server", {})
    host = os.environ.get("HOST", server_cfg.get("host", "0.0.0.0"))
    port = int(os.environ.get("PORT", server_cfg.get("port", 8787)))

    print(f"HTTP server: http://{host}:{port}")
    start_server(host, port)
    os.chdir(BASE)

    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        load_existing_outputs()
        print(f"Loaded {len(live['days'])} saved conversation days.")
        print(f"Serve-only mode. Run individual days from http://127.0.0.1:{port}")
        print("Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopped.")
        sys.exit(0)

    # args: python3 runner.py [start_day] [end_day]
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    end = int(sys.argv[2]) if len(sys.argv) > 2 else TOTAL_KANNS
    print(f"Running days {start}-{end} ({end - start + 1} Kannbeschreibungen)")
    print(f"Students: {', '.join(STUDENT_NAMES[sid] for sid in STUDENT_IDS)}")
    run_course(start, end)

    print(f"\nDone. http://127.0.0.1:{port}")
    print("Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopped.")
