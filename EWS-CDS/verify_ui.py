"""Foqal CareOS — UI verification via Playwright.
Seeds sessionStorage with add_init_script (runs BEFORE page scripts) so the SPA boots."""
import os, sys, json, time
from playwright.sync_api import sync_playwright

OUT = r"E:\IP_EarlyWarning\EWS-CDS\screenshots"
os.makedirs(OUT, exist_ok=True)
BASE = "http://localhost:8000"

ROLES = {
    "nurse":    {"role": "nurse",    "name": "Nurse Rekha Devi",   "roleLabel": "Bedside Nurse", "shift": "Day", "ward": "Ward 4B/4C", "empId": "N001"},
    "charge":   {"role": "charge",   "name": "Sister Leena Kurup", "roleLabel": "Head Nurse",    "shift": "Day", "ward": "Ward 4B/4C", "empId": "C001"},
    "gw_nurse": {"role": "gw_nurse", "name": "Nurse Anita Rao",     "roleLabel": "GW Nurse",      "shift": "Day", "ward": "General Ward", "empId": "G001"},
}
PASS = FAIL = 0
def ok(c, m):
    global PASS, FAIL
    PASS, FAIL = PASS + (1 if c else 0), FAIL + (0 if c else 1)
    print(("  OK  " if c else "  FAIL ") + m)

def new_ctx(browser, role):
    ctx = browser.new_context(viewport={"width": 1340, "height": 900})
    u = json.dumps(ROLES[role])
    ctx.add_init_script(f"sessionStorage.setItem('foqal_user', {json.dumps(u)}); sessionStorage.setItem('foqal_token','local-test');")
    return ctx

def run(role, steps):
    print(f"\n=== {role} ===")
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = new_ctx(b, role)
        page = ctx.new_page()
        page.goto(BASE)
        try:
            page.wait_for_selector("#app-shell", state="visible", timeout=8000)
        except Exception as e:
            print(f"  app-shell not visible: {e}")
        page.wait_for_timeout(2500)
        steps(page)
        b.close()

def shot(page, n):
    page.screenshot(path=os.path.join(OUT, n + ".png"), full_page=True)
    print(f"  [img] {n}.png")

def nurse_steps(page):
    shot(page, "v1_nurse_dashboard")
    c = page.content()
    ok("EWS Reason" in c, "EWS Reason column header")
    ok("Diagnosis" in c, "Diagnosis column header")
    ok("DCM" in c, "diagnosis values present")
    ok("Due in" in c or "Overdue" in c, "cadence due/overdue labels")
    ok("AI" in c and "demo" in c, "demo AI risk pill present")
    # open first patient
    try:
        page.wait_for_selector("table tbody tr", timeout=4000)
        page.locator("table tbody tr").first.click()
        page.wait_for_timeout(1500)
        shot(page, "v2_nurse_n1b_vitals")
        c = page.content()
        ok("dx-banner" in c, "diagnosis banner rendered")
        ok("NEWS2 Trend" in c, "NEWS2 trend chart present")
        ok("Heart-Failure Watch" in c, "DCM params block present")
        ok("Fluid Balance" in c and "Urine Output" in c, "fluid/urine params")
        ok("ML Insights" in c, "ML Insights tab present")
        ok("CCU&rarr;GW Transfer" in c or "Transfer" in c, "transfer button present")
        # ML tab
        page.locator("button.tab-btn", has_text="ML Insights").first.click()
        page.wait_for_timeout(800)
        shot(page, "v3_nurse_ml_tab")
        c = page.content()
        ok("Deterioration Risk" in c, "ML risk panel")
        ok("in training" in c, "demo/in-training label on ML")
        ok("contributing signals" in c.lower() or "Top contributing" in c, "ML contributor bars")
    except Exception as e:
        print(f"  n1b step error: {e}")

def charge_steps(page):
    shot(page, "v4_charge_n5")
    c = page.content()
    ok("Escalation Queue" in c, "charge escalation queue")

if __name__ == "__main__":
    run("nurse", nurse_steps)
    run("charge", charge_steps)
    print(f"\nResult: {PASS} passed, {FAIL} failed")
