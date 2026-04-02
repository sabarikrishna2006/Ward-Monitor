/**
 * Ward Monitor Dashboard — Main JavaScript
 * Handles data fetching, DOM updates, sparklines, and alert panel.
 */

let lastSyncTime = null;
let wardData = null;

// ===== Clock =====
function updateClock() {
    const now = new Date();
    const timeStr = now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const shortTime = now.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
    const clockEl = document.getElementById('clock');
    const topClockEl = document.getElementById('top-clock');
    if (clockEl) clockEl.textContent = timeStr;
    if (topClockEl) topClockEl.textContent = shortTime;

    // Shift detection
    const h = now.getHours();
    const shiftEl = document.getElementById('shift-info');
    if (shiftEl) {
        if (h >= 7 && h < 15) shiftEl.textContent = 'Morning Shift';
        else if (h >= 15 && h < 21) shiftEl.textContent = 'Afternoon Shift';
        else shiftEl.textContent = 'Night Shift';
    }
}
setInterval(updateClock, 1000);
updateClock();

// ===== Time Ago =====
function formatTimeAgo(timestamp) {
    if (!timestamp) return '—';
    const now = Date.now();
    const then = new Date(timestamp).getTime();
    const diff = Math.floor((now - then) / 1000);
    if (diff < 5) return 'just now';
    if (diff < 60) return diff + 's ago';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
}

// ===== Fetch Ward Data =====
function fetchWardData() {
    fetch('/api/ward-data')
        .then(r => r.json())
        .then(data => {
            wardData = data;
            lastSyncTime = new Date();
            updatePatientCards(data.patients);
            updateAlertPanel(data.patients);
            updateConnectionStatus(true);
            document.getElementById('last-sync').textContent = 'just now';
        })
        .catch(err => {
            console.error('Failed to fetch ward data:', err);
            updateConnectionStatus(false);
        });
}

function updateConnectionStatus(connected) {
    const el = document.getElementById('connection-status');
    if (!el) return;
    const dot = el.querySelector('.status-dot');
    if (connected) {
        dot.className = 'status-dot connected';
        el.querySelector('span:last-child').textContent = 'Connected';
    } else {
        dot.className = 'status-dot disconnected';
        el.querySelector('span:last-child').textContent = 'Disconnected';
    }
}

// ===== Patient Cards =====
function updatePatientCards(patients) {
    const container = document.getElementById('patient-list');
    if (!container) return;

    container.innerHTML = patients.map(p => renderPatientCard(p)).join('');

    // Render sparklines after DOM update
    requestAnimationFrame(() => {
        patients.forEach(p => {
            renderPatientSparklines(p);
        });
    });
}

