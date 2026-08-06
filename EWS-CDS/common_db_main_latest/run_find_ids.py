import re
import os
import sys

with open('deploy.sh', encoding='utf-8') as f:
    content = f.read()
    match = re.search(r'CLOUD_SQL_PASS=([^\s]+)', content)
    if match:
        os.environ['CLOUD_SQL_PASS'] = match.group(1).strip("'\"")
    else:
        print("Could not find CLOUD_SQL_PASS in deploy.sh")
        sys.exit(1)

sys.path.append('sabari_project')
sys.path.append('sabari_project/backend')
with open('sabari_project/find_mimic_ids.py') as f:
    exec(f.read())
