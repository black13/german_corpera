"""
runner.py v2 — Classroom model. One Kann per day, configured student group.
Disposable. Reads JSON, calls APIs, writes JSON, serves HTTP.
Contains ZERO rules about German. All meaning is in the JSON files.
"""
import json, os, sys, threading, time, traceback, functools
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler
from openai import OpenAI

BASE = Path(__file__).parent

# ── JSON helpers ───────────────────────────────────────────────────
def load(path):
    with open(BASE / path) as f:
        return json.load(f)

def save(path, data):
    p = BASE / path
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


runtime_cfg = load("config/runtime.json")

# ── API clients ────────────────────────────────────────────────────
openai_client = OpenAI()
deepseek_client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
    base_url="https://api.deepseek.com"
)

def chat(api, model, messages, temperature=0.8, max_tokens=500):
    client = deepseek_client if api == "deepseek" else openai_client
    r = client.chat.completions.create(
        model=model, messages=messages, temperature=temperature, max_tokens=max_tokens
    )
    return r.choices[0].message.content


def chat_from_config(step_name, messages):
    cfg = runtime_cfg["models"][step_name]
    return chat(
        cfg["api"],
        cfg["model"],
        messages,
        temperature=cfg.get("temperature", 0.8),
        max_tokens=cfg.get("max_tokens", 500),
    )

def parse_json(raw):
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
    if s.endswith("```"):
        s = s[:-3]
    return json.loads(s.strip())

# ── load canon + prompts (read-only) ──────────────────────────────
kann_data    = load("canon/kannbeschreibungen_full.json")
all_kanns    = kann_data["kannbeschreibungen"]
TOTAL_KANNS  = len(all_kanns)
canon_bewert = load("canon/bewertung.json")
teacher_pers = load("prompts/teacher/persona.json")
rounds_tmpl  = load("prompts/teacher/round_frames.json")["rounds"]
wrapup_tmpl  = load("prompts/teacher/wrapup.json")
bridges      = load("prompts/interstitials/bridges.json")
grader_round = load("prompts/grader/per_round.json")
grader_day   = load("prompts/grader/day_summary.json")
overlay_tmpl = load("prompts/students/learning_overlay.json")

STUDENT_IDS = runtime_cfg["classroom"]["students"]
student_configs = {sid: load(f"prompts/students/{sid}.json") for sid in STUDENT_IDS}

# ── live state ─────────────────────────────────────────────────────
live = {
    "status": "starting",
    "current_day": 0,
    "current_kann": "",
    "current_kann_text": "",
    "current_round": 0,
    "current_round_name": "",
    "active_student": "",
    "days": [],  # [{day, kann_id, kann_text, category, rounds, summaries}]
    "done": False
}

# ── HTML rendering ─────────────────────────────────────────────────
def _esc(s):
    return str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

STUDENT_COLORS = {"marta": "#dcf8c6", "james": "#d4e6f1", "yuki": "#f9e79f"}
STUDENT_LABEL_COLORS = {"marta": "#2e7d32", "james": "#1565c0", "yuki": "#e65100"}
STUDENT_NAMES = {sid: student_configs[sid]["name"] for sid in STUDENT_IDS}

