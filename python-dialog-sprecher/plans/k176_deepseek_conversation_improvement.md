# K176 DeepSeek Conversation Improvement Pass

Source: local DeepSeek reasoner call over compact K176 transcript, Qwen relationship note, and canon focus JSON.

```markdown
## 1. What worked
- **Core Mediation Pattern**: Students consistently performed the core speech act: asking "Was bedeutet...?" and providing a translation/explanation. (R6: `"Was bedeutet Housekeeping? Das bedeutet... Putzen? Zimmer sauber machen."`).
- **Situational Fidelity**: Most prompts correctly placed the student in the role of a hotel employee mediating for a German-speaking guest.
- **Vocabulary Integration**: Words from the `wohnen` and `zeit` fields (Zimmer, Uhr, von...bis) were used naturally in explanations (R3, R7).
- **Realistic A1 Language**: Broken German and elliptical structures were accepted when the mediation succeeded (R6, R7).

## 2. What failed or drifted
- **Empty Teacher Turn**: In R2 Erkundung for Marta, the teacher turn is `[EMPTY]`, causing student drift into irrelevant questioning (`"Ja, genau. Und was machen Leute im Hotel?"`).
- **Drifting from Mediation to General Q&A**: The initial "Kontakt" round for all students focused on "Warum gehen Leute in ein Hotel?" and "was brauchen Sie?". This is personal data exchange, not mediation, and delays the target skill.
- **Weak Use of Target Speech Act**: The speech act `"signalisieren, dass man etwas (nicht) verstanden hat"` is underutilized. It only appears in R4 (Marta: `"Ich weiß nicht."`) as a complication, not as a core strategy for the mediator.
- **Grammar Mismatch**: The grammar target `"Nominativ und Akkusativ"` is not foregrounded. Mediation explanations often use simple nominative phrases (`"Das bedeutet Parkplatz."`) or prepositional phrases (`"Frühstück von sieben bis zehn Uhr."`). The accusative in `"fÜr einen deutschsprachigen Gast"` is never practiced.
- **Uncertain Prerequisite Reliance**: The conversation assumes students can already ask "Was bedeutet...?" (from K173). This is reasonable as a *bridge*, but the initial scene should solidify this bridge before adding new complexity.

## 3. Better lesson ladder for K176
**Big Scene:** Hotel Lobby / Reception Area with Information Board.
**Small Scene:** A German-speaking guest points to a word on the board (e.g., "breakfast," "check-out," "reception") and looks confused. The student (hotel employee) mediates.
**Speech Act Sequence:**
1.  **Signal non-understanding (Guest):** Guest uses body language or a simple "Hm?".
2.  **Ask for meaning (Mediator):** "Was bedeutet [Wort]?"
3.  **Provide translation (Mediator):** "Das bedeutet [Deutsches Wort]." OR "[Deutsche Erklärung]."
4.  **Signal understanding/request clarification (Mediator):** "Verstehen Sie?" / "Ist das klar?" (Activating the target speech act as a strategy).
**Utterance/Text:** Short, formulaic phrases centered on the mediation act.
**Lexical Field:** `wohnen` (Zimmer), `zeit` (Uhr, von...bis, am), `verkehr` (links, rechts, hier) used to *give context* to the translated term (e.g., "Das bedeutet Frühstück. Das ist hier, links.").
**Grammar Emergence:** Prepositional phrases for location/time (`auf der Tafel`, `von...bis`, `hier links`). Accusative appears only in the fixed phrase `"fÜr Sie"` (for the guest).

## 4. Concrete teacher prompt changes
- **R1 Kontakt:** Start *in medias res*. Remove "Warum gehen Leute..." questions.
    * **New Prompt:** "Guten Tag. Stellen Sie sich vor, Sie arbeiten im Hotel. Ein deutschsprachiger Gast zeigt auf das Wort 'breakfast' an der Informationstafel. Er versteht es nicht. Was sagen Sie zuerst?" (Forces immediate "Was bedeutet...?").
- **R2 Erkundung:** Eliminate empty turns. Prompt should introduce a *second* term from the board to translate, incorporating a direction or time.
    * **New Prompt:** "Gut. Jetzt zeigt der Gast auf ein anderes Wort: 'Reception'. Wo ist die Reception? Können Sie das dem Gast sagen? Zum Beispiel: 'Das bedeutet Empfang. Der Empfang ist dort.'"
- **R4 Komplikation:** Instead of asking for a room location the student doesn't know, have the guest signal *they still don't understand* the translation. This practices the "signal understanding" act.
    * **New Prompt:** "Sie sagen 'Das bedeutet Frühstück.' Der Gast sieht unsicher aus und sagt 'Frühstück...?'. Wie können Sie sichergehen, dass er es versteht?"

## 5. Concrete grader changes
- **Priority Order:** Grade successful mediation (successful meaning transfer) above grammatical perfection of the explanation.
- **"Steering" for Drift:** If a student answers a mediation prompt with personal data (e.g., "Ich brauche Frühstück"), the grader should state: `DRIFTING | act=persönliche Daten angeben | steering=Das ist gut zu wissen! Aber hier sind Sie der Hotelmitarbeiter. Der Gast versteht 'breakfast' nicht. Was fragen Sie IHN?`
- **Activate Target Speech Act:** When a student successfully translates, the grader's "steering" for the next prompt should encourage them to check understanding: `ON TRACK | steering=Perfekt übersetzt. Jetzt eine wichtige Frage für den Gast: Können Sie fragen 'Verstehen Sie?' oder 'Ist das klar?'`

## 6. Improved seed examples
Add examples that model the full mediation exchange and incorporate the target grammar/vocabulary naturally.

```json
{
  "text": "Gast: (zeigt auf Schild) Breakfast? \nMitarbeiter: Was bedeutet 'breakfast'? Das bedeutet Frühstück. Frühstück ist von sieben bis zehn Uhr. Verstehen Sie?",
  "source": "improved",
  "note": "Models Q&A, translation, time phrase, and understanding check."
},
{
  "text": "Schild: Check-out 11 am \nErklärung für Gast: Das bedeutet: Sie müssen das Zimmer bis elf Uhr verlassen.",
  "source": "improved",
  "note": "Models translation + explanation with accusative 'das Zimmer' and temporal 'bis'."
},
{
  "text": "Gast: Das Wort 'pool'? \nMitarbeiter: 'Pool'? Das ist der Swimmingpool. Der Pool ist im Garten. Ist das klar?",
  "source": "improved",
  "note": "Models repetition of term, translation, location (im Garten), and clarification check."
}
```

## 7. Sample improved round sequence (for Marta)
- **R1 Kontakt:** Teacher: "Frau Kowalska, Sie arbeiten im Hotel. Ein Gast zeigt auf die Informationstafel zum Wort 'breakfast'. Was sagen Sie?" Student: "Was bedeutet 'breakfast'? Das bedeutet Frühstück."
- **R2 Erkundung:** Teacher: "Sehr gut. Jetzt zeigt der Gast auf 'check-out'. Was sagen Sie?" Student: "Was bedeutet 'check-out'? Das bedeutet... Sie müssen gehen... bis elf Uhr?"
- **R3 Modell:** Teacher: "Fast richtig. Für die Prüfung: 'Das bedeutet: Sie müssen das Zimmer bis elf Uhr verlassen.' Bitte wiederholen." Student: "Das bedeutet: Sie müssen das Zimmer bis elf Uhr verlassen."
- **R4 Komplikation:** Teacher: "Perfekt. Sie sagen das zum Gast. Der Gast fragt: 'Verlassen? Das Zimmer?' Er sieht unsicher aus. Was sagen Sie?" Student: "Äh... Ja. Das Zimmer. Bis elf Uhr. Verstehen Sie?"
- **R5 Korrektur:** Teacher: "Die Idee war sehr gut! 'Verstehen Sie?' ist perfekt. Ein kleiner Tipp: Sie können auch sagen 'Ist das klar?'" Student: "Ah, okay. Ist das klar?"
- **R6 Übung:** Teacher: "Genau. Neue Übung: Der Gast zeigt auf 'luggage storage'." Student: "Was bedeutet 'luggage storage'? Das bedeutet... Koffer aufbewahren. Ist das klar?"
- **R7 Prüfung:** Teacher: "Prüfungssituation. Der Gast zeigt auf 'dining room'." Student: "Was bedeutet 'dining room'? Das bedeutet Speisesaal. Der Speisesaal ist hier links. Verstehen Sie?"

## 8. JSON artifact changes to make next
```json
{
  "changes_to_focus_json": [
    {
      "field": "speech_acts",
      "new_value": [
        "nachfragen (Was bedeutet [Wort]?)",
        "Übersetzen/Erklären (Das bedeutet [X]. / [X] ist hier, [Richtung].)",
        "Verständnis sichern (Verstehen Sie? / Ist das klar?)"
      ],
      "reason": "Sequences the acts logically for the mediation scenario and explicitly adds the underused 'Verständnis sichern' act as a core strategy."
    },
    {
      "field": "grammar_targets",
      "new_value": [
        "Temporale Präpositionen: von...bis, bis, am",
        "Lokale Präpositionen: hier, dort, links, rechts (für Erklärungen)"
      ],
      "reason": "These emerge naturally from giving times and locations for translated terms (e.g., 'Frühstück von 7 bis 10 Uhr', 'Der Aufzug ist dort rechts'). 'Nominativ/Akkusativ' is less central to this specific mediation act."
    },
    {
      "field": "wortfeld_targets",
      "action": "add",
      "new_value": ["richtung"],
      "reason": "Giving simple directions ('hier links', 'dort rechts') is a natural way to expand a translation for a guest and uses the existing 'verkehr' samples."
    }
  ]
}
```