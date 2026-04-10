# Instructor Planning Workflow

## Position

This system does not need to prove that an AI can replace the teacher.

A more valuable and more realistic goal is:

- help a busy instructor unpack a `Kannbeschreibung`
- connect it to grammar, vocabulary, and speech acts
- gather useful examples from trusted materials
- generate plausible classroom pathways
- keep the resulting curriculum logic inspectable

The conversation generator is one useful consumer of that planning work. It is
not the whole product.

## Core Split

Use two different model tiers for two different jobs.

### Cheap Runtime Layer

Use cheaper or local models for:

- daily classroom simulation
- student turns
- grader passes
- routine conversation generation
- low-cost iteration while watching the run

This layer should prioritize readability, continuity, and cost control.

### Expensive Planning Layer

Use stronger models, including burst compute on Vast AI, for:

- `Kannbeschreibung` unpacking
- teacher preparation notes
- lesson-seed generation
- curriculum linking across levels
- synthesis of telc materials and textbook examples
- post-run review of what worked and what drifted

This layer should prioritize depth, synthesis, and planning quality.

## Lesson Seed Shape

Each important `Kannbeschreibung` should eventually have a lesson seed that
contains at least:

- scene
- roles and relationships
- core words
- likely sign or form language
- target speech acts
- target grammar
- prior dependencies
- likely learner drift paths
- likely recovery moves
- telc-style task patterns
- textbook or library examples with source notes

Example for hotel mediation tasks:

- scene: hotel reception / information board / guest asks for meaning
- dependencies: greeting, person, place, time, asking what a word means
- words: Frühstück, Check-out, Rezeption, Zimmer, WLAN, Buffet
- speech acts: ask meaning, translate a term, explain a short notice, react to
  thanks

## Workflow

1. Run the classroom day cheaply and preserve the full JSON artifact.
2. Preserve per-call usage, estimated cost, and full provider response JSON.
3. Send the finished artifact plus canon and trusted source notes to a stronger
   planning job.
4. Produce improved lesson seeds, curriculum notes, and source-backed examples.
5. Feed those improvements back into the next cheap run.

## Why This Matters

This architecture makes the repository useful even if no instructor ever wants
the AI to act as the actual teacher in the room.

It still provides value by reducing preparation load and by making the
pedagogical structure around each `Kannbeschreibung` easier to see, revise, and
reuse.
