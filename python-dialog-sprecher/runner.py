"""
runner.py — Disposable. Reads JSON, calls APIs, writes JSON, serves HTTP.
Contains ZERO rules about German. All meaning is in the JSON files.
"""
import json, os, sys, threading, time, traceback
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from openai import OpenAI

BASE = Path(__file__).parent

# ── load JSON helpers ──────────────────────────────────────────────
def load(path):
    with open(BASE / path) as f:
        return json.load(f)

def save(path, data):
    p = BASE / path
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ── API clients ────────────────────────────────────────────────────
openai_client = OpenAI()
deepseek_client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
    base_url="https://api.deepseek.com"
)

def chat(api, model, messages, temperature=0.8):
    client = deepseek_client if api == "deepseek" else openai_client
    r = client.chat.completions.create(
        model=model, messages=messages, temperature=temperature, max_tokens=500
    )
    return r.choices[0].message.content

def parse_json(raw):
    """Strip markdown code fences before parsing JSON."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
    if s.endswith("```"):
        s = s[:-3]
    return json.loads(s.strip())

# ── load all canon + prompts (read-only) ───────────────────────────
canon_kann   = load("canon/kannbeschreibungen.json")["kannbeschreibungen"]
canon_bewert = load("canon/bewertung.json")
canon_sprach = load("canon/sprachhandlungen.json")
canon_wort   = load("canon/wortfelder.json")
course_struct= load("plans/course_structure.json")
teacher_pers = load("prompts/teacher/persona.json")
planner_tmpl = load("prompts/teacher/planner.json")
rounds_tmpl  = load("prompts/teacher/round_frames.json")["rounds"]
wrapup_tmpl  = load("prompts/teacher/wrapup.json")
bridges      = load("prompts/interstitials/bridges.json")
grader_round = load("prompts/grader/per_round.json")
grader_day   = load("prompts/grader/day_summary.json")
overlay_tmpl = load("prompts/students/learning_overlay.json")

ALL_STUDENTS = ["marta", "james", "yuki"]
ALL_AREAS = [a["id"] for a in course_struct["subject_areas"]]
NUM_DAYS = len(ALL_AREAS)  # 7

# ── live state (shared with HTTP server) ───────────────────────────
live = {
    "status": "starting",
    "current_student": "",
    "current_day": 0,
    "students": {},   # student_id -> {"name": ..., "days": [{day, area, plan, rounds, summary}]}
    "scorecard": {},  # student_id -> {area_id -> "bestanden"|"teilweise"|"nicht_bestanden"}
    "done": False
}

# ── HTTP server ────────────────────────────────────────────────────
def _esc(s):
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def render_html():
    s = live
    status = _esc(s["status"])

    # ── scorecard table ───────────────────────────────────────────
    scorecard_html = '<table class="score"><tr><th>Kannbeschreibung</th>'
    for sid in ALL_STUDENTS:
        name = s["students"].get(sid, {}).get("name", sid)
        scorecard_html += f'<th>{_esc(name)}</th>'
    scorecard_html += '</tr>'

    area_names = {a["id"]: a["name"] for a in course_struct["subject_areas"]}
    for area_id in ALL_AREAS:
        scorecard_html += f'<tr><td>{_esc(area_names.get(area_id, area_id))}</td>'
        for sid in ALL_STUDENTS:
            result = s["scorecard"].get(sid, {}).get(area_id, "—")
            cls = {"bestanden": "pass", "teilweise": "partial", "nicht_bestanden": "fail"}.get(result, "pending")
            label = {"bestanden": "bestanden", "teilweise": "teilweise", "nicht_bestanden": "nicht best.", "—": "—"}.get(result, result)
            scorecard_html += f'<td class="{cls}">{label}</td>'
        scorecard_html += '</tr>'
    scorecard_html += '</table>'

    # ── per-student days ──────────────────────────────────────────
    students_html = ""
    for sid in ALL_STUDENTS:
        sdata = s["students"].get(sid, {"name": sid, "days": []})
        students_html += f'<div class="student-section"><h2>{_esc(sdata["name"])}</h2>'

        for ddata in sdata.get("days", []):
            day_num = ddata.get("day", "?")
            area = ddata.get("area", "")
            area_label = area_names.get(area, area)
            plan = ddata.get("plan", {})
            summary = ddata.get("summary")

            # day header + summary badge
            badge = ""
            if summary:
                res = summary.get("kann_result", "")
                bcls = {"bestanden": "pass", "teilweise": "partial", "nicht_bestanden": "fail"}.get(res, "pending")
                badge = f' <span class="badge {bcls}">{res}</span>'

            day_id = f"d_{sid}_{day_num}"
            students_html += f'<details class="day-block" id="{day_id}"><summary>Tag {day_num}: {_esc(area_label)}{badge}</summary>'

            # plan
            if plan:
                students_html += f'<div class="plan-box"><b>Plan:</b> {_esc(plan.get("reasoning",""))}<br><b>Approach:</b> {_esc(plan.get("opening_approach",""))}</div>'

            # rounds
            for r in ddata.get("rounds", []):
                students_html += f'<div class="round-header">— Runde {r["round"]}: {_esc(r["name"])} —</div>'

                # Teacher
                rnd = r["round"]
                t_id = f"p_{sid}_{day_num}_{rnd}_t"
                s_id = f"p_{sid}_{day_num}_{rnd}_s"
                g_id = f"p_{sid}_{day_num}_{rnd}_g"

                students_html += f'<div class="msg teacher"><div class="label">Lehrerin Weber</div>{_esc(r.get("teacher_msg","..."))}'
                students_html += f'<details id="{t_id}"><summary class="prompt-toggle">show prompt</summary><div class="prompt-box">{_esc(r.get("teacher_prompt",""))}</div></details></div>'

                # Student
                if r.get("student_msg"):
                    students_html += f'<div class="msg student"><div class="label">{_esc(sdata["name"])}</div>{_esc(r.get("student_msg","..."))}'
                    students_html += f'<details id="{s_id}"><summary class="prompt-toggle">show prompt</summary><div class="prompt-box">{_esc(r.get("student_prompt",""))}</div></details></div>'

                # Grader
                if r.get("grader"):
                    g = r["grader"]
                    gtext = f"Verdict: {g.get('verdict','')} | Wortfeld: {', '.join(g.get('wortfeld_used',[]))} | Grammar: {'; '.join(g.get('grammar_notes',[]))}"
                    students_html += f'<div class="grader"><div class="label">Grader</div>{_esc(gtext)}'
                    students_html += f'<details id="{g_id}"><summary class="prompt-toggle">show prompt</summary><div class="prompt-box">{_esc(r.get("grader_prompt",""))}</div></details></div>'

            # day summary
            if summary:
                highlight = summary.get("session_highlight", "")
                vocab = ", ".join(v.get("word","") for v in summary.get("vocabulary_learned", []))
                students_html += f'<div class="summary-box"><b>Result:</b> {_esc(summary.get("kann_result",""))}<br>'
                students_html += f'<b>Highlight:</b> {_esc(highlight)}<br>'
                if vocab:
                    students_html += f'<b>Vocabulary:</b> {_esc(vocab)}'
                students_html += '</div>'

            students_html += '</details>'

        # active round indicator
        if s["current_student"] == sid and not s["done"]:
            students_html += '<div class="active-indicator">Running...</div>'

        students_html += '</div>'

    # ── assemble ──────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Sprecher — A1 Full Course</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: -apple-system, 'Segoe UI', sans-serif; background:#e5ddd5; padding:20px; max-width:1000px; margin:0 auto; }}
  h1 {{ text-align:center; padding:12px; background:#075e54; color:white; border-radius:10px 10px 0 0; font-size:1.2em; }}
  .status {{ text-align:center; padding:8px; background:#128c7e; color:white; font-size:0.85em; margin-bottom:15px; border-radius:0 0 10px 10px; }}
  h2 {{ background:#25d366; color:white; padding:8px 12px; border-radius:8px; margin:15px 0 8px 0; font-size:1em; }}
  .score {{ width:100%; border-collapse:collapse; margin:10px 0 20px 0; font-size:0.85em; }}
  .score th {{ background:#075e54; color:white; padding:6px 10px; text-align:left; }}
  .score td {{ padding:6px 10px; border:1px solid #ccc; text-align:center; }}
  .score td:first-child {{ text-align:left; font-weight:bold; }}
  .pass {{ background:#d4edda; color:#155724; font-weight:bold; }}
  .partial {{ background:#fff3cd; color:#856404; font-weight:bold; }}
  .fail {{ background:#f8d7da; color:#721c24; font-weight:bold; }}
  .pending {{ background:#f0f0f0; color:#888; }}
  .badge {{ font-size:0.75em; padding:2px 6px; border-radius:4px; margin-left:6px; }}
  .student-section {{ margin:10px 0; }}
  .day-block {{ background:white; border-radius:8px; margin:6px 0; padding:0; }}
  .day-block > summary {{ padding:10px 14px; cursor:pointer; font-weight:bold; font-size:0.95em; background:#f8f9fa; border-radius:8px; }}
  .day-block[open] > summary {{ border-radius:8px 8px 0 0; border-bottom:1px solid #ddd; }}
  .chat {{ padding:10px 15px; }}
  .msg {{ max-width:78%; padding:8px 12px; border-radius:10px; margin:6px 0; line-height:1.4; font-size:0.9em; }}
  .teacher {{ background:#dcf8c6; margin-right:auto; border-top-left-radius:0; }}
  .student {{ background:white; margin-left:auto; border-top-right-radius:0; border:1px solid #eee; }}
  .grader {{ background:#fff3cd; margin:8px auto; max-width:90%; border-radius:8px; border-left:4px solid #ffc107; font-size:0.8em; padding:8px 12px; }}
  .label {{ font-weight:bold; font-size:0.75em; color:#555; margin-bottom:2px; }}
  .prompt-box {{ background:#1a1a2e; color:#0f0; font-family:monospace; font-size:0.7em; padding:10px; border-radius:6px; margin:6px 0; max-height:180px; overflow-y:auto; white-space:pre-wrap; word-wrap:break-word; }}
  .prompt-toggle {{ font-size:0.7em; color:#075e54; cursor:pointer; text-decoration:underline; }}
  .round-header {{ text-align:center; color:#888; font-size:0.8em; margin:12px 0 4px 0; padding:4px; border-bottom:1px solid #eee; }}
  .plan-box {{ background:#d4edda; padding:8px 12px; border-radius:6px; margin:8px 12px; font-size:0.85em; border-left:4px solid #28a745; }}
  .summary-box {{ background:#cce5ff; padding:8px 12px; border-radius:6px; margin:8px 12px; font-size:0.85em; border-left:4px solid #004085; }}
  .active-indicator {{ text-align:center; padding:6px; color:#128c7e; font-style:italic; animation: pulse 1.5s infinite; }}
  @keyframes pulse {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:0.4; }} }}
  details summary {{ cursor:pointer; }}
</style>
</head><body>
<h1>Deutschkurs A1 — Voller Kurs — 3 Studierende × 7 Themen</h1>
<div class="status">{status}</div>
{scorecard_html}
{students_html}
<script>
function getOpenIds() {{
  return Array.from(document.querySelectorAll('details[open]'))
    .map(d => d.id).filter(Boolean);
}}
function restoreOpen(ids) {{
  ids.forEach(id => {{
    var el = document.getElementById(id);
    if (el) el.open = true;
  }});
}}
function poll() {{
  fetch(location.href).then(r => r.text()).then(html => {{
    var open = getOpenIds();
    var scroll = window.scrollY;
    var parser = new DOMParser();
    var doc = parser.parseFromString(html, 'text/html');
    document.querySelector('.status').innerHTML = doc.querySelector('.status').innerHTML;
    var tables = document.querySelectorAll('.score');
    var newTables = doc.querySelectorAll('.score');
    if (tables.length && newTables.length) tables[0].outerHTML = newTables[0].outerHTML;
    var sections = document.querySelectorAll('.student-section');
    var newSections = doc.querySelectorAll('.student-section');
    for (var i = 0; i < newSections.length; i++) {{
      if (i < sections.length) sections[i].outerHTML = newSections[i].outerHTML;
      else document.body.appendChild(newSections[i].cloneNode(true));
    }}
    restoreOpen(open);
    window.scrollTo(0, scroll);
  }}).catch(() => {{}});
}}
setInterval(poll, 4000);
</script>
</body></html>"""
    return html

