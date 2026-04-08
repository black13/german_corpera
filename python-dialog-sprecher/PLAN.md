# Build Plan

## The Discipline

**All meaning lives in JSON. Python is a dumb pipe.**

Python does exactly 3 things:
1. Read JSON
2. Call an API with what the JSON says
3. Write JSON back

Python does NOT:
- Decide what to say
- Choose topics
- Evaluate grammar
- Route conversation flow
- Format prompts with logic
- Contain if/else trees about German

If you find yourself writing `if "artikel" not in response:` in Python, STOP.
That rule belongs in a grader prompt JSON. The LLM evaluates grammar, not Python.

If you find yourself writing `rounds = [{"name": "Kontakt", ...}]` in Python, STOP.
That structure belongs in `prompts/teacher/round_frames.json`.

---

## Files To Create

### Phase 1: Canon (6 files)

The raw reference data from Profile Deutsch, CEFR, Goethe Wortliste.
These files are NEVER modified by the runner. They are read-only ground truth.

```
canon/kannbeschreibungen.json
  10 Kannbeschreibungen, each with:
    id, kann (the can-do text), subject_area, wortfeld[], sprachhandlungen[]

canon/bewertung.json
  CEFR A1 grading criteria (Wortschatz, Grammatik, Flüssigkeit, Kohärenz, Interaktion)
  Plus the global A1 descriptor text.

canon/sprachhandlungen.json
  Speech acts by category:
    Soziale Konventionen, Informationsaustausch, Bewertung,
    Gefühlsausdruck, Handlungsregulierung, Redeorganisation

canon/themen.json
  The 7 subject areas with their sub-topics from the Goethe inventory.

canon/grammatik.json
  A1 grammar scope: Verb, Satzstruktur, Nomen, Artikel, Pronomen,
  Präpositionen, Adjektiv, Konnektoren. Each with examples.

canon/wortfelder.json
  Full vocabulary clusters per Kannbeschreibung.
  Larger than what's in kannbeschreibungen.json — this is the deep list.
```

### Phase 2: Prompts (12 files)

Every prompt the system ever sends to an API is assembled from these templates.
The runner reads a template, fills slots with data from canon + state, sends it.

```
prompts/teacher/persona.json
  Who Lehrerin Weber is. Her pedagogical principles.
  Her attitude toward errors. How she references Profile Deutsch.
  How she speaks (mostly German, simple English for emergencies).

prompts/teacher/planner.json
  Day 0 prompt. Teacher reviews student memory + course state.
  Picks today's subject area. Outputs JSON with:
    chosen_area, reasoning, opening_approach, connections_to_prior, watch_for

prompts/teacher/round_frames.json
  The 7-round arc. Each round has:
    teacher_instruction (what to do this round)
    student_expectation (what to expect back)
    grader_focus (what to evaluate)
    interstitial_before (which bridge prompt fires before, or null)
    interstitial_after (which bridge prompt fires after, or null)

prompts/teacher/wrapup.json
  End-of-day prompt. Teacher summarizes what happened.
  Updates their memory of the student. Outputs JSON for state/.

prompts/students/marta.json
  Base persona: background, language profile (strengths, weaknesses,
  L1 interference), personality, generation rules.

prompts/students/james.json
  Same structure, different person.

prompts/students/yuki.json
  Same structure, different person.

prompts/students/learning_overlay.json
  Template that merges base persona + learned state into
  a day-specific student prompt. Uses slots like:
    {{vocabulary_acquired}}, {{grammar_acquired}}, {{persistent_errors}},
    {{emotional_state}}, {{days_completed}}

prompts/grader/per_round.json
  System prompt for grading a single exchange. Evaluates:
    canon alignment, wortfeld coverage, sprachhandlung performed,
    grammar notes (permissive), verdict (✅/⚠️/🔄), steering instruction.

prompts/grader/day_summary.json
  End-of-day grader prompt. Summarizes all 7 rounds.
  Compares to prior days. Outputs Kann result: bestanden/teilweise/nicht bestanden.

prompts/interstitials/bridges.json
  All interstitial prompts in one file, keyed by id:
    day_open — sets tone at start of day (first meeting vs. returning)
    round_transition — acknowledges what student said before probing deeper
    correction_bridge — fires when grader says redirect; tells teacher HOW to steer back
    topic_callback — fires when today connects to a prior day's topic
    day_close — wraps up warmly, previews next time
  Each entry has:
    when (condition), teacher_injection (added to teacher system prompt),
    student_injection (added to student system prompt, or null)
```

