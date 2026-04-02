"""
NEWS2 (National Early Warning Score 2) Calculator
"""


def score_respiratory_rate(rr):
    """Score respiratory rate (breaths per minute)."""
    if rr <= 8:
        return 3
    elif rr <= 11:
        return 1
    elif rr <= 20:
        return 0
    elif rr <= 24:
        return 2
    else:
        return 3


def score_spo2(spo2):
    """Score SpO2 Scale 1 (%)."""
    if spo2 <= 91:
        return 3
    elif spo2 <= 93:
        return 2
    elif spo2 <= 95:
        return 1
    else:
        return 0


def score_systolic_bp(sbp):
    """Score systolic blood pressure (mmHg)."""
    if sbp <= 90:
        return 3
    elif sbp <= 100:
        return 2
    elif sbp <= 110:
        return 1
    elif sbp <= 219:
        return 0
    else:
        return 3


def score_heart_rate(hr):
    """Score heart rate (bpm)."""
    if hr <= 40:
        return 3
    elif hr <= 50:
        return 1
    elif hr <= 90:
        return 0
    elif hr <= 110:
        return 1
    elif hr <= 130:
        return 2
    else:
        return 3


def score_temperature(temp):
    """Score temperature (°C)."""
    if temp <= 35.0:
        return 3
    elif temp <= 36.0:
        return 1
    elif temp <= 38.0:
        return 0
    elif temp <= 39.0:
        return 1
    else:
        return 2


def score_consciousness(consciousness):
    """Score consciousness level (A=Alert, C=Confused, V=Voice, P=Pain, U=Unresponsive)."""
    if consciousness == 'A':
        return 0
    else:
        return 3


def score_air_oxygen(air_or_oxygen):
    """Score air or supplemental oxygen. 'air' or 'oxygen'."""
    if air_or_oxygen and air_or_oxygen.lower() == 'oxygen':
        return 2
    return 0


def calculate_news2(vitals):
    """
    Calculate NEWS2 score from a vitals dict.

    vitals should have: respiratory_rate, spo2, sbp, heart_rate, temperature
    Optional: consciousness (default 'A'), air_or_oxygen (default 'air')

    Returns: { score, risk_level, color, clinical_response, breakdown }
    """
    rr = vitals.get('respiratory_rate', 16)
    spo2 = vitals.get('spo2', 98)
    sbp = vitals.get('sbp', 120)
    hr = vitals.get('heart_rate', 72)
    temp = vitals.get('temperature', 37.0)
    consciousness = vitals.get('consciousness', 'A')
    air_or_oxygen = vitals.get('air_or_oxygen', 'air')

    breakdown = {
        'respiratory_rate': score_respiratory_rate(rr),
        'spo2': score_spo2(spo2),
        'systolic_bp': score_systolic_bp(sbp),
        'heart_rate': score_heart_rate(hr),
        'temperature': score_temperature(temp),
        'consciousness': score_consciousness(consciousness),
        'air_or_oxygen': score_air_oxygen(air_or_oxygen),
    }

    total = sum(breakdown.values())

    if total >= 7:
        risk_level = 'HIGH'
        color = 'red'
        clinical_response = (
            'Continuous monitoring of vital signs. Urgent or emergency assessment '
            'by a clinician with critical care competencies, including airway management. '
            'Consider transfer to Level 2/3 care.'
        )
    elif total >= 5:
        risk_level = 'MEDIUM'
        color = 'amber'
        clinical_response = (
            'Continuous monitoring of vital signs. Urgent assessment by ward-based '
            'nurse who should have a escalation plan using NEWS2. '
            'Assess for need to transfer to higher-dependency bed.'
        )
    else:
        risk_level = 'LOW'
        color = 'green'
        clinical_response = (
            'Assessment by registered nurse who should decide if increased '
            'frequency of monitoring and/or escalation of clinical care is required.'
        )

    # Check for any individual score of 3 — triggers immediate escalation
    if any(v == 3 for v in breakdown.values()):
        if risk_level == 'LOW':
            clinical_response = (
                'Single parameter score of 3 detected. Requires urgent ward-based '
                'response and minimum of 1-hourly observations. Consider clinical review.'
            )

    return {
        'score': total,
        'risk_level': risk_level,
        'color': color,
        'clinical_response': clinical_response,
        'breakdown': breakdown,
    }
