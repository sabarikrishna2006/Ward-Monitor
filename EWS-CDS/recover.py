import json
import re
import io

transcript_path = r"C:\Users\sabari krishna\.gemini\antigravity-ide\brain\1641149a-a2ea-41f7-b3cf-281c0113ccf1\.system_generated\logs\transcript.jsonl"

file_lines = []

with io.open(transcript_path, 'r', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line)
        if data.get('type') == 'VIEW_FILE' and 'foqal_careos_unified_erd_final.html' in data.get('content', ''):
            if data.get('step_index') in [133, 137]:
                content = data['content']
                lines = content.split('\n')
                start_idx = 0
                for i, l in enumerate(lines):
                    if "leading space." in l:
                        start_idx = i + 1
                        break
                
                for l in lines[start_idx:]:
                    if l.startswith("The above content does NOT") or l.startswith("The following code has been"):
                        break
                    match = re.match(r"^\d+:\s?(.*)$", l)
                    if match:
                        file_lines.append(match.group(1))
                    elif l.strip() == "" and len(file_lines) > 0:
                        file_lines.append("")

with io.open("e:/IP_EarlyWarning/EWS-CDS/foqal_careos_unified_erd_final_recovered.html", "w", encoding="utf-8") as out:
    out.write("\n".join(file_lines))

print("Recovered to foqal_careos_unified_erd_final_recovered.html")
