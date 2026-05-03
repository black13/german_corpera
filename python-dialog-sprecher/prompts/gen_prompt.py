#!/usr/bin/env python3
"""Generate DeepSeek prompts for telc A1 exam practice.
Usage: python gen_prompt.py lesen [1|2|3|all]
       python gen_prompt.py horen [1|2|3|all]
       python gen_prompt.py sprechen [1|2|3|all]
       python gen_prompt.py schreiben [1|2|all]
       python gen_prompt.py kb K100
"""
import json, sys, os

CANON = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                      '..', '..', 'canon')
if not os.path.exists(CANON):
    # Running from temp, adjust
    CANON = '/Users/jjosburn/Documents/programming/german_corpera/python-dialog-sprecher/canon'

def load_data():
    with open(f'{CANON}/kannbeschreibungen_full.json') as f:
        kbs = {k['id']: k for k in json.load(f)['kannbeschreibungen']}
    with open(f'{CANON}/grammatik.json') as f:
        grammatik = json.load(f)
    with open(f'{CANON}/wortfelder.json') as f:
        wf = json.load(f)
    with open(f'{CANON}/kann_reductions.json') as f:
        red = json.load(f)
    return kbs, grammatik, wf, red

def grammar_summary(grammatik):
    out = []
    for cat, rules in grammatik.items():
        out.append(f"{cat}:")
        for r in rules:
            out.append(f"  - {r}")
    return "\n".join(out)

def vocab_summary(wf, max_items=8):
    out = []
    fields = ['person','familie','beruf','einkaufen','lebensmittel','getränke',
              'restaurant','wohnen','möbel','verkehr','zeit','freizeit','zahlen']
    for field in fields:
        words = wf.get(field, [])[:max_items]
        out.append(f"{field}: {', '.join(words)}")
    return "\n".join(out)

def kb_for_cluster(kbs, cluster_name):
    """Map cluster name to KB IDs"""
    clusters = {
        'lesen_1': ['K111','K112','K113','K114','K115'],
        'lesen_2': ['K087','K092','K095','K085'],
        'lesen_3': ['K100','K101','K102','K103','K104'],
        'horen_1': ['K060','K068','K069','K070','K071'],
        'horen_2': ['K063','K064','K074','K075'],
        'horen_3': ['K066','K067','K076','K079'],
        'sprechen_1': ['K121','K122','K123','K124','K014','K015','K016','K017'],
        'sprechen_2': ['K022','K023','K024','K025','K018','K019','K020','K021'],
        'sprechen_3': ['K026','K027','K028','K029'],
        'schreiben_1': ['K137','K138','K149','K150'],
        'schreiben_2': ['K149','K150','K151','K152'],
    }
    ids = clusters.get(cluster_name, [])
    return [kbs[kid] for kid in ids if kid in kbs]

def prompt_lesen(kbs, grammatik, wf, red, teil='all'):
    base = f"""You are a telc Deutsch A1 exam author. Your task: generate Lesen (reading) practice questions.

## A1 Grammar Constraints
{grammar_summary(grammatik)}

## Vocabulary
Use ONLY these A1 words and their simple inflections. No words outside this list unless they are proper names.

{vocab_summary(wf, max_items=10)}

## Kannbeschreibungen (can-do statements being tested)
"""
    if teil == '1' or teil == 'all':
        for k in kb_for_cluster(kbs, 'lesen_1'):
            base += f"  {k['id']}: {k['kann'][:200]}\n"
        base += """
## Lesen Teil 1 — Kurze Texte (Richtig/Falsch)
Two short everyday texts (notes, emails, invitations, messages). Each has 2-3 statements. 
FALSE statements are false because of ONE meaning-changing word: "vielleicht", "leider", "aber", "nicht", "noch nicht", "schon".
Example: "Die Party beginnt um 18 Uhr." — FALSE if text says "Vielleicht um 18 Uhr."
"""
    if teil == '2' or teil == 'all':
        for k in kb_for_cluster(kbs, 'lesen_2'):
            base += f"  {k['id']}: {k['kann'][:200]}\n"
        base += """
## Lesen Teil 2 — Kleinanzeigen (Zuordnen / a or b)
10 short ads. 5 situations. For each situation, show 2 ads (a/b). 
The learner marks which ad fits the situation.
Ads from: Wohnungen, Jobs, Autos, Möbel, Bücher, Kurse, Reisen, Freizeit.
"""
    if teil == '3' or teil == 'all':
        for k in kb_for_cluster(kbs, 'lesen_3'):
            base += f"  {k['id']}: {k['kann'][:200]}\n"
        base += """
## Lesen Teil 3 — Schilder und Aushänge (Richtig/Falsch)
5 very short signs/notices. One statement each.
Signs: "Heute geschlossen", "Aufzug außer Betrieb", "Parken verboten", 
"Kein Eintritt", "Bitte Tür schließen", "Rauchen verboten", etc.
"""
    base += "\nGenerate original exam-style questions. Provide answer key at the end."
    return base

