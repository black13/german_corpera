"""
Generate lesson seed drafts via DeepSeek.

Usage:
  .venv/bin/python3 tools/seed_gen.py K001       (one KB)
  .venv/bin/python3 tools/seed_gen.py K001 K005   (range)
  .venv/bin/python3 tools/seed_gen.py --ask "how should K001 be taught?"

Output goes to plans/generated/seed_Kxxx.json for review.
"""
import json, os, sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from openai import OpenAI


def get_kb(kb_id):
    data = json.loads((BASE / "canon/kannbeschreibungen_full.json").read_text())
    for k in data["kannbeschreibungen"]:
        if k["id"] == kb_id.upper():
            return k
    return None


def kb_ids_in_range(start, end):
    data = json.loads((BASE / "canon/kannbeschreibungen_full.json").read_text())
    ids = []
    for k in data["kannbeschreibungen"]:
        num = int(k["id"][1:])
        if start <= num <= end:
            ids.append(k["id"])
    return ids


DUAL_EXAMPLE = {
    "K084": {
        "compact_form": "short everyday text + pick out single words + understand one key item",
        "scene": {"big": "everyday written information in public life", "small": "a sign, notice, timetable line, or form entry"},
        "target_speech_acts": ["einzelne Wörter erkennen", "die wichtigste Information nennen"],
        "target_utterances": ["Hier steht ...", "Das Wort bedeutet ...", "Ich sehe ..."],
        "target_grammar": ["Nomen erkennen", "Zahlen erkennen", "kurze Hauptsätze"],
        "drift_paths": [
            {"failure": "tries to read and understand the whole text", "recovery": "Lesen Sie nur das erste Wort. Was steht da?"}
        ],
        "teacher_notes": "Start from one visible word. Do not require full-sentence comprehension."
    },
    "K176": {
        "compact_form": "hotel info board + foreign term + translate to German for guest",
        "scene": {"big": "hotel lobby / reception area", "small": "information board with foreign-language terms"},
        "target_speech_acts": ["Aufschrift lesen", "Bedeutung auf Deutsch erklären", "Verständnis sichern"],
        "target_utterances": ["Das bedeutet Frühstück.", "Das Frühstück ist von sieben bis zehn Uhr.", "Verstehen Sie?"],
        "target_grammar": ["Das bedeutet + Nomen", "von ... bis (Zeitangaben)", "hier, dort, links, rechts"],
        "drift_paths": [
            {"failure": "starts general hotel conversation instead of mediating", "recovery": "Wir sind an der Informationstafel. Der Gast zeigt auf ein Wort. Was bedeutet es?"}
        ],
        "teacher_notes": "Start in medias res at the info board. The student is a hotel employee. Der Gegenstand bleibt."
    }
}

SEED_PROMPT = """You are a CEFR A1 German curriculum designer and test-preparation specialist.

TASK: Write a lesson seed for one Kannbeschreibung.

CONTEXT:
- This is for A1 learners at the very beginning of German.
- The lesson seed is read by an LLM teacher agent (Frau Weber) and an LLM grader.
- The seed must make the instructional target concrete, not abstract.
- Follow the scene-to-language ladder: big scene -> small scene -> speech act -> utterance -> lexical field -> grammar.
- Grammar must come LAST, derived from the utterance need. Never choose grammar first.

RULES:
- For written skills: identify the PHYSICAL CARRIER (Schild, Aufschrift, Formular, Fahrplan, Tafel, Aushang, Notiz...).
  The carrier stays visible ("der Gegenstand bleibt"). This is the key to A1 difficulty.
- For spoken skills: the input disappears. The learner must hold it in memory.
- Drift paths must be concrete: what does the learner actually DO wrong, and what does the teacher actually SAY to redirect.
- Teacher recovery moves must be in German (the teacher speaks German).
- Target utterances must be 3-6 prototype A1-sized sentences the learner should produce.
- Core words should be 8-15 concrete nouns, verbs, and formulaic phrases.
- All output must be strictly valid JSON with no commentary.

EXAMPLES OF GOOD SEEDS:

Example 1 (Rezeption schriftlich):
```json
{dual_example_k084}
```

Example 2 (Sprachmittlung mündlich):
```json
{dual_example_k176}
```

NOW PRODUCE A SEED FOR THIS KANNBESCHREIBUNG:

ID: {kb_id}
Category: {category}
Text: {kb_text}

Output ONLY valid JSON following the schema above. No markdown fences, no commentary."""


def generate_seed(kb, client):
    prompt = SEED_PROMPT.format(
        dual_example_k084=json.dumps(DUAL_EXAMPLE["K084"], indent=2, ensure_ascii=False),
        dual_example_k176=json.dumps(DUAL_EXAMPLE["K176"], indent=2, ensure_ascii=False),
        kb_id=kb["id"],
        category=kb.get("category", ""),
        kb_text=kb["kann"],
    )
    r = client.chat.completions.create(
        model="deepseek-reasoner",
        messages=[
            {"role": "user", "content": prompt}
        ],
        temperature=0.3,
        max_tokens=2000,
    )
    raw = r.choices[0].message.content or ""
    # Strip markdown fences if present
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines)
    try:
        seed = json.loads(raw)
    except json.JSONDecodeError:
        print(f"  WARNING: Could not parse JSON. Raw output saved.")
        seed = {"_raw": raw, "_parse_error": True}
    seed["kb_id"] = kb["id"]
    seed["kb_text_de"] = kb["kann"]
    return seed


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    # --ask mode for freeform questions
    if sys.argv[1] == "--ask":
        question = " ".join(sys.argv[2:])
        client = OpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            base_url="https://api.deepseek.com",
        )
        r = client.chat.completions.create(
            model="deepseek-reasoner",
            messages=[{"role": "user", "content": question}],
            temperature=0.5,
            max_tokens=2000,
        )
        print(r.choices[0].message.content or "")
        return

    # KB ID mode
    kb_ids = []
    for arg in sys.argv[1:]:
        arg = arg.upper()
        if arg.startswith("K") and arg[1:].isdigit():
            kb_ids.append(arg)
        elif arg.isdigit():
            kb_ids.extend(kb_ids_in_range(int(arg), int(arg)))

    if not kb_ids:
        print("No valid KB IDs found.")
        sys.exit(1)

    client = OpenAI(
        api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
        base_url="https://api.deepseek.com",
    )

    out_dir = BASE / "plans" / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)

    for kid in kb_ids:
        kb = get_kb(kid)
        if not kb:
            print(f"  {kid}: NOT FOUND")
            continue
        print(f"  {kid} [{kb.get('category','')}]: {kb['kann'][:80]}...")
        seed = generate_seed(kb, client)
        path = out_dir / f"seed_{kid}.json"
        path.write_text(json.dumps(seed, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"    -> saved {path}")

    print(f"\nGenerated {len(kb_ids)} seeds in {out_dir}/")


if __name__ == "__main__":
    main()
