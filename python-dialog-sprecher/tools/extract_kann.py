"""One-time script: extract all A1 Kannbeschreibungen from OCR into structured JSON."""
import json, re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

with open(BASE / "reference" / "ocr_text_only.txt") as f:
    lines = f.readlines()

# Section 8.1 starts at line 2887 (0-indexed: 2886), ends around 3236
section = lines[2886:3236]

# State machine to parse
categories = []
current_cat = None
current_sub = None  # "global" or "detailed"
current_group = None  # the header Kann for a cluster of examples
group_counter = 0

for line in section:
    line = line.strip()
    if not line:
        continue

    # Category headers
    if "Globale Kannbeschreibungen:" in line or "Globale Kannbeschreibungen:" in line:
        cat_name = line.split(":")[-1].strip()
        # Check if this is a new category or sub-part
        if current_cat is None or cat_name != current_cat["category"]:
            current_cat = {"category": cat_name, "global": [], "detailed": []}
            categories.append(current_cat)
        current_sub = "global"
        continue

    if "Detaillierte Kannbeschreibungen mit Beispielen:" in line:
        cat_name = line.split(":")[-1].strip()
        if current_cat is None or cat_name != current_cat["category"]:
            current_cat = {"category": cat_name, "global": [], "detailed": []}
            categories.append(current_cat)
        current_sub = "detailed"
        current_group = None
        continue

    # Skip section headers
    if line.startswith("8.1") or line == "A1 Kannbeschreibungen" or re.match(r"^A1 Kannbeschreibungen\b", line):
        continue
    if line.startswith("1. Globale") or line.startswith("2. Kann"):
        # Production section has numbered headers, treat "2. Kann..." as a Kann
        if line.startswith("2. Kann"):
            line = line[3:]  # strip "2. "
        else:
            continue
    if line in ("Rezeption schriftlich", "Interaktion schriftlich", "Sprachmittlung mündlich",
                "aus dem Deutschen", "aus einer anderen Sprache",
                "A1 Kannbeschreibungen Interaktion mündlich"):
        if "schriftlich" in line and "Rezeption" in line:
            # This is a category marker but the global header follows
            pass
        if "schriftlich" in line and "Interaktion" in line:
            pass
        continue

    # Lines starting with "Kann" are Kannbeschreibungen
    if line.startswith("Kann") and current_cat:
        group_counter += 1
        entry = {
            "id": f"K{group_counter:03d}",
            "kann": line,
            "type": current_sub or "detailed"
        }

        if current_sub == "global":
            current_cat["global"].append(entry)
        else:
            # In detailed sections, longer/more abstract statements are group headers,
            # shorter situational ones are examples
            # Heuristic: if it doesn't reference a specific situation, it's a header
            is_example = any(marker in line for marker in [
                "z. B.", "Kollegin", "Kursgruppe", "Arbeitsplatz", "Freund",
                "Restaurant", "Hotel", "Party", "Supermarkt", "Geschäft",
                "Fernsehen", "Radio", "Zeitung", "Computer", "CD",
                "Kaufhaus", "Apotheke", "Arzt", "Amt", "Büro",
                "Chef", "Kolleg", "Kurs", "Prüfung", "Flughafen",
                "Studentenwohnheim", "Wohngemeinschaft", "Firma",
                "Internetcafé", "Sprachlernprogramm", "Betrieb",
                "Fußball", "Snowboard", "Fahrplan", "Kinoprogramm",
                "Postkarte", "E-Mail", "Besprechung", "Cafeteria",
                "Rezeption", "Schalter", "Polizist", "Tourist",
                "Hausbewohner", "Sekretariat", "Medikament",
                "Putin", "Schalke", "Bauer"
            ])

            if is_example:
                entry["type"] = "example"
            else:
                entry["type"] = "detailed"
                current_group = entry

            current_cat["detailed"].append(entry)

# Flatten into final structure
all_kann = []
for cat in categories:
    for k in cat["global"]:
        k["category"] = cat["category"]
        k["level"] = "global"
        all_kann.append(k)
    for k in cat["detailed"]:
        k["category"] = cat["category"]
        k["level"] = k.pop("type")
        all_kann.append(k)

# Build the output
output = {
    "source": "Profile Deutsch A1, Section 8.1",
    "total_count": len(all_kann),
    "categories": list(set(c["category"] for c in categories)),
    "kannbeschreibungen": all_kann
}

with open(BASE / "canon" / "kannbeschreibungen_full.json", "w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"Extracted {len(all_kann)} Kannbeschreibungen across {len(categories)} categories")

# Summary
for cat in categories:
    print(f"  {cat['category']}: {len(cat['global'])} global + {len(cat['detailed'])} detailed")
