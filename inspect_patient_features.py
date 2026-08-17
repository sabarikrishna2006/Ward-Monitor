import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "sabari_project", "backend"))

_env_path = os.path.join(os.path.dirname(__file__), ".env.secrets")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line.startswith("export "):
                _line = _line[len("export "):]
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip('"'))

os.environ.setdefault(
    "GOOGLE_APPLICATION_CREDENTIALS",
    os.path.join(os.path.dirname(__file__), "foqal-healthcare-project-google.json")
)

from database import SessionLocal
from main import get_ward_data
import escalation_model
from models import Patient

TARGET_IDS = [28192221, 28217808, 28278955, 25201843, 20026625, 29736161]

def check():
    db = SessionLocal()
    try:
        data = get_ward_data(ward="All", db=db)
        by_id = {int(p["id"]): p for p in data["patients"]}
        for hid in TARGET_IDS:
            p = by_id.get(hid)
            if not p:
                print(f"{hid}: not found in ward data")
                continue
            print(f"\n=== hadm_id={hid} name={p.get('name')} news2={p['news2']} mlRisk={p.get('mlRisk')}% tier={p.get('escalationTier')} ===")
            print(f"  latest vitals: hr={p.get('hr')} rr={p.get('rr')} spo2={p.get('spo2')} bp={p.get('bp')} temp={p.get('temp')} avpu={p.get('avpu')} o2={p.get('o2')}")
            print(f"  newsFactors: {p.get('newsFactors')}")
            print(f"  SHAP drivers:")
            for d in (p.get('mlContributors') or []):
                print(f"    {d}")
    finally:
        db.close()

if __name__ == "__main__":
    check()
