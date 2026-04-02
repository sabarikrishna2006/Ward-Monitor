"""Main dashboard routes."""
from flask import Blueprint, render_template, jsonify
from utils.db import get_db, query_db
from engine.ews import calculate_news2
from engine.drug_lab import check_patient_against_rules
from engine.mock_replay import get_sparkline_data

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
def ward_view():
    """Main ward monitoring dashboard."""
    return render_template('ward.html')


@dashboard_bp.route('/patient/<int:subject_id>')
def patient_detail(subject_id):
    """Expanded patient detail view."""
    patient = query_db('SELECT * FROM patients WHERE subject_id = ?', [subject_id], one=True)
    if not patient:
        return "Patient not found", 404
    return render_template('patient_detail.html', patient=patient, subject_id=subject_id)


@dashboard_bp.route('/api/ward-data')
def ward_data():
    """JSON of all patients with current vitals, NEWS2, alerts."""
    db = get_db()
    cur = db.cursor()

    cur.execute('SELECT * FROM patients ORDER BY bed_number')
    patients_raw = [dict(row) for row in cur.fetchall()]

    patients = []
    for p in patients_raw:
        sid = p['subject_id']

        # Latest vitals
        cur.execute(
            'SELECT heart_rate, respiratory_rate, spo2, sbp, dbp, temperature, consciousness, air_or_oxygen, timestamp '
            'FROM vitals_timeseries WHERE subject_id = ? ORDER BY timestamp DESC LIMIT 1',
            (sid,)
        )
        vrow = cur.fetchone()
        if not vrow:
            continue

        vitals = {
            'heart_rate': vrow[0], 'respiratory_rate': vrow[1],
            'spo2': vrow[2], 'sbp': vrow[3], 'dbp': vrow[4],
            'temperature': vrow[5], 'consciousness': vrow[6],
            'air_or_oxygen': vrow[7] or 'air', 'timestamp': vrow[8],
        }

        # NEWS2 score
        news2 = calculate_news2(vitals)

        # Sparkline data (24h)
        sparklines = get_sparkline_data(db, sid, hours=24)

        # Drug-lab alerts
        cur.execute('SELECT med_name FROM medications WHERE subject_id = ?', (sid,))
        meds = [row[0] for row in cur.fetchall()]

        cur.execute(
            'SELECT item_name, value FROM lab_events WHERE subject_id = ? '
            'AND id IN (SELECT MAX(id) FROM lab_events WHERE subject_id = ? GROUP BY item_name)',
            (sid, sid)
        )
        labs = {row[0].lower(): row[1] for row in cur.fetchall()}

        drug_lab_alerts = check_patient_against_rules(meds, labs)

        # Stored alerts from DB
        cur.execute(
            'SELECT * FROM alerts WHERE subject_id = ? ORDER BY timestamp DESC',
            (sid,)
        )
        db_alerts = [dict(row) for row in cur.fetchall()]

        patients.append({
            **p,
            'vitals': vitals,
            'news2': news2,
            'sparklines': sparklines,
            'drug_lab_alerts': drug_lab_alerts,
            'db_alerts': db_alerts,
            'meds': meds,
            'labs': labs,
        })

    # Sort: RED first, then AMBER, then GREEN
    risk_order = {'red': 0, 'amber': 1, 'green': 2}
    patients.sort(key=lambda p: risk_order.get(p['news2']['color'], 3))

    db.close()
    return jsonify({'patients': patients, 'ward': '4B - General Medicine'})


@dashboard_bp.route('/api/patient/<int:subject_id>')
def patient_data(subject_id):
    """JSON of single patient detail."""
    db = get_db()
    cur = db.cursor()

    patient = query_db('SELECT * FROM patients WHERE subject_id = ?', [subject_id], one=True)
    if not patient:
        db.close()
        return jsonify({'error': 'Patient not found'}), 404

    # Full vitals history (48h)
    cur.execute(
        'SELECT timestamp, heart_rate, respiratory_rate, spo2, sbp, dbp, temperature, consciousness, air_or_oxygen '
        'FROM vitals_timeseries WHERE subject_id = ? ORDER BY timestamp',
        (subject_id,)
    )
    vitals_history = [
        {'timestamp': r[0], 'heart_rate': r[1], 'respiratory_rate': r[2],
         'spo2': r[3], 'sbp': r[4], 'dbp': r[5], 'temperature': r[6],
         'consciousness': r[7], 'air_or_oxygen': r[8]}
        for r in cur.fetchall()
    ]

    # All labs
    cur.execute(
        'SELECT timestamp, item_name, value, unit FROM lab_events WHERE subject_id = ? ORDER BY timestamp DESC',
        (subject_id,)
    )
    labs = [{'timestamp': r[0], 'item_name': r[1], 'value': r[2], 'unit': r[3]} for r in cur.fetchall()]

    # Medications
    cur.execute('SELECT med_name, dose, frequency, start_date FROM medications WHERE subject_id = ?', (subject_id,))
    meds = [{'med_name': r[0], 'dose': r[1], 'frequency': r[2], 'start_date': r[3]} for r in cur.fetchall()]

    # Alerts
    cur.execute('SELECT * FROM alerts WHERE subject_id = ? ORDER BY timestamp DESC', (subject_id,))
    alerts = [dict(row) for row in cur.fetchall()]

    # Latest vitals for NEWS2
    latest_vitals = vitals_history[-1] if vitals_history else {}
    news2 = calculate_news2(latest_vitals) if latest_vitals else {}

    db.close()

    return jsonify({
        'patient': patient,
        'vitals_history': vitals_history,
        'labs': labs,
        'meds': meds,
        'alerts': alerts,
        'news2': news2,
    })