# ── CSS (plain string — no f-string escaping needed) ──────────────
_CSS = """
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;overflow:hidden}
body{font-family:-apple-system,'Segoe UI',Roboto,Helvetica,sans-serif;background:#f0f0f0;color:#222;
  -webkit-user-select:text;user-select:text;-webkit-touch-callout:default}

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
.lh-kann{opacity:.85;font-size:.92em}
.lh-right{display:flex;align-items:center;gap:12px;flex-shrink:0}
.lh-student{font-weight:700;color:#a5d6a7}
.lh-updated{opacity:.65;font-size:.82em}

/* ── two-pane layout ── */
.layout{
  display:grid;grid-template-columns:1fr 280px;
  height:calc(100vh - 42px);margin-top:42px;
}
.transcript{overflow-y:auto;padding:16px 28px 40px 28px;background:#f0f0f0}
.sidebar{overflow-y:auto;padding:14px;background:#fff;border-left:1px solid #ddd}

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
.sc-day{font-weight:700;width:28px}
.sc-kann{max-width:56px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pass{background:#d4edda;color:#155724;font-weight:700}
.partial{background:#fff3cd;color:#856404;font-weight:700}
.fail{background:#f8d7da;color:#721c24;font-weight:700}
.pending{background:#f5f5f5;color:#aaa}

/* ── day blocks ── */
.day-block{background:#fff;border-radius:10px;margin:12px 0;box-shadow:0 1px 4px rgba(0,0,0,.07)}
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

/* ── view mode filtering ── */
body.view-conversation .grader-block{display:none}
body.view-conversation .prompt-details{display:none}
body.view-grader .prompt-details{display:none}
/* body.view-debug — everything visible */

/* ── mobile / iPhone ── */
@media(max-width:768px){
  .layout{grid-template-columns:1fr;height:auto;margin-top:0}
  .live-header{position:relative;flex-wrap:wrap;padding:8px 12px;font-size:.82em}
  .lh-sep{display:none}
  .lh-left{gap:4px}
  .lh-right{width:100%;justify-content:space-between;margin-top:4px}
  html,body{height:auto;overflow:auto}
  .transcript{padding:10px 12px 30px 12px;min-height:0}
  .sidebar{border-left:none;border-top:1px solid #ddd;padding:12px}
  .day-content{padding:10px 12px}
  .msg{max-width:95% !important;padding:10px 12px;font-size:.95em}
  .teacher-msg{max-width:95%}
  .grader-block{max-width:100%}
  .kann-banner{padding:8px 10px}
  .round-header{margin:16px 0 8px 0}
  .exchange-group{margin-bottom:14px;padding-bottom:12px}
  .prompt-box{max-height:150px;font-size:.65em}
  .day-block>summary{padding:10px 12px;font-size:.88em}
  .scorecard{font-size:.68em}
  .vbtn{padding:8px 6px;font-size:.72em}
}
@media(max-width:430px){
  .live-header{padding:6px 10px;font-size:.78em}
  .lh-tag,.lh-round{font-size:.85em}
  .lh-kann{font-size:.8em}
  .transcript{padding:8px 8px 24px 8px}
  .day-content{padding:8px 10px}
  .msg{padding:8px 10px;font-size:.9em;border-radius:8px}
  .speaker{font-size:.78em}
  .kann-text{font-size:.88em}
  .sidebar{padding:10px}
}
"""

# ── JS (plain string — no f-string escaping needed) ───────────────
_JS = """
(function(){
  var currentView = localStorage.getItem('sprecher-view') || 'conversation';
  var lastUpdate = Date.now();
  var manuallyClosedDays = {};

  function setView(v) {
    currentView = v;
    localStorage.setItem('sprecher-view', v);
    document.body.className = 'view-' + v;
    document.querySelectorAll('.vbtn').forEach(function(b){
      b.classList.toggle('active', b.getAttribute('data-view') === v);
    });
  }
  setView(currentView);

  // button clicks via delegation
  document.addEventListener('click', function(e){
    if (e.target.classList.contains('vbtn')) {
      setView(e.target.getAttribute('data-view'));
    }
  });

  // track manual close of day blocks
  document.addEventListener('toggle', function(e){
    if (e.target.classList && e.target.classList.contains('day-block')) {
      if (!e.target.open) manuallyClosedDays[e.target.id] = true;
      else delete manuallyClosedDays[e.target.id];
    }
  }, true);

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

    fetch(location.href).then(function(r){ return r.text(); }).then(function(html){
      var parser = new DOMParser();
      var doc = parser.parseFromString(html, 'text/html');

      // header (fixed position — no layout shift)
      var h = document.querySelector('.live-header');
      var nh = doc.querySelector('.live-header');
      if (h && nh) h.innerHTML = nh.innerHTML;

      // sidebar sections (separate scroll context — no transcript shift)
      var secs = document.querySelectorAll('.sidebar-section');
      var nsecs = doc.querySelectorAll('.sidebar-section');
      for (var i = 0; i < nsecs.length && i < secs.length; i++)
        secs[i].innerHTML = nsecs[i].innerHTML;

      // transcript — append-only strategy
      var trans = document.getElementById('transcript');
      var ntrans = doc.getElementById('transcript');
      if (trans && ntrans) {
        var days = Array.from(trans.querySelectorAll('.day-block'));
        var newDays = Array.from(ntrans.querySelectorAll('.day-block'));

        for (var i = 0; i < newDays.length; i++) {
          if (i >= days.length) {
            // brand-new day block — append whole
            trans.appendChild(newDays[i].cloneNode(true));
          } else if (i >= days.length - 1) {
            // was the active (last) day — incremental update only
            updateActiveDay(days[i], newDays[i]);
          }
          // older completed days: don't touch at all
        }
      }

      // auto-open latest day unless user manually closed it
      var allDays = document.querySelectorAll('.day-block');
      if (allDays.length > 0) {
        var last = allDays[allDays.length - 1];
        if (!manuallyClosedDays[last.id]) last.open = true;
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

  setInterval(poll, 3000);
})();
"""

