# Current Plan

## Working Position

This repository is already in use as a v2 classroom prototype.
The immediate goal is not to redesign it from scratch. The immediate goal is to
reduce drift so the repository accurately reflects how it currently works.

## Current Priorities

1. Keep course logic in JSON where practical.
2. Keep `runner.py` small and execution-focused.
3. Make reset/restart behavior deterministic.
4. Keep source material, tools, runtime state, and generated outputs clearly
   separated.
5. Judge progress by conversation quality, not by Python sophistication.
6. Preserve cumulative learning history without sending raw cumulative history
   into every model call.
7. Use cheaper runtime generation for day-to-day classroom simulation and
   reserve expensive models for curriculum planning, teacher preparation, and
   post-run analysis.
8. Treat the system as a planning aid for busy instructors, not as a claim that
   the AI itself must become the real teacher.

## Concrete Work Items

### 1. Runtime Config

Maintain `config/runtime.json` as the single place for:

- classroom roster
- teacher model selection
- grader model selection
- wrapup model selection
- local server settings

This prevents roster and model drift from accumulating in `runner.py`.

### 2. Prompt and State Discipline

Treat these as first-class editable logic:

- `prompts/teacher/*.json`
- `prompts/students/*.json`
- `prompts/grader/*.json`
- `prompts/interstitials/*.json`
- `state/**/*.json`

When behavior changes, first ask whether the change belongs in one of these
files instead of in Python.

### 3. Reset Behavior

`reset.sh` should:

- stop the local runner if it is active
- restore the documented initial state shapes
- preserve the configured student roster
- clear generated outputs

An empty object is not the same thing as a valid initial state.

### 4. Repository Hygiene

Keep the root focused on the active runtime.

- Move one-off migration utilities into `tools/`
- Move source PDFs, OCR text, and other reference inputs into `reference/`
- Avoid leaving scratch run logs in the root when they are not meaningful

### 5. Documentation

`ARCHITECTURE.md` and `PLAN.md` should describe the current classroom model, not
an older single-student or planner-heavy design that the runtime no longer
implements.

### 6. Cumulative State Compression

Keep the cumulative record. Compress the prompt payload.

This project needs both:

- a full readable history for the human operator
- a smaller working summary for the model

Do not treat these as the same thing.

The full record should remain in:

- `output/*.json`
- `state/**/*.json`
- future per-Kann mapping artifacts

The prompt-time working summary should be derived from that record and should
favor pedagogical signal over raw transcript bulk.

The intended summary shape is:

- active `Kannbeschreibung`
- related prior `Kannbeschreibungen`
- target grammar
- target vocabulary
- supporting examples
- stable learned items
- unstable learned items
- repeated errors
- what changed on the current day

The main purpose is not just cost control. The main purpose is to keep the
active `Kannbeschreibung` legible while reducing prompt drift, duplication, and
provider spend.

This should be designed as a reusable pattern that can be shared across other
conversation-heavy systems:

- preserve full artifacts
- persist a compressed durable summary
- send only the compressed summary plus recent raw turns back to the model

### 7. Teacher Preparation Layer

The teacher should not be forced to improvise from a bare `Kannbeschreibung`.

Add or derive per-Kann preparation artifacts that make the instructional target
explicit before class generation begins.

The intended lesson-seed shape should include:

- the scene and role relationship
- core words and likely signboard terms
- core speech acts
- prior dependencies such as person, place, time, greeting, and clarification
- likely learner drift paths
- natural recovery or redirection paths
- telc-style task expectations
- curated examples from books, mock tests, or other trusted materials

This preparation layer should improve both the runtime prompts and the value of
the repository as an instructor planning tool.

### 8. Curriculum Planning Workflow

Use two different compute modes for two different jobs.

Cheap/local generation should handle:

- classroom runs
- readable conversation artifacts
- grader summaries
- routine iteration

More expensive models, including burst compute on Vast AI, should be reserved
for:

- unpacking a `Kannbeschreibung`
- building or revising lesson seeds
- synthesizing telc and textbook material
- proposing curriculum links across A1, A2, and B1
- auditing generated runs and feeding improvements back into the planning layer

The main workflow should become:

1. run a day cheaply
2. preserve the full artifact and billing data
3. hand the finished artifact to a stronger planning job
4. update lesson seeds and curriculum notes
5. feed those improvements back into future cheap runs

### 9. Billing and Full Response Preservation

The runtime should preserve enough execution data to support later review.

That includes:

- per-call usage
- per-day and session-level estimated pricing
- full JSON responses from providers such as DeepSeek

This is important not only for cost control, but for prompt analysis and for
post-run planning jobs that need the original model output rather than only the
cleaned transcript text.

## Runtime Snapshot

Current runtime behavior:

- load `config/runtime.json`
- load canon, prompts, and current state
- run one classroom day per `Kannbeschreibung`
- loop through all configured students inside each round
- grade each exchange
- summarize each student day
- update memory and learned state
- write the day artifact to `output/`
- serve a local HTML view during execution

Target runtime behavior after compression work:

- preserve full day artifacts and state history on disk
- maintain a compressed per-student working summary
- maintain a compressed per-Kann view of grammar, vocabulary, and examples
- build prompts from compressed memory plus current-day context, not from raw
  cumulative append-only state
- expose per-run billing and saved provider response data for later analysis
- support a post-run planning pass that updates curriculum artifacts

## Review Standard

Prefer changes that do one or more of the following:

- improve dialog quality
- improve faithfulness to the JSON artifacts
- reduce hardcoded assumptions
- improve restartability and observability
- reduce prompt bloat without hiding pedagogical state
- strengthen the repository as an instructor planning tool
- reserve expensive model usage for planning tasks that justify it

Be cautious with changes that mainly:

- add Python structure without improving outputs
- move pedagogy into code
- create a second source of truth beside the JSON layer
- spend expensive model time on routine low-value turn generation