### Phase 3: Plans (2 files)

```
plans/course_structure.json
  The 7 subject areas. Each has:
    id, name, primary_kann[], connects_to[]
  Plus the Day 7 special rule (Prüfungsvorbereitung).

plans/day_plan_template.json
  Schema for what a generated day plan looks like.
  The planner prompt outputs this structure. The runner reads it.
```

### Phase 4: Initial State (8 files)

Empty starting state. The runner fills these as it runs.

```
state/teacher/memory_marta.json   — {}
state/teacher/memory_james.json   — {}
state/teacher/memory_yuki.json    — {}
state/students/marta_learned.json — {"student":"marta","day":0,"vocabulary_acquired":[],"grammar_acquired":[],"kannbeschreibungen_attempted":{},"persistent_errors":[],"emotional_state":"nervous, first day"}
state/students/james_learned.json — same shape
state/students/yuki_learned.json  — same shape
state/grader/progress.json        — {"marta":[],"james":[],"yuki":[]}
state/course/course_state.json    — {"current_day":{},"areas_covered":{}}
```

### Phase 5: The Runner (1 file)

```
runner.py — THE ONLY PYTHON FILE

  It does:
    1. Read command line args (--student marta --day 1)
    2. Load canon JSON (read-only)
    3. Load state JSON (read-write)
    4. Load prompt templates (read-only)
    5. Call planner API → get day plan → save to plans/generated/
    6. For each round 1-7:
       a. Assemble teacher prompt from template + canon + state + interstitials
       b. Call teacher API → get teacher message
       c. Assemble student prompt from template + learned state + overlay
       d. Call student API → get student response
       e. Assemble grader prompt from template + canon + exchange
       f. Call grader API → get verdict JSON
       g. Parse verdict → determine interstitials for next round
       h. Append exchange to output
    7. Call wrapup API → get updated memory
    8. Write updated state JSON files
    9. Write output JSON (the raw SMS thread data)
   10. Print SMS thread to terminal

  It does NOT:
    - Contain any German text (all German is in JSON)
    - Contain any pedagogical logic (all in prompt templates)
    - Contain any grading rules (all in grader prompts)
    - Contain any conversation flow decisions (all in round_frames + interstitials)
    - Know what a Kannbeschreibung is (it just reads the JSON key)

  The Python is ~200 lines. A loop, some JSON reads, some API calls.
```

---

## Build Order

```
Step  What                              Files    Depends on
────  ──────────────────────────────     ─────    ──────────
 1    Canon JSON                          6       nothing (source docs)
 2    Prompt templates                   12       canon (references wortfeld etc.)
 3    Plans + initial state              10       prompt templates (schema must match)
 4    Runner                              1       everything above
 5    Smoke test: 1 day, 1 student       —        all of the above
 6    Run Day 1 for all 3 students       —        step 5 passes
 7    Run Days 2-7 (full course)         —        step 6 passes
```

---

## Verification: Is It In JSON?

Before merging any work, check:

| Question | Answer must be YES |
|---|---|
| Can I delete runner.py and still read every conversation that happened? | The output/ JSON has everything. |
| Can I delete runner.py and still know what each student learned? | The state/ JSON has everything. |
| Can I delete runner.py and still see the full prompt that was sent? | The prompts/ JSON + canon/ JSON reconstruct it. |
| Can I rewrite runner.py in bash/Go/JS and get the same conversations? | Yes — it's just JSON in, API call, JSON out. |
| Is there a single `if` in Python that makes a decision about German? | No. LLMs make all German decisions via prompts. |

---

## File Count

```
canon/          6 files   (read-only reference data)
prompts/       12 files   (read-only prompt templates)
plans/          2 files   (read-only structure + template)
state/          8 files   (read-write, grows each run)
output/         0 files   (generated per run)
plans/generated 0 files   (generated per run)
runner.py       1 file    (disposable)
────────────────────────
Total:         29 files to create before first run
```
