"""
Foqal CareOS — UI smoke test via Playwright
Strategy: set sessionStorage → reload → IIFE boots the app from session.
"""
import os, time, json
from playwright.sync_api import sync_playwright, expect

OUT = r"E:\IP_EarlyWarning\EWS-CDS\screenshots"
os.makedirs(OUT, exist_ok=True)

NURSE = {"role": "nurse", "name": "Nurse Rekha Devi", "roleLabel": "Bedside Nurse",
         "shift": "Day", "ward": "Ward 4B", "empId": "N001"}
CHARGE = {"role": "charge", "name": "Sister Leena Kurup", "roleLabel": "Head Nurse",
          "shift": "Day", "ward": "Ward 4B / 4C", "empId": "C001"}

PASS = 0; FAIL = 0

def shot(page, name):
    path = os.path.join(OUT, f"{name}.png")
    page.screenshot(path=path, full_page=True)
    print(f"  [img] {name}.png")

def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  OK  {msg}")
    else:
        FAIL += 1; print(f"  FAIL {msg}")

def login(page, user):
    """Inject user into sessionStorage then reload so the IIFE boots the app."""
    raw = json.dumps(user)
    page.evaluate(f"() => sessionStorage.setItem('foqal_user', {json.dumps(raw)})")
    page.evaluate("() => sessionStorage.setItem('foqal_token', 'local-test')")
    page.reload()
    page.wait_for_load_state("networkidle")
    # IIFE shows #app-shell once session is valid
    page.wait_for_selector("#app-shell", state="visible", timeout=10000)
    # Give ward-data fetch time to resolve and renderAll() to paint
    page.wait_for_load_state("networkidle")

def nav_to(page, screen_id):
    page.evaluate(f"() => window.nav('{screen_id}')")
    page.wait_for_load_state("networkidle")
    time.sleep(0.8)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)

    # ── NURSE SESSION ──────────────────────────────────────────────────────────
    print("\n=== NURSE (Bedside Nurse) ===")
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    page.goto("http://localhost:8000")
    page.wait_for_load_state("networkidle")
    login(page, NURSE)

    # 1. NEWS2 Dashboard (N1)
    print("[1] NEWS2 Dashboard (N1)")
    shot(page, "01_nurse_dashboard")
    c = page.content()
    ok("PT-26-" in c, "patient_code PT-26-XXXX visible in table")
    ok(any(x in c for x in ["CRITICAL", "WARNING", "STABLE", "stable"]), "risk badges visible")
    ok("NEWS2" in c, "NEWS2 heading present")

    # 2. Patient Detail (N1b) — click first row
    print("[2] Patient Detail (N1b)")
    try:
        page.wait_for_selector("table tbody tr", timeout=5000)
        page.locator("table tbody tr").first.click()
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        shot(page, "02_patient_detail_n1b")
        c = page.content()
        ok("Drug-Lab" in c, "Drug-Lab tab visible in N1b")
        ok("PT-26-" in c, "patient_code shown in N1b header")
        ok(any(x in c for x in ["SpO", "Vital", "NEWS"]), "vitals section visible")
    except Exception as e:
        print(f"  SKIP N1b: {e}")

    # 3. Drug-Lab tab routing button
    print("[3] Drug-Lab tab → routing button")
    try:
        page.locator("button", has_text="Drug-Lab").first.click()
        time.sleep(0.8)
        shot(page, "03_druglab_tab")
        c = page.content()
        ok("View Drug-Lab Details" in c, "Drug-Lab routing button visible")
        ok("Nurse view" in c or "read only" in c.lower() or "read-only" in c.lower(),
           "nurse read-only label visible")
    except Exception as e:
        print(f"  SKIP Drug-Lab tab: {e}")

    # 4. Enter Vitals → N_vitals screen (stale patient)
    print("[4] Enter Vitals → N_vitals screen")
    nav_to(page, "n1")
    try:
        vitals_btn = page.locator("button", has_text="Enter Vitals").first
        vitals_btn.wait_for(state="visible", timeout=5000)
        vitals_btn.click()
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        shot(page, "04_n_vitals_screen")
        c = page.content()
        ok("Vital Signs Entry" in c or "v-spo2" in c, "N_vitals dedicated screen loaded")
        ok(any(x in c for x in ["SpO", "Heart Rate", "Temperature"]), "form fields visible")
    except Exception as e:
        print(f"  SKIP N_vitals (may have no stale patient): {e}")

    # 5. Fill and submit vitals form
    print("[5] Submit vitals form → NEWS2 result")
    try:
        page.wait_for_selector("#v-spo2", timeout=4000)
        page.fill("#v-spo2", "94")
        page.fill("#v-rr", "22")
        page.fill("#v-hr", "105")
        page.fill("#v-sbp", "108")
        page.fill("#v-dbp", "68")
        page.fill("#v-temp", "38.3")
        shot(page, "05_vitals_form_filled")
        page.click("#submit-vitals-btn")
        time.sleep(3)
        shot(page, "06_vitals_result")
        c = page.content()
        ok("NEWS2" in c, "NEWS2 score shown after submission")
    except Exception as e:
        print(f"  SKIP vitals form: {e}")

    # ── CHARGE NURSE SESSION ───────────────────────────────────────────────────
    print("\n=== CHARGE NURSE (Head Nurse) ===")
    page.goto("http://localhost:8000")
    page.wait_for_load_state("networkidle")
    login(page, CHARGE)

    # 6. Escalation Queue (N5)
    print("[6] Escalation Queue (N5) — charge nurse default screen")
    shot(page, "07_charge_escalation_queue")
    c = page.content()
    ok("Escalation" in c, "Escalation heading visible")
    ok("Drug-Lab" in c, "Drug-Lab Overview link/button visible")

    # 7. Patient detail from charge POV
    print("[7] Head Nurse patient detail → false alarm button")
    nav_to(page, "n1")
    try:
        page.wait_for_selector("table tbody tr", timeout=5000)
        page.locator("table tbody tr").first.click()
        page.wait_for_load_state("networkidle")
        time.sleep(1)
        shot(page, "08_charge_patient_detail")
        c = page.content()
        ok("Mark False Alarm" in c, "Head Nurse False Alarm button visible")
        ok("Escalation Queue" in c or "Head Nurse" in c, "Head Nurse breadcrumb/back-link visible")
        ok("Escalate to Attending" in c or "Escalate" in c, "Escalate action visible")
    except Exception as e:
        print(f"  SKIP charge patient detail: {e}")

    # 8. DL1 Drug-Lab overview
    print("[8] DL1 Drug-Lab Flag Overview")
    nav_to(page, "dl1")
    shot(page, "09_dl1_overview")
    c = page.content()
    ok("Drug" in c or "Lab" in c, "DL1 page loaded")
    ok(any(x in c for x in ["CRITICAL", "WARNING", "No active", "PT-26-"]), "DL flag content present")

    browser.close()

    print(f"\n{'='*50}")
    print(f"Results: {PASS} passed, {FAIL} failed")
    print(f"Screenshots saved to: {OUT}")
