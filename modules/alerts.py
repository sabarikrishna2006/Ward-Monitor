"""Alert API endpoints."""
from flask import Blueprint, jsonify
from utils.db import query_db, get_db

alerts_bp = Blueprint('alerts', __name__)


@alerts_bp.route('/api/alerts')
def all_alerts():
    """Get all active (unacknowledged) alerts."""
    alerts = query_db(
        'SELECT a.*, p.name, p.bed_number FROM alerts a '
        'JOIN patients p ON a.subject_id = p.subject_id '
        'WHERE a.acknowledged = 0 ORDER BY a.severity DESC, a.timestamp DESC'
    )
    return jsonify({'alerts': alerts})


@alerts_bp.route('/api/alerts/acknowledge/<int:alert_id>', methods=['POST'])
def acknowledge_alert(alert_id):
    """Acknowledge an alert."""
    db = get_db()
    db.execute('UPDATE alerts SET acknowledged = 1 WHERE id = ?', (alert_id,))
    db.commit()
    db.close()
    return jsonify({'status': 'ok'})
