# A1 Closed Production System

## Core claim

The A1 `Kannbeschreibungen` can be written in higher-level German. That does
not mean the learner has to produce that higher-level German.

The descriptor language is teacher/planner metalanguage. The learner-facing
language must stay inside a much smaller A1 production system.

```text
Kannbeschreibung language = planning language
student performance language = A1 closed production inventory
```

Example:

```text
KB: Kann im Hotel einfache Begriffe auf der Informationstafel
    für einen deutschsprachigen Gast übersetzen.

Student does not need to say:
    "Ich kann Begriffe auf der Informationstafel übersetzen."

Student needs to say:
    "Das bedeutet Frühstück."
    "Frühstück ist von sieben bis zehn Uhr."
    "Ist das klar?"
```

## The closed-system rule

For generated classroom dialogue, expected learner answers, and correction
models, A1 should behave as a closed system:

- use the known A1 vocabulary inventory first;
- use fixed chunks and reusable sentence frames;
- use present-tense verbs as the default production tense;
- prefer concrete nouns, places, times, numbers, and visible objects;
- keep one main idea per sentence;
- avoid leaking the abstract wording of the `Kannbeschreibung` into the
  student's required output.

This is a production rule, not a rule against teacher planning. Planning notes
may use words like `Sprachmittlung`, `Rezeption`, `Aufschrift`, `Deutschsprachige`,
`Basiswortschatz`, or `Informationstafel`. The student output should usually be
much smaller:

```text
Das ist ...
Das bedeutet ...
Ich habe ...
Ich brauche ...
Ich möchte ...
Ich gehe ...
Ich komme ...
Es ist ...
Es gibt ...
von ... bis ...
um ... Uhr
hier / dort / links / rechts
```

## Closed does not mean tiny

The closed system is generative because it combines:

- a bounded vocabulary inventory;
- a bounded set of present-tense verb frames;
- a bounded set of sentence patterns;
- recurring concrete scenes;
- visible carriers such as signs, forms, lists, timetables, and boards.

That is enough to create many tasks without leaving A1.

```text
word bank + present verb frame + scene role + carrier/object = A1 output
```

Examples:

```text
Hotel + bedeuten + Informationstafel:
Das bedeutet Frühstück.

Formular + brauchen + Name:
Ich brauche Ihren Namen.

Aushang + sein + Uhrzeit:
Der Kurs ist um acht Uhr.

Schild + dürfen + nicht:
Sie dürfen hier nicht rauchen.
```

## Why this matters for the KB system

Many A1 descriptors contain words that are not good learner production targets.
They describe what the learner can do, not what the learner must say.

Bad teacher move:

```text
Heute üben wir Sprachmittlung. Sie geben anderssprachige Informationen
Deutschsprachigen in Einzelwörtern auf Deutsch weiter.
```

Better teacher move:

```text
Ein Gast zeigt auf "breakfast".
Er fragt: Was bedeutet das?
Sie sagen: Das bedeutet Frühstück.
```

The first version is descriptor language. The second version is the actual A1
performance.

## Relation to A1 Wortschatz

The A1 vocabulary list acts like a closed inventory for production. It is not
the whole German language, and it is not the full language of the descriptors.

For this project, the product should distinguish:

- **passive/planning words**: words the teacher, grader, or UI may use to
  explain the task;
- **active learner words**: words the student should be expected to produce;
- **scene labels/proper labels**: foreign signs or special labels that may
  appear as visible input, but are explained with A1 German.

Example:

```text
visible input: breakfast
active A1 output: Frühstück
frame: Das bedeutet Frühstück.
```

The foreign or higher-level word can appear as an object in the scene. It should
not force the learner to use non-A1 explanatory language.

## Present tense as the default engine

The basic production engine should be present tense:

```text
Ich bin ...
Ich habe ...
Ich komme ...
Ich gehe ...
Ich brauche ...
Ich möchte ...
Ich kann ...
Das ist ...
Das bedeutet ...
Der Kurs beginnt ...
Der Bus fährt ...
Das kostet ...
```

Other forms can exist as fixed chunks when a KB demands them, but they should
not become the default generation mode. The default A1 simulation should ask:

```text
Can this be said with an A1 word and a present-tense frame?
```

If yes, use that. If no, simplify the scene or change the required output.

## Practical generator rule

For every KB, derive two layers:

```text
1. Descriptor layer:
   full German KB, category, planning explanation, relationship to other KBs

2. Production layer:
   A1 words + present-tense frames + fixed chunks + acceptable tiny answers
```

The teacher prompt and grader should be built from the production layer. The UI
can expose the descriptor layer for the human reader, but the simulated student
should not be asked to reproduce descriptor language.

## Grader implication

A student should pass when the target action is completed inside the A1 closed
system.

The grader should reward:

- correct speech act;
- recoverable meaning;
- A1-sized phrase or sentence;
- present-tense/simple-frame solution;
- correct use of a visible input item when relevant.

The grader should not require:

- abstract descriptor vocabulary;
- grammatical completeness beyond A1;
- full sentence translation;
- B1-style explanation;
- adult administrative sophistication.

## Short formula

```text
A1 KB execution = complex descriptor translated into simple scene + A1 word bank + present-tense frame
```

For K173-K176:

```text
Descriptor: anderssprachige Informationen von Schildern und Aufschriften weitergeben
Scene: tourist points at a sign
Input: "fermé"
A1 output: Das bedeutet geschlossen.
```
