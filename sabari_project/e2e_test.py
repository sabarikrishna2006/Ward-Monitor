import httpx
import time
import sys

data_server = "http://localhost:6020"
ward_server = "http://localhost:6030"
ashmit_api = "http://localhost:6010"

hadm_id = 20000094

def run_test():
    print(f"=== Foqal CareOS E2E Test (Billing -> Discharge) for {hadm_id} ===")
    
    # 1. Billing Admission
    print(f"\n[1] Admitting patient from Billing (Triggering ETL)...")
    start = time.time()
    resp = httpx.post(f"{data_server}/api/patient/{hadm_id}/prefetch-all", timeout=120)
    elapsed = time.time() - start
    print(f"Response ({elapsed:.2f}s): {resp.status_code}")
    data = resp.json()
    print(f"Result: {data}")
    if data.get("status") != "fetched":
        print("FAILED: Patient was not marked 'fetched' synchronously!")
        sys.exit(1)
        
    # 2. Verify in Ward Dashboard
    print(f"\n[2] Checking Ward Dashboard...")
    resp = httpx.get(f"{ward_server}/api/ward-data?ward=All")
    ward_data = resp.json()
    
    patient_found = None
    for p in ward_data.get("patients", []):
        if p["id"] == hadm_id:
            patient_found = p
            break
            
    if not patient_found:
        print("FAILED: Patient not found in Ward Dashboard!")
        sys.exit(1)
        
    print(f"Patient Found in Ward: Name={patient_found['name']}, db_status={patient_found['db_status']}, EWS={patient_found['ews']}")
    if patient_found["db_status"] != "active":
        print(f"FAILED: Expected db_status 'active', got {patient_found['db_status']}")
        sys.exit(1)

    # 3. Initiate Discharge
    print(f"\n[3] Ward Nurse Initiating Discharge...")
    resp = httpx.post(f"{ward_server}/api/patients/{hadm_id}/discharge-initiate")
    print(f"Discharge Initiate Response: {resp.status_code} {resp.text}")

    # Verify status changed
    resp = httpx.get(f"{ward_server}/api/ward-data?ward=All")
    for p in resp.json().get("patients", []):
        if p["id"] == hadm_id:
            print(f"New db_status: {p['db_status']}")
            if p["db_status"] != "discharge_initiated":
                print("FAILED: db_status did not update to 'discharge_initiated'")
                sys.exit(1)
            break
            
    # 4. Generate Discharge Summary (LLM)
    print(f"\n[4] Resident generating Discharge Summary (LLM)...")
    start = time.time()
    resp = httpx.post(f"{ashmit_api}/api/patients/{hadm_id}/discharge-summary", timeout=180)
    elapsed = time.time() - start
    print(f"Summary generated in {elapsed:.2f}s (Status: {resp.status_code})")
    
    # 5. Signoff
    print(f"\n[5] Resident signing off discharge...")
    resp = httpx.post(f"{ashmit_api}/api/patients/{hadm_id}/discharge-signoff", json={"summary": "Automated Test Signed Off Summary"})
    print(f"Signoff Response: {resp.status_code} {resp.text}")
    
    print("\n=== Test Completed Successfully! ===")

if __name__ == "__main__":
    run_test()