function renderPatientCard(p) {
    const n = p.news2;
    const v = p.vitals;
    const spark = p.sparklines;

    const lastHR = spark.heart_rate.length ? spark.heart_rate[spark.heart_rate.length - 1] : v.heart_rate;
    const firstHR = spark.heart_rate.length ? spark.heart_rate[0] : v.heart_rate;
    const lastRR = spark.respiratory_rate.length ? spark.respiratory_rate[spark.respiratory_rate.length - 1] : v.respiratory_rate;
    const lastSpO2 = spark.spo2.length ? spark.spo2[spark.spo2.length - 1] : v.spo2;
    const lastTemp = spark.temperature.length ? spark.temperature[spark.temperature.length - 1] : v.temperature;
    const firstTemp = spark.temperature.length ? spark.temperature[0] : v.temperature;

    const hrClass = lastHR > 130 ? 'vital-crit' : lastHR > 110 ? 'vital-warn' : '';
    const rrClass = lastRR > 24 ? 'vital-crit' : lastRR > 20 ? 'vital-warn' : '';
    const spo2Class = lastSpO2 < 92 ? 'vital-crit' : lastSpO2 < 95 ? 'vital-warn' : '';

    let escalation = '';
    if (n.risk_level === 'HIGH') {
        escalation = `<div class="card-escalation critical">⚡ Escalation: Repeat obs 15min · Notify on-call if unchanged</div>`;
    } else if (n.risk_level === 'MEDIUM') {
        escalation = `<div class="card-escalation">⚡ Increase monitoring frequency · Escalation plan per NEWS2</div>`;
    }

    return `
    <div class="patient-card risk-${n.color}" onclick="openPatientDetail(${p.subject_id})" data-subject-id="${p.subject_id}">
        <div class="card-header">
            <div class="card-identity">
                <span class="card-bed risk-${n.color}">BED ${p.bed_number}</span>
                <div>
                    <div class="card-name">${p.name}</div>
                    <div class="card-demo">${p.age}${p.gender} · ${p.condition}</div>
                </div>
            </div>
            <div class="card-scores">
                <div class="news2-label">NEWS2</div>
                <span class="news2-score risk-${n.color}">${n.score}</span>
                <span class="news2-level-badge risk-${n.color}">${n.risk_level}</span>
            </div>
        </div>
        <div class="card-sparklines">
            <div class="sparkline-cell">
                <div class="sparkline-label">HR</div>
                <div class="sparkline-current ${hrClass}">${Math.round(lastHR)}</div>
                <canvas class="sparkline-canvas" id="spark-hr-${p.subject_id}"></canvas>
                <div class="sparkline-values"><span>${Math.round(firstHR)}</span><span>${Math.round(lastHR)}</span></div>
            </div>
            <div class="sparkline-cell">
                <div class="sparkline-label">RR</div>
                <div class="sparkline-current ${rrClass}">${Math.round(lastRR)}</div>
                <canvas class="sparkline-canvas" id="spark-rr-${p.subject_id}"></canvas>
            </div>
            <div class="sparkline-cell">
                <div class="sparkline-label">SpO₂</div>
                <div class="sparkline-current ${spo2Class}">${Math.round(lastSpO2)}%</div>
                <canvas class="sparkline-canvas" id="spark-spo2-${p.subject_id}"></canvas>
            </div>
            <div class="sparkline-cell">
                <div class="sparkline-label">BP</div>
                <div class="sparkline-current">${Math.round(v.sbp)}/${Math.round(v.dbp)}</div>
                <canvas class="sparkline-canvas" id="spark-bp-${p.subject_id}"></canvas>
            </div>
            <div class="sparkline-cell">
                <div class="sparkline-label">Temp</div>
                <div class="sparkline-current">${lastTemp.toFixed(1)}°</div>
                <canvas class="sparkline-canvas" id="spark-temp-${p.subject_id}"></canvas>
            </div>
        </div>
        ${escalation}
    </div>`;
}

function renderPatientSparklines(p) {
    const s = p.sparklines;
    const sid = p.subject_id;

    const hrCanvas = document.getElementById(`spark-hr-${sid}`);
    const rrCanvas = document.getElementById(`spark-rr-${sid}`);
    const spo2Canvas = document.getElementById(`spark-spo2-${sid}`);
    const bpCanvas = document.getElementById(`spark-bp-${sid}`);
    const tempCanvas = document.getElementById(`spark-temp-${sid}`);

    if (hrCanvas && s.heart_rate.length) {
        const maxHR = Math.max(...s.heart_rate);
        const minHR = Math.min(...s.heart_rate);
        const hrColor = maxHR > 130 ? '#ef4444' : maxHR > 110 ? '#f59e0b' : '#3b82f6';
        renderSparkline(hrCanvas, s.heart_rate, { color: hrColor, min: Math.min(40, minHR - 5), max: Math.max(140, maxHR + 5) });
    }
    if (rrCanvas && s.respiratory_rate.length) {
        const maxRR = Math.max(...s.respiratory_rate);
        const rrColor = maxRR > 24 ? '#ef4444' : maxRR > 20 ? '#f59e0b' : '#f59e0b';
        renderSparkline(rrCanvas, s.respiratory_rate, { color: rrColor, min: 8, max: Math.max(30, maxRR + 3) });
    }
    if (spo2Canvas && s.spo2.length) {
        const minSpO2 = Math.min(...s.spo2);
        const spo2Color = minSpO2 < 92 ? '#ef4444' : minSpO2 < 95 ? '#f59e0b' : '#22c55e';
        renderSparkline(spo2Canvas, s.spo2, { color: spo2Color, min: 88, max: 100 });
    }
    if (bpCanvas && s.sbp.length) {
        renderSparkline(bpCanvas, s.sbp, { color: '#8b5cf6', min: 70, max: 180 });
    }
    if (tempCanvas && s.temperature.length) {
        const maxTemp = Math.max(...s.temperature);
        const tempColor = maxTemp > 39 ? '#ef4444' : maxTemp > 38 ? '#f59e0b' : '#8b5cf6';
        renderSparkline(tempCanvas, s.temperature, { color: tempColor, min: 35.5, max: 40 });
    }
}

