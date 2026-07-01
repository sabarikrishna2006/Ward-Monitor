import os
import glob

downloads_dir = r"c:\Users\ASUS\Downloads"
search_pattern = os.path.join(downloads_dir, "*")
files = glob.glob(search_pattern)

print("Matching files in Downloads:")
for f in files:
    name = os.path.basename(f)
    if "indian" in name.lower() or "medicine" in name.lower() or "drug" in name.lower():
        print(f" - {name} ({os.path.getsize(f)} bytes)" if os.path.isfile(f) else f" - [DIR] {name}")
