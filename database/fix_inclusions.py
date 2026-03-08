import json
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Pattern matches: "Heading 08.01 — Coconuts..." or "Heading 08.01 - Coconuts..."
pattern = re.compile(r'^Heading\s+(\d{2}\.\d{2})\s*[—\-\–:]+\s*(.*)', re.IGNORECASE)

count_modified = 0

for filename in os.listdir(BASE_DIR):
    if filename.startswith("chapter_") and filename.endswith("_rules.json"):
        filepath = os.path.join(BASE_DIR, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        modified = False
        new_inclusions = []
        for inc in data.get("inclusions", []):
            if isinstance(inc, str):
                match = pattern.match(inc)
                if match:
                    heading = match.group(1)
                    desc = match.group(2)
                    new_inclusions.append({
                        "heading": heading,
                        "description": desc
                    })
                    modified = True
                else:
                    new_inclusions.append(inc)
            elif isinstance(inc, dict):
                # Ensure keys are correct
                new_inclusions.append(inc)
            else:
                new_inclusions.append(inc)
                
        if modified:
            data["inclusions"] = new_inclusions
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            count_modified += 1
            
print(f"Modified {count_modified} files to structure inclusions.")
