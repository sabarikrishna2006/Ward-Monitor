"""
Drug-Lab Interaction Rule Engine
Loads rules from rules/drug_lab_rules.yaml and checks patient data against them.
"""
import os
import yaml

RULES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'rules', 'drug_lab_rules.yaml')

# Map of drug class keywords to their member medications
DRUG_CLASS_MAP = {
    'ace_inhibitors': ['lisinopril', 'enalapril', 'ramipril', 'perindopril', 'captopril'],
    'k_sparing_diuretics': ['spironolactone', 'amiloride', 'eplerenone'],
    'metformin': ['metformin'],
    'nsaids': ['ibuprofen', 'naproxen', 'diclofenac', 'indomethacin', 'ketorolac', 'aspirin'],
    'anticoagulants': ['warfarin', 'apixaban', 'rivaroxaban', 'dabigatran', 'enoxaparin', 'heparin'],
}


def load_rules():
    """Load rules from YAML file."""
    with open(RULES_PATH, 'r') as f:
        return yaml.safe_load(f)['rules']


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
    Check a single patient's meds and labs against drug-lab rules.
    
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

        lab_value = patient_labs.get(lab_name)
        if lab_value is None:
            continue

        if not _evaluate_condition(condition, lab_value):
            continue

        # Lab condition met — check if any medication matches
        med_classes = rule.get('medications', [])
        matching_meds = []
        for med in patient_meds:
            if _med_matches_class(med, med_classes):
                matching_meds.append(med)

        if matching_meds:
            alerts.append({
                'rule_name': rule['name'],
                'alert_type': 'drug_lab',
                'severity': rule['severity'],
                'message': rule['message'].format(lab_value=lab_value, lab_name=lab_name),
                'action': rule['action'],
                'lab_name': lab_name,
                'lab_value': lab_value,
                'triggering_meds': matching_meds,
            })

    # Check sepsis concern rule (lactate > 2.0 triggers regardless of meds)
    lactate = patient_labs.get('lactate')
    if lactate is not None and lactate > 2.0:
        has_sepsis_alert = any(a.get('rule_name', '').startswith('Lactate') for a in alerts)
        if not has_sepsis_alert:
            alerts.append({
                'rule_name': 'Lactate elevation — sepsis concern',
                'alert_type': 'clinical',
                'severity': 'WARNING' if lactate <= 4.0 else 'CRITICAL',
                'message': f'Lactate elevated at {lactate} mmol/L — consider sepsis workup.',
                'action': 'Assess for sepsis criteria. Consider blood cultures, broad-spectrum antibiotics.',
                'lab_name': 'lactate',
                'lab_value': lactate,
                'triggering_meds': [],
            })

    return alerts


def check_all_rules(conn):
    """
    Check all patients against drug-lab rules.
    Returns list of alert dicts with subject_id attached.
    """
    cur = conn.cursor()

    # Get all patients
    cur.execute('SELECT subject_id FROM patients')
    patient_ids = [row[0] for row in cur.fetchall()]

    all_alerts = []

    for pid in patient_ids:
        # Get medications
        cur.execute('SELECT med_name FROM medications WHERE subject_id = ?', (pid,))
        meds = [row[0] for row in cur.fetchall()]

        # Get latest lab values
        cur.execute(
            'SELECT item_name, value FROM lab_events WHERE subject_id = ? '
            'AND id IN (SELECT MAX(id) FROM lab_events WHERE subject_id = ? GROUP BY item_name)',
            (pid, pid)
        )
        labs = {row[0].lower(): row[1] for row in cur.fetchall()}

        # Check rules
        alerts = check_patient_against_rules(meds, labs)
        for alert in alerts:
            alert['subject_id'] = pid
            all_alerts.append(alert)

    return all_alerts
