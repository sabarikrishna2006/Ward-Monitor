import sys
import os
sys.path.append(os.path.join(os.getcwd(), 'sabari_project/backend'))
from database import SessionLocal
import main

db = SessionLocal()
try:
    res = main.get_patient_detail(10001, db)
    print("SUCCESS!")
    print(res.get("ml_tier"), res.get("ml_model_type"))
except Exception as e:
    print("CRASHED!")
    import traceback
    traceback.print_exc()