def render_html():
    status = _esc(live["status"])
    cur_day = live.get("current_day", 0)
    cur_round = live.get("current_round", 0)
    cur_round_name = _esc(live.get("current_round_name", ""))
    cur_kann = _esc(live.get("current_kann", ""))
    cur_kann_text = _esc(live.get("current_kann_text", ""))
    active_stu = _esc(live.get("active_student", ""))
    is_done = live.get("done", False)

    # ── sidebar scorecard rows ──
    sc_rows = ""
    for ddata in live["days"]:
        cells = ""
        for sid in STUDENT_IDS:
            result = ddata.get("summaries", {}).get(sid, {}).get("kann_result", "\u2026")
            cls = {"bestanden": "pass", "teilweise": "partial", "nicht_bestanden": "fail"}.get(result, "pending")
            cells += f'<td class="{cls}">{_esc(result)}</td>'
        sc_rows += f'<tr><td class="sc-day">{ddata["day"]}</td><td class="sc-kann" title="{_esc(ddata.get("kann_text",""))}">{_esc(ddata["kann_id"])}</td>{cells}</tr>\n'

    stu_ths = "".join(f"<th>{_esc(STUDENT_NAMES[sid][:8])}</th>" for sid in STUDENT_IDS)

    # ── transcript day blocks ──
    days_html = ""
    n_days = len(live["days"])
    for idx, ddata in enumerate(live["days"]):
        day_num = ddata["day"]
        is_latest = (idx == n_days - 1)

        kann_full = _esc(ddata.get("kann_text", ""))
        kann_cat = _esc(ddata.get("category", ""))
        days_html += f'<details class="day-block" id="d_{day_num}" data-latest="{1 if is_latest else 0}">'
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
                    f'<div class="text">{_esc(ex.get("teacher_msg", "..."))}</div>'
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

                # grader
                if ex.get("grader"):
                    g = ex["grader"]
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
  <div class="sidebar" id="sidebar">
    <div class="view-controls">
      <button class="vbtn" data-view="conversation">Conversation</button>
      <button class="vbtn" data-view="grader">+ Grader</button>
      <button class="vbtn" data-view="debug">Full Debug</button>
    </div>
    <div class="sidebar-section">
      <div class="sidebar-title">Scorecard</div>
      <table class="scorecard">
        <thead><tr><th>Tag</th><th>Kann</th>{stu_ths}</tr></thead>
        <tbody>{sc_rows}</tbody>
      </table>
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

class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(render_html().encode())
    def log_message(self, *a): pass