def prompt_horen(kbs, grammatik, wf, red, teil='all'):
    return f"""You are a telc Deutsch A1 exam author. Generate Hören (listening) questions.

## Grammar & Vocabulary
{grammar_summary(grammatik)}
{vocab_summary(wf, max_items=8)}

## Hören Teil 1 — Kurze Gespräche (a/b/c, 6 dialogs)
Short everyday conversations. Each has one multiple-choice question with 3 options.
Topics: asking for time, price, directions, introductions, wellbeing.

## Hören Teil 2 — Durchsagen (Richtig/Falsch, 4 announcements)  
Public announcements at Bahnhof, Flughafen, Supermarkt, Kaufhaus.
Test: extracting numbers, times, places, names from spoken announcements.
Key: announcements are heard ONCE.

## Hören Teil 3 — Telefonansagen (a/b/c, 5 messages)
Answering machine messages. Each has one multiple-choice question.
"Wer ruft an? Warum? Was soll der Hörer tun?"

For each item, provide:
1. The spoken text (German, A1 level, 20-40 words for Teil 1, 30-60 for Teil 3)
2. The question
3. Three answer options
4. Correct answer

Target KBs: K063 (hear numbers/price/time), K064 (hear location/time), 
K074 (public call), K076 (spoken instruction).
Generate now."""

def prompt_sprechen(kbs, grammatik, wf, red, teil='all'):
    return f"""You are a telc Deutsch A1 speaking examiner. Practice Sprechen with me.

## Grammar & Vocabulary
{grammar_summary(grammatik)}

## Sprechen Teil 1 — Sich vorstellen (max 3 points)
I introduce myself: Name, Alter, Herkunft, Wohnort, Beruf, Hobby.
Then buchstabieren (spell my name) and say a number (Telefonnummer).
You give me 4 Stichwörter as prompts. I speak 60 seconds. You score me.

## Sprechen Teil 2 — Fragen stellen und beantworten (max 6 points)
Topics: Einkaufen, Essen und Trinken, Freizeit/Wochenende.
I draw a Handlungskarte with one word. I ask my partner a question.
My partner answers. Then switch. Each person asks 2 questions, answers 2.

Give me 8 Handlungskarten now with model questions and answers.

## Sprechen Teil 3 — Bitten formulieren (max 6 points)
I draw a card with a Bild (picture/word). I make a polite request (Bitte).
My partner responds. "Ein Glas Wasser, bitte." → "Ja, natürlich."

Give me 12 Bildkarten with model Bitten and Antworten."""

def prompt_schreiben(kbs, grammatik, wf, red, teil='all'):
    return f"""You are a telc Deutsch A1 exam corrector. Generate Schreiben (writing) tasks.

## Grammar & Vocabulary  
{grammar_summary(grammatik)}

## Schreiben Teil 1 — Formular ausfüllen (max 5 points)
A situation description + a form with 5 empty fields. I fill in the blanks.
Situations: Hotelanmeldung, Kursanmeldung, Paketkarte, Gewinnspiel.

## Schreiben Teil 2 — Kurzmitteilung (max 10 points)
Write ~30 words. 3 Inhaltspunkte. Text type: E-Mail, Notiz, Brief.
Score: 3 points per Inhaltspunkt + 1 for Anrede/Gruß.

Situation types:
- Entschuldigung (can't come → why, apologize)
- Einladung (invite → when/where, what to bring)
- Information (ask tourist office → why, what info, hotel?)
- Danke (thank → what liked, how used, invite back)

Give me 4 Schreiben Teil 2 tasks now."""

def prompt_kb(kbs, grammatik, wf, red, kb_id):
    kb = kbs.get(kb_id.upper())
    if not kb:
        return f"KB {kb_id} not found."
    red_data = red.get('manual_overrides', {}).get(kb_id.upper(), {})
    
    return f"""You are a telc Deutsch A1 tutor. Help me master this one Kannbeschreibung.

## KB {kb['id']}: {kb['kann']}
Category: {kb['category']}
Level: {kb.get('level','')}

## What this means (simplified)
The learner should be able to: {kb['kann'][:300]}

## Carrier & Operation
{red_data.get('carrier','(not specified)')}
Channel: {red_data.get('channel','')} 
Operation: {red_data.get('operation','')}
Output expected: {red_data.get('output','')}

## Examples from the KB data
{chr(10).join(f'- {ex.get("text","")}' for ex in red_data.get('examples',[]) if isinstance(ex,dict)) or chr(10).join(f'- {ex}' for ex in red_data.get('examples',[]))}

## Near/related KBs
near_kbs: {red_data.get('near_kbs',[])} (practice these alongside)

## A1 constraints
Grammar: {grammar_summary(grammatik)[:500]}

## Your task
Generate 8 short practice questions in the telc A1 exam format that test EXACTLY this KB.
Make distractors that test the learner's ability to distinguish this KB from similar ones.
Include answers."""

# Main
if __name__ == '__main__':
    kbs, grammatik, wf, red = load_data()
    module = sys.argv[1] if len(sys.argv) > 1 else 'lesen'
    teil = sys.argv[2] if len(sys.argv) > 2 else 'all'
    
    if module == 'kb':
        print(prompt_kb(kbs, grammatik, wf, red, teil))
    elif module == 'lesen':
        print(prompt_lesen(kbs, grammatik, wf, red, teil))
    elif module == 'horen':
        print(prompt_horen(kbs, grammatik, wf, red, teil))
    elif module == 'sprechen':
        print(prompt_sprechen(kbs, grammatik, wf, red, teil))
    elif module == 'schreiben':
        print(prompt_schreiben(kbs, grammatik, wf, red, teil))
    else:
        print(f"Unknown module: {module}. Options: lesen, horen, sprechen, schreiben, kb")