class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(render_html().encode())
    def log_message(self, *a): pass

def start_server(port=8787):
    srv = HTTPServer(("127.0.0.1", port), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv

# ── find Kann by subject area ──────────────────────────────────────
def get_kann_for_area(area_id):
    for area in course_struct["subject_areas"]:
        if area["id"] == area_id:
            kann_id = area["primary_kann"][0]
            for k in canon_kann:
                if k["id"] == kann_id:
                    return k
    return canon_kann[0]

# ── build prompts from JSON templates ──────────────────────────────
def build_teacher_prompt(kann, round_frame, day, student_name, teacher_memory, interstitial_text=""):
    persona = teacher_pers["system_prompt"]
    canon_block = f"Current Kannbeschreibung: {kann['kann']}\nWortfeld: {', '.join(kann['wortfeld'])}\nSprachhandlungen: {', '.join(kann['sprachhandlungen'])}"
    round_block = f"Round {round_frame['round']} of 7: {round_frame['name']}.\n{round_frame['teacher_instruction']}"
    memory_block = f"Your memory of {student_name}:\n{json.dumps(teacher_memory, ensure_ascii=False)}" if teacher_memory else f"This is your first meeting with {student_name}."
    day_block = bridges["day_open"]["teacher_injection_day1"] if day == 1 else bridges["day_open"]["teacher_injection_returning"].replace("{days_completed}", str(day-1))

    full = f"{persona}\n\n--- CANON ---\n{canon_block}\n\n--- ROUND ---\n{round_block}\n\n--- MEMORY ---\n{memory_block}\n\n--- DAY CONTEXT ---\n{day_block}"
    if interstitial_text:
        full += f"\n\n--- INTERSTITIAL ---\n{interstitial_text}"
    return full

def build_student_prompt(student_data, learned_state):
    base = f"{student_data['base_persona']}\n\n{student_data['personality']}\n\n{student_data['generation_rules']}"
    if learned_state.get("day", 0) > 0:
        vocab_lines = []
        for v in learned_state.get("vocabulary_acquired", []):
            status = "STABLE — use correctly" if v.get("stable") else "UNSTABLE — right ~70%, slip back ~30%"
            vocab_lines.append(f"  - '{v['word']}' ({status})")
        vocab_section = "Vocabulary you've learned:\n" + "\n".join(vocab_lines) if vocab_lines else ""

        gram_lines = []
        for g in learned_state.get("grammar_acquired", []):
            status = "STABLE" if g.get("stable") else "UNSTABLE"
            gram_lines.append(f"  - {g['rule']} ({status})")
        gram_section = "Grammar you've learned:\n" + "\n".join(gram_lines) if gram_lines else ""

        errors_section = "Errors you STILL make:\n" + "\n".join(f"  - {e}" for e in learned_state.get("persistent_errors", []))
        emotional = f"Your feeling about German class: {learned_state.get('emotional_state', '')}"

        overlay = overlay_tmpl["template"]
        overlay = overlay.replace("{base_persona}", base)
        overlay = overlay.replace("{days_completed}", str(learned_state.get("day", 0)))
        overlay = overlay.replace("{vocabulary_section}", vocab_section)
        overlay = overlay.replace("{grammar_section}", gram_section)
        overlay = overlay.replace("{errors_section}", errors_section)
        overlay = overlay.replace("{emotional_section}", emotional)
        return overlay
    return base

def build_grader_prompt(kann, round_frame, day, teacher_msg, student_msg, prior_progress):
    sys_p = grader_round["system_prompt"]
    user_p = grader_round["user_template"]
    user_p = user_p.replace("{kann_text}", kann["kann"])
    user_p = user_p.replace("{wortfeld}", ", ".join(kann["wortfeld"]))
    user_p = user_p.replace("{sprachhandlungen}", ", ".join(kann["sprachhandlungen"]))
    user_p = user_p.replace("{current_day}", str(day))
    user_p = user_p.replace("{current_round}", str(round_frame["round"]))
    user_p = user_p.replace("{round_name}", round_frame["name"])
    user_p = user_p.replace("{prior_progress}", json.dumps(prior_progress, ensure_ascii=False) if prior_progress else "No prior data (Day 1).")
    user_p = user_p.replace("{teacher_message}", teacher_msg)
    user_p = user_p.replace("{student_message}", student_msg)
    return sys_p, user_p

# ── run one day for one student ────────────────────────────────────
def run_day(student_id):
    student_data = load(f"prompts/students/{student_id}.json")
    learned = load(f"state/students/{student_id}_learned.json")
    teacher_mem = load(f"state/teacher/memory_{student_id}.json")
    course = load("state/course/course_state.json")
    progress = load("state/grader/progress.json")

    day = course["current_day"].get(student_id, 0) + 1
    areas_covered = course["areas_covered"].get(student_id, [])
    areas_remaining = [a for a in ALL_AREAS if a not in areas_covered]

    if not areas_remaining:
        print(f"  {student_data['name']}: all areas covered!")
        return None

    # init live tracking for this student
    if student_id not in live["students"]:
        live["students"][student_id] = {"name": student_data["name"], "days": []}

    live["current_student"] = student_id
    live["current_day"] = day
    live["status"] = f"{student_data['name']} — Tag {day}/{NUM_DAYS} — Planning..."

    day_live = {"day": day, "area": "", "plan": {}, "rounds": [], "summary": None}
    live["students"][student_id]["days"].append(day_live)

    print(f"\n{'='*60}")
    print(f"  Tag {day} — {student_data['name']}")
    print(f"{'='*60}")

    # ── Planner ───────────────────────────────────────────────────
    planner_user = planner_tmpl["user_template"]
    planner_user = planner_user.replace("{student_name}", student_data["name"])
    planner_user = planner_user.replace("{current_day}", str(day))
    planner_user = planner_user.replace("{teacher_memory}", json.dumps(teacher_mem, ensure_ascii=False))
    planner_user = planner_user.replace("{student_learned}", json.dumps(learned, ensure_ascii=False))
    planner_user = planner_user.replace("{areas_covered}", ", ".join(areas_covered) or "none")
    planner_user = planner_user.replace("{areas_remaining}", ", ".join(areas_remaining))
    plan_raw = chat("openai", "gpt-4o", [
        {"role": "system", "content": planner_tmpl["system_prompt"]},
        {"role": "user", "content": planner_user}
    ], temperature=0.7)

    try:
        plan = parse_json(plan_raw)
    except:
        plan = {"chosen_area": areas_remaining[0], "reasoning": plan_raw, "opening_approach": "Greet and ask an open question.", "watch_for": []}

    # validate chosen_area is actually remaining
    if plan.get("chosen_area") not in areas_remaining:
        plan["chosen_area"] = areas_remaining[0]

    kann = get_kann_for_area(plan["chosen_area"])
    area_name = plan["chosen_area"]
    day_live["area"] = area_name
    day_live["plan"] = plan
    live["status"] = f"{student_data['name']} — Tag {day}/{NUM_DAYS} — {area_name}"

    print(f"  Plan: {area_name} — {plan.get('reasoning','')[:80]}")
    save(f"plans/generated/{student_id}_day{day}_plan.json", plan)

    # ── Rounds 1-7 ────────────────────────────────────────────────
    conversation_history = []
    grader_reports = []
    interstitial_text = ""

    for rf in rounds_tmpl:
        rnd = rf["round"]
        live["status"] = f"{student_data['name']} — Tag {day} — Runde {rnd}/7: {rf['name']}"
        round_data = {"round": rnd, "name": rf["name"]}

        # Teacher
        t_prompt = build_teacher_prompt(kann, rf, day, student_data["name"], teacher_mem, interstitial_text)
        t_messages = [{"role": "system", "content": t_prompt}]
        for ex in conversation_history:
            t_messages.append({"role": "assistant", "content": ex["teacher"]})
            if ex.get("student"):
                t_messages.append({"role": "user", "content": ex["student"]})
        if rnd == 1 and not conversation_history:
            t_messages.append({"role": "user", "content": f"Begin the lesson. Open approach: {plan.get('opening_approach','Greet the student.')}"})

        teacher_msg = chat("openai", "gpt-4o", t_messages)
        round_data["teacher_msg"] = teacher_msg
        round_data["teacher_prompt"] = t_prompt
        print(f"\n  [Runde {rnd}: {rf['name']}]")
        print(f"  Lehrerin: {teacher_msg}")

        # Student
        s_prompt = build_student_prompt(student_data, learned)
        s_messages = [{"role": "system", "content": s_prompt}]
        for ex in conversation_history:
            s_messages.append({"role": "user", "content": ex["teacher"]})
            if ex.get("student"):
                s_messages.append({"role": "assistant", "content": ex["student"]})
        s_messages.append({"role": "user", "content": teacher_msg})

        student_msg = chat(student_data["api"], student_data["model"], s_messages)
        round_data["student_msg"] = student_msg
        round_data["student_prompt"] = s_prompt
        print(f"  {student_data['name']}: {student_msg}")

        # Grader
        g_sys, g_user = build_grader_prompt(kann, rf, day, teacher_msg, student_msg, progress.get(student_id, []))
        grader_raw = chat("openai", "gpt-4o", [
            {"role": "system", "content": g_sys},
            {"role": "user", "content": g_user}
        ], temperature=0.3)

        try:
            grader_result = parse_json(grader_raw)
        except:
            grader_result = {"verdict": "parse_error", "wortfeld_used": [], "grammar_notes": [grader_raw], "steering": "proceed", "canon_aligned": True, "sprachhandlung": ""}

        round_data["grader"] = grader_result
        round_data["grader_prompt"] = f"SYSTEM:\n{g_sys}\n\nUSER:\n{g_user}"
        grader_reports.append(grader_result)
        print(f"  Grader: {grader_result.get('verdict','')} | {'; '.join(grader_result.get('grammar_notes',[]))}")

        # Steering
        steering = grader_result.get("steering", "proceed")
        interstitial_key = rf.get("interstitial_after", "")
        interstitial_text = ""
        if steering in ("gentle_redirect", "explicit_reteach") and "correction_bridge" in bridges:
            interstitial_text = bridges["correction_bridge"]["teacher_injection"]
        elif interstitial_key == "round_transition" and "round_transition" in bridges:
            interstitial_text = bridges["round_transition"]["teacher_injection"]
        elif interstitial_key == "day_close" and "day_close" in bridges:
            interstitial_text = bridges["day_close"]["teacher_injection"]

        conversation_history.append({"teacher": teacher_msg, "student": student_msg})
        day_live["rounds"].append(round_data)

    # ── Day Summary ───────────────────────────────────────────────
    live["status"] = f"{student_data['name']} — Tag {day} — Summarizing..."
    summary_user = grader_day["user_template"]
    summary_user = summary_user.replace("{student_name}", student_data["name"])
    summary_user = summary_user.replace("{current_day}", str(day))
    summary_user = summary_user.replace("{subject_area}", area_name)
    summary_user = summary_user.replace("{kann_text}", kann["kann"])
    summary_user = summary_user.replace("{all_grader_reports}", json.dumps(grader_reports, ensure_ascii=False))
    summary_user = summary_user.replace("{prior_progress}", json.dumps(progress.get(student_id, []), ensure_ascii=False))
    summary_raw = chat("openai", "gpt-4o", [
        {"role": "system", "content": grader_day["system_prompt"]},
        {"role": "user", "content": summary_user}
    ], temperature=0.3)

    try:
        day_summary = parse_json(summary_raw)
    except:
        day_summary = {"day": day, "kann_result": "teilweise", "session_highlight": summary_raw,
                       "vocabulary_learned": [], "grammar_learned": [], "persistent_errors": [],
                       "improvements_from_prior": [], "emotional_state": ""}

    day_live["summary"] = day_summary

    # ── Wrapup ────────────────────────────────────────────────────
    wrapup_user = wrapup_tmpl["user_template"]
    wrapup_user = wrapup_user.replace("{student_name}", student_data["name"])
    wrapup_user = wrapup_user.replace("{current_day}", str(day))
    wrapup_user = wrapup_user.replace("{subject_area}", area_name)
    wrapup_user = wrapup_user.replace("{conversation}", json.dumps(conversation_history, ensure_ascii=False))
    wrapup_user = wrapup_user.replace("{grader_reports}", json.dumps(grader_reports, ensure_ascii=False))
    wrapup_user = wrapup_user.replace("{prior_memory}", json.dumps(teacher_mem, ensure_ascii=False))
    wrapup_raw = chat("openai", "gpt-4o", [
        {"role": "system", "content": wrapup_tmpl["system_prompt"]},
        {"role": "user", "content": wrapup_user}
    ], temperature=0.5)

    try:
        new_teacher_mem = parse_json(wrapup_raw)
    except:
        new_teacher_mem = {"raw": wrapup_raw}

    # ── Update learned state ──────────────────────────────────────
    new_learned = dict(learned)
    new_learned["day"] = day
    for v in day_summary.get("vocabulary_learned", []):
        new_learned.setdefault("vocabulary_acquired", []).append(v)
    for g in day_summary.get("grammar_learned", []):
        new_learned.setdefault("grammar_acquired", []).append(g)
    new_learned["persistent_errors"] = day_summary.get("persistent_errors", learned.get("persistent_errors", []))
    new_learned["emotional_state"] = day_summary.get("emotional_state", "")
    new_learned.setdefault("kannbeschreibungen_attempted", {})[kann["id"]] = {
        "day": day, "result": day_summary.get("kann_result", "teilweise")
    }

    # ── Save everything ───────────────────────────────────────────
    save(f"state/teacher/memory_{student_id}.json", new_teacher_mem)
    save(f"state/students/{student_id}_learned.json", new_learned)

    progress.setdefault(student_id, []).append(day_summary)
    save("state/grader/progress.json", progress)

    course["current_day"][student_id] = day
    course["areas_covered"].setdefault(student_id, []).append(area_name)
    save("state/course/course_state.json", course)

    save(f"output/day{day}_{student_id}.json", {
        "day": day, "student": student_id, "subject_area": area_name,
        "plan": plan, "rounds": day_live["rounds"], "summary": day_summary,
        "teacher_memory_after": new_teacher_mem
    })

    # update scorecard
    live["scorecard"].setdefault(student_id, {})[area_name] = day_summary.get("kann_result", "teilweise")

    result = day_summary.get("kann_result", "")
    highlight = day_summary.get("session_highlight", "")
    print(f"\n  Result: {result} — {highlight}")
    return day_summary

# ── run full course ────────────────────────────────────────────────
def run_full_course():
    """Run all students through all 7 subject areas."""
    total_days = NUM_DAYS * len(ALL_STUDENTS)
    completed = 0

    for student_id in ALL_STUDENTS:
        print(f"\n{'#'*60}")
        print(f"  STUDENT: {student_id.upper()}")
        print(f"{'#'*60}")

        for day_num in range(1, NUM_DAYS + 1):
            try:
                result = run_day(student_id)
                completed += 1
                live["status"] = f"Progress: {completed}/{total_days} days complete"
                if result is None:
                    break
            except Exception as e:
                print(f"\n  ERROR on {student_id} day {day_num}: {e}")
                traceback.print_exc()
                live["status"] = f"ERROR: {student_id} day {day_num} — {e}"
                completed += 1
                continue

    live["status"] = f"COMPLETE — {completed}/{total_days} days run"
    live["done"] = True

# ── entry point ────────────────────────────────────────────────────
if __name__ == "__main__":
    port = 8787
    print(f"Starting HTTP server on http://127.0.0.1:{port}")
    start_server(port)
    os.chdir(BASE)

    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    if mode == "all":
        run_full_course()
    else:
        # single student, all their days
        live["students"][mode] = {"name": mode, "days": []}
        for _ in range(NUM_DAYS):
            result = run_day(mode)
            if result is None:
                break
        live["done"] = True

    print(f"\nDone. Server running at http://127.0.0.1:{port}")
    print("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopped.")
