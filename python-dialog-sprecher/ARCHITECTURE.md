# Sprecher Architecture

## Primary Goal

The goal of this project is to generate multi-day A1 classroom conversations
that are worth reading.

The main product is not the Python runtime. The main product is the combination
of:

- canon data
- prompt templates
- persistent teacher/student/grader state
- generated conversation artifacts

If a change improves code cleanliness but does not improve conversation quality,
reproducibility, or inspectability, it is not automatically a good change.

## Boundary

### Artifact layer: the real course logic

These files define what the course is:

- `canon/*.json`
- `prompts/**/*.json`
- `plans/*.json`
- `state/**/*.json`
- `output/*.json`
- `config/runtime.json`

This layer contains:

- pedagogical framing
- student personas
- teacher behavior
- grader behavior
- course memory
- runtime configuration such as roster and model selection

### Runtime layer: execution only

`runner.py` exists to execute the artifact layer.

It may:

- read JSON
- assemble prompts from JSON plus state
- call model APIs
- write outputs and updated state
- render a local monitoring view

It should not become the place where the course design lives.

## Current Runtime Model

This is the v2 classroom model.

- One `Kannbeschreibung` runs per day.
- All configured students participate in the same classroom session.
- Each day runs through the round sequence defined in
  `prompts/teacher/round_frames.json`.
- The teacher, each student, the per-round grader, the day summary grader, and
  the wrapup step are all driven by prompt files plus runtime state.
- The runner serves a lightweight local HTML view so the run can be watched as it
  progresses.

## History Layers

This system should distinguish three different kinds of history.

### 1. Full Artifact History

Keep the complete readable record in JSON artifacts such as:

- `output/*.json`
- `state/**/*.json`

This is for the human operator. It should remain inspectable and cumulative.

### 2. Durable Compressed Memory

Keep a smaller structured summary for reuse across days and restarts.

For this project, compressed memory should emphasize:

- active and recent `Kannbeschreibungen`
- target grammar
- target vocabulary
- supporting examples
- stable vs unstable learning
- repeated errors and drift

This is the layer the runtime should prefer when reconstructing context.

### 3. Prompt-Time Working Context

Each model call should be built from:

- compressed durable memory
- active day context
- only the recent raw turns that are still relevant

The runtime should not keep feeding raw cumulative append-only history back into
every prompt if a smaller pedagogically meaningful summary can carry the same
information more faithfully.

## Compression Rule

Preserve full history. Compress prompt payload.

That rule is important here because the operator is not merely watching a chat
system. The operator is trying to understand the active `Kannbeschreibung`
through grammar, vocabulary, examples, and visible progress over time.

So the system should reduce prompt bloat in a way that makes the
`Kannbeschreibung` more legible, not less.

## Current Directory Layout

```text
python-dialog-sprecher/
├── config/
│   └── runtime.json          runtime roster, model selection, server config
├── canon/
│   └── *.json                reference content
├── prompts/
│   ├── teacher/
│   ├── students/
│   ├── grader/
│   └── interstitials/
├── plans/
│   ├── course_structure.json
│   └── generated/            generated plan artifacts when used
├── state/
│   ├── teacher/
│   ├── students/
│   ├── grader/
│   └── course/
├── output/                   generated day artifacts
├── logs/                     scratch run logs
├── tools/                    one-off utilities and migration scripts
├── reference/                source PDFs, OCR text, and other reference inputs
├── runner.py                 execution runtime
├── reset.sh                  restore initial state shapes and clear generated data
└── PLAN.md                   current cleanup/build plan
```

## What Lives In JSON Now

The following are intentionally treated as data, not implementation detail:

- student roster
- teacher/grader/wrapup model selection
- student personas and generation rules
- teacher persona
- round structure
- interstitial instructions
- grader criteria
- course state and memory
- compressed pedagogical summaries

## What Still Lives In Python

The following remain in `runner.py` on purpose:

- prompt assembly order
- API invocation
- local HTML rendering
- persistence mechanics
- classroom execution loop

Those are runtime concerns. They should stay narrow and should not absorb the
course design itself.

The runtime may derive compressed summaries, but those summaries should be
persisted back into inspectable artifacts instead of living only as hidden
Python internals.

## Evaluation Standard

When reviewing changes, prefer these questions:

1. Does this improve the readability and coherence of the generated dialogs?
2. Does this make the course behavior easier to inspect and edit through JSON?
3. Does this improve reproducibility or reduce drift between docs and runtime?
4. Does this avoid moving pedagogical decisions into Python unnecessarily?

## Anti-Drift Rule

The main failure mode in this repo is not "the Python is too simple."
The main failure mode is letting the runtime become the center of gravity and
then optimizing the runtime instead of the conversations.

Changes to `runner.py` are justified when they:

- remove hardcoded runtime assumptions that belong in JSON
- improve observability
- improve reproducibility
- make artifact-driven behavior execute more faithfully

Changes are not justified merely because they make the Python look more like a
conventional application.
