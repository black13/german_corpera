# KB Relationship Prompt System

This note documents the small prompt-system change made after the K176/hotel discussion.

## Core Idea

The runner should not treat every Kannbeschreibung as an isolated task. Some KBs are scene-specific, while others are global support machinery.

The planning ladder is:

```text
global ability -> domain/place system -> role -> small scene -> speech act -> text/utterance -> lexical field -> grammar tool
```

Example:

```text
K176 -> hotel -> information board -> guest/worker -> explain a word -> "Das bedeutet..." -> hotel/time/direction words -> von...bis / bis / hier / dort
```

## Relationship Groups

The relationship groups now live in `canon/kann_relationships.json`.

- A1 conversation support: K001, K003, K004, K005, K006, K007, K030, K038.
- Social contact operators: K009, K010, K014, K017, K018, K022, K026.
- Numbers/time as exchange currency: K034, K064, K067, K075, K129, K141.
- Text/list reading: K060, K062, K084, K085, K086, K092, K104, bridging to K163 and K176.
- Micro-writing: K043, K048, K051, K052, K136, K145, K149, K150.
- Oral production frame: K116, K117, K120, K121, K126.

These groups are not meant to replace the current KB. They explain how the current KB can be performed at A1.

## Staged Prompting

In early rounds, a student may state the task or KB in English or meta-language, for example:

```text
We are translating the hotel sign.
```

That should not automatically count as drift. The teacher should accept it as orientation and recast it in simple German:

```text
Ja, genau: Heute erklären wir ein Wort auf Deutsch. Der Gast fragt: Was bedeutet "breakfast"?
```

Then the teacher should put the student back into the concrete scene and ask for the actual utterance.

James Chen now carries this as a learner trait: he can often explain the goal in English but still cannot produce the German utterance. The teacher should treat that as useful orientation, paraphrase it into simple German, and then require the small spoken/written action.

## Draft Course Map

The course map is not complete curriculum. It is a planning scaffold in `canon/a1_syllabus_branches.json`.

Current draft branches include:

- A1 speaking operating system.
- Social entry and exit moves.
- Information currency.
- Text/list to message.
- Micro-writing exchange.
- Service place systems.

The teacher may briefly say where the current KB sits, for example "Das gehört zu..." or "Das hilft uns bei..." but must immediately return to the concrete KB scene. The draft map must not be presented as official, exhaustive, or more important than the current Kannbeschreibung.

## Grader Rule

The grader should distinguish between:

- task orientation in English/meta-language, which can be acceptable in early rounds;
- full task drift, where the student never performs or approaches the target speech act;
- teacher drift, where the teacher praises, lectures, or opens a new topic without giving a concrete chance to perform the KB.

## Canon Repair

The following truncated production KBs were repaired from `reference/ocr_text_only.txt`:

- K116
- K118
- K121
- K125

K118 was not in the original short list, but it had the same line-break truncation problem.

## Phone UI Pass

The current phone pass is intentionally modest:

- mobile header is sticky;
- messages use full width on small screens;
- touch controls are larger;
- scorecard scrolls horizontally instead of forcing the page to overflow;
- run form stacks on narrow screens.
- a browser-local Workbench Notes panel lets the reader write observations while watching a run; live polling must not overwrite this text.

This is not a full mobile redesign. It is a first usability pass so the existing live conversation view is more usable on a phone.
