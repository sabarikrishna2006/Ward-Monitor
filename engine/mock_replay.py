"""
Mock Replay Engine — generates time-series vitals data during seeding.
The dashboard "replays" by showing latest values and sparklines.
No real-time streaming; data is pre-generated in seed.py.
"""


def get_vitals_trend(conn, subject_id, hours=24, parameter=None):
    """
    Get vitals time-series for a patient over the last N hours.
    Returns list of dicts ordered by timestamp.
    """
    cur = conn.cursor()
    query = (
        'SELECT timestamp, heart_rate, respiratory_rate, spo2, sbp, dbp, '
        'temperature, consciousness, air_or_oxygen '
        'FROM vitals_timeseries '
        'WHERE subject_id = ? AND timestamp >= datetime("now", ?) '
        'ORDER BY timestamp'
    )
    cur.execute(query, (subject_id, f'-{hours} hours'))
    rows = cur.fetchall()

    result = []
    for row in rows:
        entry = {
            'timestamp': row[0],
            'heart_rate': row[1],
            'respiratory_rate': row[2],
            'spo2': row[3],
            'sbp': row[4],
            'dbp': row[5],
            'temperature': row[6],
            'consciousness': row[7],
            'air_or_oxygen': row[8],
        }
        if parameter:
            entry['value'] = entry.get(parameter)
        result.append(entry)

    return result


def get_sparkline_data(conn, subject_id, hours=24):
    """
    Get sparkline-ready data (just the numeric arrays) for a patient.
    Returns dict of parameter → [values].
    """
    trends = get_vitals_trend(conn, subject_id, hours)
    return {
        'heart_rate': [t['heart_rate'] for t in trends],
        'respiratory_rate': [t['respiratory_rate'] for t in trends],
        'spo2': [t['spo2'] for t in trends],
        'sbp': [t['sbp'] for t in trends],
        'temperature': [t['temperature'] for t in trends],
    }
