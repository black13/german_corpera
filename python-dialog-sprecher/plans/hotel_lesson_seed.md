# Hotel Lesson Seed

## Purpose

This file writes out one clean version of the idea:

`building -> roles -> typical actions -> utterances -> lexical fields -> grammar`

The point is not that a hotel is only a vocabulary item. In A1 material, a
building usually functions as a place-type with a small family of expected
actions.

This seed uses current project notes and user-provided source observations. It
should get a later source-audit pass before being treated as a public citation
artifact.

## Scene Ladder

- Big scene: Unterkunft / Hotel
- Small scene: hotel reception, information board, room, breakfast, payment,
  facilities, check-out
- Roles: guest, German-speaking guest, receptionist, hotel worker, learner as
  helper or mediator
- Speech act: ask for meaning, explain a simple hotel term, pass on practical
  information
- Text or utterance: a short sign, note, information-board item, or spoken
  explanation
- Lexical field: hotel, room, reception, breakfast, information, payment,
  facilities, time
- Grammar: simple present, W-questions, "Das bedeutet ...", Nominativ/Akkusativ
  where needed, temporal expressions such as `um` and `von ... bis`

## Action Family

Hotel carries a small set of likely A1 actions:

- reservieren / anmelden / einchecken
- an der Rezeption fragen
- Informationen lesen
- ein Wort oder Schild verstehen
- ein Wort oder eine kurze Information übersetzen
- den Pass zeigen
- ein Zimmer bekommen
- Frühstückszeiten verstehen
- bezahlen
- Einrichtungen benutzen
- ein- und ausgehen
- auschecken

For runtime prompts, these actions should not all be forced into one class. They
are nearby options the teacher can use to keep a hotel lesson concrete, or to
recover when a student drifts.

## Roles

- Receptionist: gives information, asks for a passport, answers questions,
  explains room, breakfast, payment, and check-out.
- Guest: asks what something means, asks where to pay or go, gives personal
  data, shows a passport, asks about breakfast or the room.
- German-speaking guest: may need help understanding an English or hotel term
  on an information board.
- Learner as mediator: translates or explains one simple term or practical item
  for the guest.

## Hotel Words And Objects

- Hotel
- Rezeption
- Information
- Informationstafel
- Pass
- Prospekt
- Zimmer
- Schlüssel / Karte
- Frühstück
- Buffet
- WLAN / Internet
- Aufzug
- Rechnung
- Uhrzeit
- Check-out / Abreise

## Utterance Patterns

These are prompt seeds, not fixed required answers:

- "Was bedeutet ...?"
- "Das bedeutet ..."
- "Das Frühstück ist von sieben bis zehn Uhr."
- "Check-out ist bis elf Uhr."
- "Die Abreise ist bis elf Uhr."
- "Hier ist mein Pass."
- "Ich habe eine Reservierung."
- "Wo muss ich bezahlen?"
- "Sie bekommen ein Zimmer ..."
- "Der Aufzug ist links / rechts."
- "Bitte den Aufzug nicht benutzen."

## Rules For The Teacher Prompt

- Start from the small scene, not from an abstract grammar topic.
- Keep the target speech act visible: the student should explain or translate a
  simple hotel item, not merely talk about hotels in general.
- Accept broken A1 language if the target action is attempted.
- Redirect if the student only gives social closing formulas or personal chat
  without performing the hotel action.
- Use nearby hotel actions as recovery material, not as a reason to replace the
  target Kannbeschreibung.
- Keep grammar attached to the utterance need. For K176, time expressions and
  "Das bedeutet ..." matter because they make the hotel information usable.

## Direct Versus Inferred Support

Directly supported by project notes and observed examples:

- hotel as a place-type in A1 materials
- hotel words such as Hotel, Rezeption, Information, Pass
- example-like patterns such as asking what a word means and asking where to
  pay
- K176: explaining a simple hotel information-board term for a German-speaking
  guest

Close inference from the same material:

- hotel action family: reserve, check in, ask at reception, read information,
  show passport, get a room, understand breakfast times, pay, use facilities,
  enter/leave, check out
- building -> roles -> typical action as a reusable lesson-planning pattern

## Compact Prompt Shape

For a future teacher-preparation prompt, Hotel can be compressed as:

`Hotel = reception + guest + information board + room/breakfast/payment/check-out`

`Core actions = ask, show, read, understand, explain/translate, get, pay, use, leave`

`Core utterances = Was bedeutet ...? / Das bedeutet ... / von ... bis ... / Wo muss ich bezahlen?`

`Grammar follows from the utterance: W-questions, simple present, time phrases, Das bedeutet ...`
