# german_corpera

## Grammar REPL (spaCy de_core_news_lg)
This repo now ships an interactive grammar REPL powered by spaCy's large German model.

### Prerequisites
1. Create the environment and activate it:
   ```bash
   conda env create -f environment.yml
   conda activate german-corpera
   ```
2. Download the spaCy German model (stored outside the repo):
   ```bash
   python3 -m spacy download de_core_news_lg
   ```

### Usage
```bash
python3 grammar_repl.py            # start the interactive prompt
python3 grammar_repl.py --text "Das ist nur ein Test."
python3 grammar_repl.py --file path/to/input.txt --no-repl
```

Inside the REPL, type German sentences to inspect lemmas, POS tags, morphology, and dependencies. Use `:help` for available commands, `:rules` to list grammar topics, and `:rule <name>` (e.g., `:rule prep-an`) to read the explanation behind a detected Kasus choice. After running an analysis you can:
- `:json path/to/file.json` — export the structured analysis for reuse.
- `:prompt [custom instructions]` — dump a ready-to-use LLM prompt seeded with the latest analysis.

### Deklination quick-start
- New rule keys: `declension-overview`, `declension-articles`, `adjective-endings` (see them via `:rules` or `:rule <key>`).
- The generated prompt now nudges LLMs to focus on Kasus choice and declension endings; you can append your own focus with `:prompt "Give A2 declension drills."`.
- Use Wechselpräposition examples to surface Dativ/Akkusativ contrasts quickly (e.g., `Ich hänge das Bild an die Wand.` / `Das Bild hängt an der Wand.`).

## Codex-Style Prompt REPL
Use `codex_repl.py` to keep an evolving conversation with an OpenAI coding model (default `gpt-4o-mini`).

### Requirements
- Export the key for your chosen provider:
  - OpenAI: `export OPENAI_API_KEY=...`
  - DeepSeek: `export DEEPSEEK_API_KEY=...`
- Keys can also live in a local `.env` (`OPENAI_API_KEY=...` / `DEEPSEEK_API_KEY=...`) or be pasted once when prompted; `.env` is git-ignored.
- Install dependencies via `conda env create -f environment.yml` (or `pip install openai requests` inside an existing env).

### Usage
```bash
python3 codex_repl.py                               # OpenAI (default), gpt-4o-mini
python3 codex_repl.py --model gpt-4.1-mini --system "You are a Python tutor."
python3 codex_repl.py --provider deepseek --model deepseek-chat
```

Commands include `:help`, `:history`, `:reset`, `:save path.txt`, `:system <text>`, and `:quit`. Each user turn is appended to the ongoing context so transformers receive all prior prompts and answers, regardless of provider.
Line-editing and arrow-key history rely on `readline`; session history is stored at `~/.codex_repl_history`.

## spaCy → LLM Prompt Bridge
Use `spacy_prompt.py` when you want to analyze a specific sentence/text block with spaCy, generate a structured prompt, and (optionally) call an LLM in one shot.

```bash
python3 spacy_prompt.py --text "An der Wand hängt ein Bild." --no-llm
python3 spacy_prompt.py --file sentences.txt --instructions "Design two drill ideas." --provider deepseek --llm-model deepseek-chat
```

Flags such as `--json-out analysis.json` or `--prompt-out seed.txt` persist intermediate artifacts. Add `--quiet` to suppress the detailed analysis printout, or `--system "You are a German tutor"` before the LLM call.

## Batch Idea Dumps
`batch_idea_dump.py` walks through a text file (one sentence per line), runs the spaCy analysis for each entry, generates prompts, and optionally calls an LLM.

```bash
python3 batch_idea_dump.py \
  --input german_sentences.txt \
  --output idea_dump.jsonl \
  --instructions "Propose one cloze deletion and one discussion question." \
  --provider deepseek --llm-model deepseek-chat --skip-empty
```

Each line in `idea_dump.jsonl` contains the source sentence, full analysis payload, generated prompt, and LLM response (unless `--no-llm` is supplied). Use `--limit N` for spot checks before running on the entire corpus.

## Hybrid German rulebook + worksheet prompts
`hybrid_rules.py` holds a small catalogue of “Hybrid German” rules plus ready-made worksheet prompts.

```bash
python3 hybrid_rules.py --list
python3 hybrid_rules.py --rule cases-declension
python3 hybrid_rules.py --rule cases-declension --worksheet  # prints a worksheet prompt you can feed to an LLM
python3 hybrid_rules.py --rule cases-declension --worksheet --call-llm \
  --provider deepseek --llm-model deepseek-chat --temperature 0.2 --max-tokens 800
```

Rules cover word order, compact cases/declension, adjective endings, verb endings, negation placement, prepositions, and phon/orthography tweaks. Use the worksheet prompt output to generate drills or explanations with your chosen LLM provider.

## Rule Roadmap
See `rule_index.md` for a coverage map (what’s in `hybrid_rules.py`, what’s missing). Gaps to fill next include: noun gender/plural/n-Dekl, detailed adjective declension types, pronouns (es/das/indefinites/wo-da), temporal preps/adverbs, verb families (reflexive/passive/trennbar/untrennbar/Konjunktiv II), and syntax (HS/NS, Konnektoren, Infinitiv/Relativ/Temporalsätze).

## OCR Helpers
- `ocr_heath_page1.py` / `ocr_bruel_batch.py` — Kraken OCR helpers (Fraktur) for the Heath dictionary PNGs.
- `cleanup_ocr.py` — normalize OCR text and flag unknown words (use a wordlist; outputs `_clean.txt` and `_unknown.txt`).