// ===== Alert Panel =====
function updateAlertPanel(patients) {
    const listEl = document.getElementById('alerts-list');
    const totalEl = document.getElementById('alert-total');
    const badgeEl = document.getElementById('alert-badge');
    if (!listEl) return;

    let allAlerts = [];

    patients.forEach(p => {
        // Drug-lab alerts
        p.drug_lab_alerts.forEach(a => {
            allAlerts.push({
                ...a,
                bed_number: p.bed_number,
                subject_id: p.subject_id,
                patient_name: p.name,
            });
        });

        // Sepsis/AKI clinical flags
        p.db_alerts.forEach(a => {
            allAlerts.push({
                ...a,
                bed_number: p.bed_number,
                subject_id: p.subject_id,
                patient_name: p.name,
            });
        });
    });

    // Sort: critical first
    allAlerts.sort((a, b) => {
        const sevOrder = { CRITICAL: 0, WARNING: 1 };
        return (sevOrder[a.severity] || 2) - (sevOrder[b.severity] || 2);
    });

    // Drug-lab alerts
    const drugLabAlerts = allAlerts.filter(a => a.alert_type === 'drug_lab');
    const clinicalAlerts = allAlerts.filter(a => a.alert_type === 'clinical' || a.alert_type === 'sepsis' || a.alert_type === 'aki');

    let html = '';

    if (drugLabAlerts.length > 0) {
        html += `<div class="alerts-section-title">💊 Drug-Lab Interactions</div>`;
        html += drugLabAlerts.map(a => renderAlertItem(a)).join('');
    }

    if (clinicalAlerts.length > 0) {
        html += `<div class="alerts-section-title">🦠 Clinical Flags</div>`;
        html += clinicalAlerts.map(a => renderAlertItem(a)).join('');
    }

    if (allAlerts.length === 0) {
        html = '<div class="loading-placeholder" style="color:#22c55e">✓ No active alerts</div>';
    }

    listEl.innerHTML = html;
    if (totalEl) totalEl.textContent = `${allAlerts.length} active`;
    if (badgeEl) {
        badgeEl.textContent = allAlerts.length;
        badgeEl.style.background = allAlerts.length > 0 ? 'var(--risk-red)' : 'var(--risk-green)';
    }
}

function renderAlertItem(a) {
    const sevClass = (a.severity || '').toLowerCase() === 'critical' ? 'critical' : 'warning';
    const labInfo = a.lab_name ? `${a.lab_name} ${a.lab_value}` : '';
    const triggerMeds = a.triggering_meds && a.triggering_meds.length ? `+ ${a.triggering_meds.join(', ')}` : '';

    return `
    <div class="alert-item severity-${sevClass}" onclick="this.classList.toggle('expanded')">
        <div class="alert-item-header">
            <span class="alert-bed">Bed ${a.bed_number} · ${a.patient_name || ''}</span>
            <span class="alert-severity ${sevClass}">${a.severity}</span>
        </div>
        <div class="alert-message">${a.message || a.rule_name || ''}</div>
        ${labInfo ? `<div style="font-size:11px;color:var(--text-muted)">${labInfo} ${triggerMeds}</div>` : ''}
        <div class="alert-details">
            <div><strong>Action:</strong> ${a.action || '—'}</div>
        </div>
    </div>`;
}

// ===== Patient Detail (inline expand) =====
function openPatientDetail(subjectId) {
    // Navigate to patient detail page
    window.location.href = `/patient/${subjectId}`;
}

function closePatientDetail() {
    const modal = document.getElementById('patient-detail-modal');
    if (modal) modal.classList.add('d-none');
}

// Update "last sync" display
setInterval(() => {
    if (lastSyncTime) {
        const el = document.getElementById('last-sync');
        if (el) el.textContent = formatTimeAgo(lastSyncTime);
    }
}, 5000);
