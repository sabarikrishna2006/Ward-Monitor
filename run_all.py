import subprocess
import sys
import time

print("Starting FULL MAPPING Pipeline with MedCPT...")

STAGES = [
    ("1. Mapping Procedures", "map_procedures.py"),
    ("2. Mapping Medicines",  "map_medicines.py"),
    ("3. Mapping Labs",       "map_labs.py"),
]

# Each stage checkpoints its own progress to disk (enrichment cache, embedding
# cache, matching-loop checkpoint), so a crash in one stage should not prevent
# the others from running — retrying that stage later will resume where it
# left off instead of losing already-saved work from a prior stage.
failed = []
for label, script in STAGES:
    print(f"\n--- {label} ---")
    result = subprocess.run([sys.executable, "-u", script])
    if result.returncode != 0:
        print(f"!!! {label} exited with code {result.returncode} — continuing to next stage anyway.")
        failed.append(label)
    time.sleep(2)

if failed:
    print(f"\nDONE WITH ERRORS — these stages failed and may need a re-run: {', '.join(failed)}")
else:
    print("\nALL 3 FILES GENERATED SUCCESSFULLY!")
