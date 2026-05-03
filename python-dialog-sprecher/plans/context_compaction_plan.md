# Context Compaction Plan

## Purpose

This plan describes a reusable pattern for long-running conversation systems.

The core idea:

- keep the full record for humans
- keep a compressed durable summary for the system
- send only the compressed summary plus recent raw context back to the model

This avoids a false choice between "preserve history" and "control prompt
size." A good system does both.

## Why This Matters Here

In this repository, cumulative history is important because the operator is
trying to understand the active `Kannbeschreibung` through:

- grammar targets
- vocabulary targets
- supporting examples
- visible student progress over time

The failure mode is not merely "prompt too long." The deeper failure mode is
that a long raw accumulation makes the `Kannbeschreibung` harder to see.

## Three Layers

### 1. Full Artifact History

Keep everything needed for inspection and audit:

- full day outputs in `output/*.json`
- persistent student and teacher state in `state/**/*.json`
- source canon and prompt data in `canon/` and `prompts/`

This is the human-readable record.

### 2. Durable Compressed Memory

Persist a smaller structured summary that survives across runs.

For this project, that summary should include:

- current and recent `Kannbeschreibungen`
- target grammar
- target vocabulary
- key example sentences
- stable items
- unstable items
- repeated errors
- drift patterns
- most recent meaningful changes

This is the system memory.

### 3. Prompt-Time Working Context

Construct each model prompt from:

- the durable compressed memory
- the active day context
- only the most recent raw turns that still matter

This is the model-facing context.

## Proposed Artifacts

Add or derive explicit artifacts such as:

- `canon/kann_map.json`
- `state/students/*_summary.json`
- `state/course/kann_progress.json`

Suggested responsibilities:

- `kann_map.json`
  - links each `Kannbeschreibung` to grammar, vocabulary, speech acts, and
    examples
- `*_summary.json`
  - stores deduplicated stable and unstable learning state for a student
- `kann_progress.json`
  - stores what has been attempted, used correctly, and still unstable per
    `Kannbeschreibung`

## Compression Rules

Do:

- deduplicate learned items
- normalize vocabulary by lemma where practical
- separate stable vs unstable knowledge
- preserve repeated errors as first-class state
- keep a few high-value examples instead of many similar ones
- keep the most recent raw turns only when they still affect the next action

Do not:

- delete the full artifact history
- replace inspectable JSON with opaque runtime-only summaries
- keep appending duplicate grammar and vocabulary items forever
- confuse transcript storage with prompt payload

## UI Implications

The reader UI should prefer:

- active `Kannbeschreibung`
- target grammar
- target vocabulary
- example bank
- visible evidence in the transcript
- what became more stable over time

The UI should not force the operator to infer this from raw transcript alone.

## Implementation Steps

1. Define the compressed state schemas in JSON.
2. Add explicit per-Kann mappings from `Kannbeschreibung` to grammar,
   vocabulary, and examples.
3. Build summarizers that convert append-only learned state into deduplicated
   compressed summaries.
4. Change prompt assembly to use compressed summaries plus recent raw context.
5. Surface the compressed pedagogical state in the live UI.
6. Compare quality, drift, and cost before and after the change.

## Reuse Beyond This Repo

This pattern should generalize to other systems that have:

- long-running conversations
- persistent user or task state
- expensive context windows
- a need for human-readable audit trails

The reusable rule is:

`full artifacts for humans, compressed memory for the system, recent context for the model`
