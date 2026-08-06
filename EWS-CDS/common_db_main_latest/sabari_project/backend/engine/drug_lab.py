"""
Drug-Lab Interaction Rule Engine
Loads rules from rules/drug_lab_rules.yaml and checks patient data against them.
Rules sourced from: Cardiological Society of India (CSI), CDSCO, RSSDI, ICMR, ESC, FDA.
"""
import os
import yaml

RULES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'rules', 'drug_lab_rules.yaml')

# Map of drug class keywords to their member medications
# Includes both generic names and Indian brand/formulary common names
DRUG_CLASS_MAP = {
    # ACE Inhibitors (very common in Indian HF/hypertension management)
    'ace_inhibitors': [
        'lisinopril', 'enalapril', 'ramipril', 'perindopril', 'captopril',
        'trandolapril', 'quinapril', 'fosinopril'
    ],
    # ARBs — often used interchangeably with ACE inhibitors in India
    'arbs': [
        'losartan', 'telmisartan', 'valsartan', 'olmesartan', 'irbesartan', 'candesartan'
    ],
    # Aldosterone antagonists / K-sparing diuretics
    'k_sparing_diuretics': [
        'spironolactone', 'amiloride', 'eplerenone', 'finerenone'
    ],
    # Biguanides (metformin — widely prescribed in Indian diabetic cardiac patients)
    'metformin': ['metformin', 'glucophage', 'glycomet', 'obimet'],
    # NSAIDs (common OTC in India — ibuprofen, diclofenac widely available)
    'nsaids': [
        'ibuprofen', 'naproxen', 'diclofenac', 'indomethacin', 'ketorolac',
        'aspirin', 'mefenamic', 'aceclofenac', 'etoricoxib', 'celecoxib'
    ],
    # Anticoagulants (warfarin still primary in India due to cost of NOACs)
    'anticoagulants': [
        'warfarin', 'apixaban', 'rivaroxaban', 'dabigatran', 'enoxaparin',
        'heparin', 'acenocoumarol', 'acitrom'  # acenocoumarol/Acitrom widely used in India
    ],
    # Beta-blockers (carvedilol, metoprolol mainstay in Indian HF guidelines)
    'beta_blockers': [
        'metoprolol', 'carvedilol', 'atenolol', 'bisoprolol', 'propranolol',
        'nebivolol', 'labetalol'
    ],
    # Loop diuretics (furosemide/frusemide — note Indian spelling variant)
    'loop_diuretics': [
        'furosemide', 'frusemide', 'torsemide', 'torasemide', 'bumetanide',
        'lasix'  # brand name commonly used in India
    ],
    # Digoxin (still used in India for rate control in AF + HF with reduced EF)
    'digoxin': [
        'digoxin', 'lanoxin', 'digitoxin'
    ],
    # Amiodarone (widely used in India for AF, VT, VF)
    'amiodarone': [
        'amiodarone', 'cordarone', 'tachyra'
    ],
    # Statins (atorvastatin/rosuvastatin dominant in Indian formulary)
    'statins': [
        'atorvastatin', 'rosuvastatin', 'simvastatin', 'pravastatin',
        'lovastatin', 'fluvastatin', 'pitavastatin'
    ],
}


_RULES_CACHE: list | None = None

def load_rules():
    global _RULES_CACHE
    if _RULES_CACHE is None:
        with open(RULES_PATH, 'r', encoding='utf-8') as f:
            _RULES_CACHE = yaml.safe_load(f)['rules']
    return _RULES_CACHE


def _med_matches_class(med_name, med_classes):
    """Check if a medication name matches any of the listed drug classes."""
    med_lower = med_name.lower()
    for cls in med_classes:
        class_meds = DRUG_CLASS_MAP.get(cls, [])
        for cm in class_meds:
            if cm in med_lower:
                return True
    return False


def _evaluate_condition(condition, lab_value):
    """Evaluate a condition string like '> 5.5' against a numeric value."""
    condition = condition.strip()
    if condition.startswith('>='):
        return lab_value >= float(condition[2:])
    elif condition.startswith('<='):
        return lab_value <= float(condition[2:])
    elif condition.startswith('>'):
        return lab_value > float(condition[1:])
    elif condition.startswith('<'):
        return lab_value < float(condition[1:])
    elif condition.startswith('='):
        return lab_value == float(condition[1:])
    return False


def check_patient_against_rules(patient_meds, patient_labs):
    """
    Check a single patient's meds and labs against drug-lab interaction rules.
    Rules sourced from CSI, CDSCO, RSSDI, ICMR, ESC, FDA guidelines.

    patient_meds: list of med_name strings
    patient_labs: dict of {lab_name: value}

    Returns: list of active alert dicts
    """
    rules = load_rules()
    alerts = []

    for rule in rules:
        trigger = rule['trigger']
        lab_name = trigger['lab']
        condition = trigger['condition']

        # Special case: heart_rate comes from vitals, not labs
        # We allow passing it in patient_labs for rules that use it
        lab_value = patient_labs.get(lab_name)
        if lab_value is None:
            continue

        if not _evaluate_condition(condition, lab_value):
            continue

        # Lab condition met — check if any medication matches
        med_classes = rule.get('medications', [])

        # Rules with empty medications list fire regardless (e.g., lactate/sepsis)
        if not med_classes:
            alerts.append({
                'rule_name': rule['name'],
                'alert_type': 'clinical',
                'severity': rule['severity'],
                'message': rule['message'].format(lab_value=round(lab_value, 2), lab_name=lab_name),
                'action': rule['action'],
                'guideline': rule.get('guideline', ''),
                'rule_logic': f"{lab_name} {condition}",
                'lab_name': lab_name,
                'lab_value': lab_value,
                'triggering_meds': [],
            })
            continue

        matching_meds = [med for med in patient_meds if _med_matches_class(med, med_classes)]

        if matching_meds:
            alerts.append({
                'rule_name': rule['name'],
                'alert_type': 'drug_lab',
                'severity': rule['severity'],
                'message': rule['message'].format(lab_value=round(lab_value, 2), lab_name=lab_name),
                'action': rule['action'],
                'guideline': rule.get('guideline', ''),
                'rule_logic': f"{lab_name} {condition} + {', '.join(med_classes)}",
                'lab_name': lab_name,
                'lab_value': lab_value,
                'triggering_meds': matching_meds,
            })

    return alerts


def check_all_rules(conn):
    """
    Check all patients against drug-lab rules.
    Returns list of alert dicts with subject_id attached.
    """
    cur = conn.cursor()

    cur.execute('SELECT subject_id FROM patients')
    patient_ids = [row[0] for row in cur.fetchall()]

    all_alerts = []

    for pid in patient_ids:
        cur.execute('SELECT med_name FROM medications WHERE subject_id = ?', (pid,))
        meds = [row[0] for row in cur.fetchall()]

        cur.execute(
            'SELECT item_name, value FROM lab_events WHERE subject_id = ? '
            'AND id IN (SELECT MAX(id) FROM lab_events WHERE subject_id = ? GROUP BY item_name)',
            (pid, pid)
        )
        labs = {row[0].lower(): row[1] for row in cur.fetchall()}

        alerts = check_patient_against_rules(meds, labs)
        for alert in alerts:
            alert['subject_id'] = pid
            all_alerts.append(alert)

    return all_alerts
