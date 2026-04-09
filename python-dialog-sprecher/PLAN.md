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

## Review Standard

Prefer changes that do one or more of the following:

- improve dialog quality
- improve faithfulness to the JSON artifacts
- reduce hardcoded assumptions
- improve restartability and observability

Be cautious with changes that mainly:

- add Python structure without improving outputs
- move pedagogy into code
- create a second source of truth beside the JSON layer
