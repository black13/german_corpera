#!/bin/bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$BASE_DIR"

# Kill any running processes
pkill -f "python3.*runner.py" 2>/dev/null || true

python3 - <<'PY'
import json
from pathlib import Path

base = Path.cwd()
config = json.loads((base / "config/runtime.json").read_text(encoding="utf-8"))
students = config["classroom"]["students"]

for sid in students:
    (base / "state/teacher" / f"memory_{sid}.json").write_text(
        json.dumps({}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (base / "state/students" / f"{sid}_learned.json").write_text(
        json.dumps(
            {
                "student": sid,
                "day": 0,
                "vocabulary_acquired": [],
                "grammar_acquired": [],
                "kannbeschreibungen_attempted": {},
                "persistent_errors": [],
                "emotional_state": "nervous, first day",
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

(base / "state/grader/progress.json").write_text(
    json.dumps({sid: [] for sid in students}, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)
(base / "state/course/course_state.json").write_text(
    json.dumps(
        {
            "current_day": {sid: 0 for sid in students},
            "areas_covered": {sid: [] for sid in students},
        },
        indent=2,
        ensure_ascii=False,
    )
    + "\n",
    encoding="utf-8",
)
PY

# Clear generated artifacts
rm -f output/*.json
rm -f plans/generated/*.json

echo "All state cleared with initial schemas. Ready for fresh run."