def start_server(host="127.0.0.1", port=8787):
    srv = HTTPServer((host, port), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv

# ── prompt builders ────────────────────────────────────────────────
def build_teacher_prompt(kann, round_frame, day, student_name, teacher_memories, classroom_context, interstitial=""):
    persona = teacher_pers["system_prompt"]
    canon_block = f"Today's Kannbeschreibung: {kann['kann']}\nCategory: {kann.get('category','')}"
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
    full += f"\n\nYou are now speaking to {student_name}."
    return full

def build_student_prompt(student_data, learned_state, classroom_context):
    base = f"{student_data['base_persona']}\n\n{student_data['personality']}\n\n{student_data.get('classmates','')}\n\n{student_data['generation_rules']}"

    # what classmates said
    if classroom_context:
        base += "\n\nWHAT YOUR CLASSMATES SAID THIS ROUND:\n" + "\n".join(
            f"  {STUDENT_NAMES.get(s,s)}: {msg}" for s, msg in classroom_context
        )

    if learned_state.get("day", 0) > 0:
        vocab_lines = [f"  - '{v['word']}' ({'STABLE' if v.get('stable') else 'UNSTABLE'})"
                       for v in learned_state.get("vocabulary_acquired", [])]
        gram_lines = [f"  - {g['rule']} ({'STABLE' if g.get('stable') else 'UNSTABLE'})"
                      for g in learned_state.get("grammar_acquired", [])]
        errors = learned_state.get("persistent_errors", [])

        overlay = overlay_tmpl["template"]
        overlay = overlay.replace("{base_persona}", base)
        overlay = overlay.replace("{days_completed}", str(learned_state.get("day", 0)))
        overlay = overlay.replace("{vocabulary_section}", "Vocabulary:\n" + "\n".join(vocab_lines) if vocab_lines else "")
        overlay = overlay.replace("{grammar_section}", "Grammar:\n" + "\n".join(gram_lines) if gram_lines else "")
        overlay = overlay.replace("{errors_section}", "Errors:\n" + "\n".join(f"  - {e}" for e in errors) if errors else "")
        overlay = overlay.replace("{emotional_section}", f"Feeling: {learned_state.get('emotional_state', '')}")
        return overlay
    return base

def build_grader_prompt(kann, round_frame, day, teacher_msg, student_msg, prior_progress):
    sys_p = grader_round["system_prompt"]
    user_p = grader_round["user_template"]
    user_p = user_p.replace("{kann_text}", kann["kann"])
    user_p = user_p.replace("{wortfeld}", "")  # full kanns don't have wortfeld
    user_p = user_p.replace("{sprachhandlungen}", "")
    user_p = user_p.replace("{current_day}", str(day))
    user_p = user_p.replace("{current_round}", str(round_frame["round"]))
    user_p = user_p.replace("{round_name}", round_frame["name"])
    user_p = user_p.replace("{prior_progress}", json.dumps(prior_progress, ensure_ascii=False) if prior_progress else "No prior data.")
    user_p = user_p.replace("{teacher_message}", teacher_msg)
    user_p = user_p.replace("{student_message}", student_msg)
    return sys_p, user_p

# ── run one day (one Kann, all students) ───────────────────────────
def run_day(day_num, kann):
    # load state
    teacher_mems = {sid: load(f"state/teacher/memory_{sid}.json") for sid in STUDENT_IDS}
    learned = {sid: load(f"state/students/{sid}_learned.json") for sid in STUDENT_IDS}
    progress = load("state/grader/progress.json")
    course_state = load("state/course/course_state.json")
    for sid in STUDENT_IDS:
        progress.setdefault(sid, [])
    course_state.setdefault("current_day", {})
    course_state.setdefault("areas_covered", {})
    for sid in STUDENT_IDS:
        course_state["current_day"].setdefault(sid, 0)
        course_state["areas_covered"].setdefault(sid, [])

    day_live = {
        "day": day_num, "kann_id": kann["id"], "kann_text": kann["kann"],
        "category": kann.get("category", ""), "rounds": [], "summaries": {}
    }
    live["days"].append(day_live)
    live["current_day"] = day_num
    live["current_kann"] = kann["id"]
    live["current_kann_text"] = kann["kann"]
    live["status"] = f"Tag {day_num}/{TOTAL_KANNS} \u2014 {kann['id']} \u2014 Starting..."

    print(f"\n{'='*70}")
    print(f"  Tag {day_num} \u2014 {kann['id']}: {kann['kann'][:70]}...")
    print(f"{'='*70}")

    # per-student conversation histories (teacher sees all, student sees own)
    teacher_history = []  # all exchanges in order
    student_histories = {sid: [] for sid in STUDENT_IDS}
    grader_reports = {sid: [] for sid in STUDENT_IDS}
    interstitial_text = ""

    for rf in rounds_tmpl:
        rnd = rf["round"]
        live["status"] = f"Tag {day_num} \u2014 Runde {rnd}/7: {rf['name']}"
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
                kann, rf, day_num, sname, teacher_mems, round_context, interstitial_text
            )
            t_messages = [{"role": "system", "content": t_prompt}]

            # teacher conversation history (all students)
            for ex in teacher_history:
                t_messages.append({"role": "assistant", "content": f"[To {ex['student_name']}] {ex['teacher_msg']}"})
                t_messages.append({"role": "user", "content": f"[{ex['student_name']}] {ex['student_msg']}"})

            if rnd == 1 and not teacher_history:
                t_messages.append({"role": "user", "content": f"Begin the lesson. Address {sname} first."})

            teacher_msg = chat_from_config("teacher", t_messages)
            print(f"\n  [R{rnd} {rf['name']}] Lehrerin \u2192 {sname}: {teacher_msg}")

            # ── Student responds ──────────────────────────────────
            s_prompt = build_student_prompt(sdata, learned[sid], round_context)
            s_messages = [{"role": "system", "content": s_prompt}]
            for ex in student_histories[sid]:
                s_messages.append({"role": "user", "content": ex["teacher_msg"]})
                s_messages.append({"role": "assistant", "content": ex["student_msg"]})
            s_messages.append({"role": "user", "content": teacher_msg})

            student_msg = chat(
                sdata["api"],
                sdata["model"],
                s_messages,
                temperature=sdata.get("temperature", 0.8),
                max_tokens=sdata.get("max_tokens", 500),
            )
            print(f"  {sname}: {student_msg}")

            # ── Grade ─────────────────────────────────────────────
            g_sys, g_user = build_grader_prompt(
                kann, rf, day_num, teacher_msg, student_msg,
                progress.get(sid, [])
            )
            grader_raw = chat_from_config("grader_round", [
                {"role": "system", "content": g_sys},
                {"role": "user", "content": g_user}
            ])

            try:
                grader_result = parse_json(grader_raw)
            except:
                grader_result = {"verdict": "parse_error", "wortfeld_used": [], "grammar_notes": [grader_raw], "steering": "proceed", "canon_aligned": True, "sprachhandlung": ""}

            print(f"  Grader \u2192 {sname}: {grader_result.get('verdict','')}")

            # ── Record ────────────────────────────────────────────
            exchange = {
                "student": sid, "teacher_msg": teacher_msg, "student_msg": student_msg,
                "grader": grader_result,
                "teacher_prompt": t_prompt, "student_prompt": s_prompt,
                "grader_prompt": f"SYSTEM:\n{g_sys}\n\nUSER:\n{g_user}"
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
    live["status"] = f"Tag {day_num} \u2014 Summarizing..."
    for sid in STUDENT_IDS:
        summary_user = grader_day["user_template"]
        summary_user = summary_user.replace("{student_name}", STUDENT_NAMES[sid])
        summary_user = summary_user.replace("{current_day}", str(day_num))
        summary_user = summary_user.replace("{subject_area}", kann.get("category", ""))
        summary_user = summary_user.replace("{kann_text}", kann["kann"])
        summary_user = summary_user.replace("{all_grader_reports}", json.dumps(grader_reports[sid], ensure_ascii=False))
        summary_user = summary_user.replace("{prior_progress}", json.dumps(progress.get(sid, []), ensure_ascii=False))
        summary_raw = chat_from_config("grader_day", [
            {"role": "system", "content": grader_day["system_prompt"]},
            {"role": "user", "content": summary_user}
        ])

        try:
            day_summary = parse_json(summary_raw)
        except:
            day_summary = {"day": day_num, "kann_result": "teilweise", "session_highlight": summary_raw,
                           "vocabulary_learned": [], "grammar_learned": [], "persistent_errors": [],
                           "improvements_from_prior": [], "emotional_state": ""}

        day_live["summaries"][sid] = day_summary
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
        wrapup_raw = chat_from_config("teacher_wrapup", [
            {"role": "system", "content": wrapup_tmpl["system_prompt"]},
            {"role": "user", "content": wrapup_user}
        ])

        try:
            new_mem = parse_json(wrapup_raw)
        except:
            new_mem = {"raw": wrapup_raw}
        save(f"state/teacher/memory_{sid}.json", new_mem)

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

    save("state/grader/progress.json", progress)
    for sid in STUDENT_IDS:
        course_state["current_day"][sid] = day_num
        area = kann.get("category", "")
        if area and area not in course_state["areas_covered"][sid]:
            course_state["areas_covered"][sid].append(area)
    save("state/course/course_state.json", course_state)

    # save day output
    save(f"output/day{day_num}_{kann['id']}.json", {
        "day": day_num, "kann": kann, "rounds": day_live["rounds"],
        "summaries": day_live["summaries"]
    })

    live["status"] = f"Tag {day_num}/{TOTAL_KANNS} \u2014 {kann['id']} \u2014 DONE"

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
