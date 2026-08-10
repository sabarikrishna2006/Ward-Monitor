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

def check():
    db = SessionLocal()
    try:
        data = get_ward_data(ward="All", db=db)
        patients = data["patients"]
        print(f"Total patients returned: {len(patients)}")

        non_vacuous = [p for p in patients
                       if isinstance(p["news2"], (int, float)) and p["news2"] < 7
                       and p.get("escalationTier") == "CRITICAL RISK"]
        high_risk_nv = [p for p in patients
                         if isinstance(p["news2"], (int, float)) and p["news2"] < 7
                         and p.get("escalationTier") == "HIGH RISK"]

        print(f"\nNEWS2<7 AND escalationTier==CRITICAL RISK (true non-vacuous alarm): {len(non_vacuous)}")
        for p in non_vacuous:
            print(f"  hadm_id={p['id']} name={p.get('name')} news2={p['news2']} mlRisk={p.get('mlRisk')}% tier={p.get('escalationTier')} window={p.get('escalationWindow')} model={p.get('escalationModel')}")

        print(f"\nNEWS2<7 AND escalationTier==HIGH RISK (softer tier, tau_low only): {len(high_risk_nv)}")
        for p in high_risk_nv:
            print(f"  hadm_id={p['id']} name={p.get('name')} news2={p['news2']} mlRisk={p.get('mlRisk')}% tier={p.get('escalationTier')} model={p.get('escalationModel')}")

        print(f"\n--- All patients (news2, tier, mlRisk, model) for context ---")
        for p in sorted(patients, key=lambda x: x.get('mlRisk') or -1, reverse=True)[:20]:
            print(f"  hadm_id={p['id']} news2={p['news2']} tier={p.get('escalationTier')} mlRisk={p.get('mlRisk')}% model={p.get('escalationModel')}")
    finally:
        db.close()

if __name__ == "__main__":
    check()
