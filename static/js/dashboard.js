/**
 * Ward Monitor Dashboard — Premium Clinical Dashboard JavaScript
 * Handles data fetching, patient cards, alert panel, slide-over detail, filters.
 */

let lastSyncTime = null;
let wardData = null;
let currentFilter = 'all';
let detailChart = null;

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
    let shift = 'Night Shift';
    if (h >= 7 && h < 15) shift = 'Morning Shift';
    else if (h >= 15 && h < 21) shift = 'Afternoon Shift';

    const shiftEl = document.getElementById('shift-info');
    const shiftTopEl = document.getElementById('shift-label-top');
    if (shiftEl) shiftEl.textContent = shift;
    if (shiftTopEl) shiftTopEl.textContent = shift;
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
            updateWardSummary(data.patients);
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
    const label = el.querySelector('span:last-child');
    if (connected) {
        dot.className = 'status-dot connected';
        label.textContent = 'Connected';
    } else {
        dot.className = 'status-dot disconnected';
        label.textContent = 'Disconnected';
    }
}

// ===== Ward Summary =====
function updateWardSummary(patients) {
    const counts = { red: 0, amber: 0, green: 0 };
    patients.forEach(p => { counts[p.news2.color]++; });

    const totalEl = document.getElementById('summary-total');
    const critEl = document.getElementById('summary-critical');
    const warnEl = document.getElementById('summary-warning');
    const stableEl = document.getElementById('summary-stable');

    if (totalEl) totalEl.textContent = patients.length;
    if (critEl) critEl.textContent = counts.red;
    if (warnEl) warnEl.textContent = counts.amber;
    if (stableEl) stableEl.textContent = counts.green;

    // Filter counts
    const fcAll = document.getElementById('fc-all');
    const fcRed = document.getElementById('fc-red');
    const fcAmber = document.getElementById('fc-amber');
    const fcGreen = document.getElementById('fc-green');
    if (fcAll) fcAll.textContent = patients.length;
    if (fcRed) fcRed.textContent = counts.red;
    if (fcAmber) fcAmber.textContent = counts.amber;
    if (fcGreen) fcGreen.textContent = counts.green;

    // Sidebar acuity
    const sCrit = document.getElementById('acuity-critical');
    const sWarn = document.getElementById('acuity-warning');
    const sStable = document.getElementById('acuity-stable');
    if (sCrit) sCrit.textContent = counts.red;
    if (sWarn) sWarn.textContent = counts.amber;
    if (sStable) sStable.textContent = counts.green;
}

// ===== Filter =====
function filterPatients(filter) {
    currentFilter = filter;

    // Update active button
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.filter === filter);
    });

    // Show/hide cards
    document.querySelectorAll('.patient-card').forEach(card => {
        if (filter === 'all') {
            card.style.display = '';
        } else {
            card.style.display = card.classList.contains('risk-' + filter) ? '' : 'none';
        }
    });
}

// ===== Patient Cards =====
function updatePatientCards(patients) {
    const container = document.getElementById('patient-list');
    if (!container) return;

    container.innerHTML = patients.map(p => renderPatientCard(p)).join('');

    // Apply current filter
    if (currentFilter !== 'all') {
        filterPatients(currentFilter);
    }

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
        escalation = `<div class="card-escalation critical"><span class="esc-icon">⚡</span> Immediate: Repeat obs 15min · Notify on-call if unchanged</div>`;
    } else if (n.risk_level === 'MEDIUM') {
        escalation = `<div class="card-escalation"><span class="esc-icon">⚡</span> Increase monitoring · Escalation per NEWS2 protocol</div>`;
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
                <div class="news2-meta">
                    <span class="news2-label">NEWS2</span>
                    <span class="news2-level-badge risk-${n.color}">${n.risk_level}</span>
                </div>
                <div class="news2-gauge">
                    <div class="news2-gauge-ring risk-${n.color}"></div>
                    <span class="news2-score risk-${n.color}">${n.score}</span>
                </div>
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
        p.drug_lab_alerts.forEach(a => {
            allAlerts.push({ ...a, bed_number: p.bed_number, subject_id: p.subject_id, patient_name: p.name });
        });
        p.db_alerts.forEach(a => {
            allAlerts.push({ ...a, bed_number: p.bed_number, subject_id: p.subject_id, patient_name: p.name });
        });
    });

    // Sort: critical first
    allAlerts.sort((a, b) => {
        const sevOrder = { CRITICAL: 0, WARNING: 1 };
        return (sevOrder[a.severity] || 2) - (sevOrder[b.severity] || 2);
    });

    const drugLabAlerts = allAlerts.filter(a => a.alert_type === 'drug_lab');
    const clinicalAlerts = allAlerts.filter(a => a.alert_type === 'clinical' || a.alert_type === 'sepsis' || a.alert_type === 'aki');

    let html = '';

    if (drugLabAlerts.length > 0) {
        html += `<div class="alerts-section-title"><span class="alerts-section-icon">💊</span> Drug-Lab Interactions</div>`;
        html += drugLabAlerts.map(a => renderAlertItem(a)).join('');
    }

    if (clinicalAlerts.length > 0) {
        html += `<div class="alerts-section-title"><span class="alerts-section-icon">🔬</span> Clinical Flags</div>`;
        html += clinicalAlerts.map(a => renderAlertItem(a)).join('');
    }

    if (allAlerts.length === 0) {
        html = `<div class="no-alerts-msg"><span class="no-alerts-icon">✓</span>No active alerts</div>`;
    }

    listEl.innerHTML = html;
    if (totalEl) totalEl.textContent = `${allAlerts.length} active`;
    if (badgeEl) {
        badgeEl.textContent = allAlerts.length;
        badgeEl.className = 'alert-badge' + (allAlerts.length === 0 ? ' low' : '');
    }
}

function renderAlertItem(a) {
    const sevClass = (a.severity || '').toLowerCase() === 'critical' ? 'critical' : 'warning';
    const labInfo = a.lab_name ? `${a.lab_name}: ${a.lab_value}` : '';
    const triggerMeds = a.triggering_meds && a.triggering_meds.length ? a.triggering_meds.join(', ') : '';

    return `
    <div class="alert-item severity-${sevClass}" onclick="this.classList.toggle('expanded')">
        <div class="alert-item-header">
            <span class="alert-bed">Bed ${a.bed_number} · ${a.patient_name || ''}</span>
            <span class="alert-severity ${sevClass}">${a.severity}</span>
        </div>
        <div class="alert-message">${a.message || a.rule_name || ''}</div>
        ${labInfo ? `<div class="alert-meta">${labInfo}${triggerMeds ? ' + ' + triggerMeds : ''}</div>` : ''}
        <div class="alert-details">
            <div class="alert-action-row">
                <span class="alert-action-label">Action:</span>
                <span class="alert-action-text">${a.action || '—'}</span>
            </div>
            ${a.id ? `<button class="alert-ack-btn" onclick="event.stopPropagation(); acknowledgeAlert(${a.id}, this)">Acknowledge</button>` : ''}
        </div>
    </div>`;
}

function acknowledgeAlert(alertId, btnEl) {
    fetch(`/api/alerts/acknowledge/${alertId}`, { method: 'POST' })
        .then(r => r.json())
        .then(() => {
            btnEl.textContent = '✓ Acknowledged';
            btnEl.disabled = true;
            btnEl.style.opacity = '0.5';
        });
}

// ===== Patient Detail (Slide-Over) =====
function openPatientDetail(subjectId) {
    const modal = document.getElementById('patient-detail-modal');
    const contentEl = document.getElementById('patient-detail-content');
    if (!modal) return;

    modal.classList.remove('d-none');
    contentEl.innerHTML = '<div class="loading-placeholder"><div class="loading-spinner"></div><div>Loading patient details...</div></div>';

    fetch(`/api/patient/${subjectId}`)
        .then(r => r.json())
        .then(data => {
            renderSlideOverDetail(data, contentEl);
        });
}

function closePatientDetail() {
    const modal = document.getElementById('patient-detail-modal');
    if (modal) modal.classList.add('d-none');
    if (detailChart) { detailChart.destroy(); detailChart = null; }
}

// Close on Escape
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closePatientDetail();
});

function renderSlideOverDetail(data, container) {
    const p = data.patient;
    const news2 = data.news2;

    const badgeClass = `risk-badge-${news2.color}`;

    container.innerHTML = `
        <!-- Patient Header -->
        <div class="detail-header">
            <div class="detail-patient-info">
                <div class="detail-bed risk-${news2.color}">BED ${p.bed_number}</div>
                <div class="detail-name">${p.name}</div>
                <div class="detail-condition">${p.age}${p.gender} · ${p.condition}</div>
                <div class="detail-admit">Admitted: ${new Date(p.admit_date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}</div>
            </div>
        </div>

        <div class="detail-grid">
            <!-- NEWS2 Score -->
            <div class="detail-section">
                <h3><span class="section-icon news2">📊</span> NEWS2 Score</h3>
                <div class="news2-detail">
                    <span class="news2-score-big ${badgeClass}">${news2.score}</span>
                    <span class="news2-level ${badgeClass}">${news2.risk_level} RISK</span>
                </div>
                <div class="news2-breakdown">
                    ${Object.entries(news2.breakdown).map(([k, v]) =>
                        `<span class="breakdown-item ${v > 0 ? 'has-score' : ''}">${k.replace(/_/g, ' ')}: <span class="score-val">${v}</span></span>`
                    ).join('')}
                </div>
                <div class="clinical-response">${news2.clinical_response}</div>
            </div>

            <!-- Vitals Chart -->
            <div class="detail-section">
                <h3><span class="section-icon vitals">📈</span> 24-Hour Trends</h3>
                <div class="vitals-chart-container">
                    <canvas id="detail-vitals-chart"></canvas>
                </div>
            </div>

            <!-- Vitals Table -->
            <div class="detail-section full-width">
                <h3><span class="section-icon vitals">🩺</span> Recent Vitals</h3>
                <div style="overflow-x:auto">
                    <table class="table table-dark table-sm vitals-table">
                        <thead>
                            <tr>
                                <th>Time</th>
                                <th>HR</th>
                                <th>RR</th>
                                <th>SpO₂</th>
                                <th>BP</th>
                                <th>Temp</th>
                                <th>LOC</th>
                            </tr>
                        </thead>
                        <tbody id="so-vitals-tbody"></tbody>
                    </table>
                </div>
            </div>

            <!-- Labs -->
            <div class="detail-section">
                <h3><span class="section-icon labs">🧪</span> Lab Results</h3>
                <div style="overflow-x:auto">
                    <table class="table table-dark table-sm vitals-table">
                        <thead>
                            <tr><th>Time</th><th>Test</th><th>Value</th><th>Unit</th></tr>
                        </thead>
                        <tbody id="so-labs-tbody"></tbody>
                    </table>
                </div>
            </div>

            <!-- Medications -->
            <div class="detail-section">
                <h3><span class="section-icon meds">💊</span> Active Medications</h3>
                <div id="so-meds-list"></div>
            </div>

            <!-- Alerts -->
            <div class="detail-section full-width">
                <h3><span class="section-icon alerts">⚠</span> Alert History</h3>
                <div id="so-alerts-history"></div>
            </div>
        </div>
    `;

    // Vitals table
    const vitals = data.vitals_history.slice(-24).reverse();
    document.getElementById('so-vitals-tbody').innerHTML = vitals.map(v => `
        <tr>
            <td>${new Date(v.timestamp).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}</td>
            <td class="${highlightVital(v.heart_rate, 50, 90, 110, 130)}">${Math.round(v.heart_rate)}</td>
            <td class="${highlightVital(v.respiratory_rate, 12, 20, 24, 25)}">${Math.round(v.respiratory_rate)}</td>
            <td class="${highlightVitalReverse(v.spo2, 96, 94, 92, 91)}">${Math.round(v.spo2)}%</td>
            <td>${Math.round(v.sbp)}/${Math.round(v.dbp)}</td>
            <td class="${highlightVital(v.temperature, 36.1, 38.0, 39.0, 39.1)}">${v.temperature.toFixed(1)}°</td>
            <td>${v.consciousness || 'A'}</td>
        </tr>
    `).join('');

    // Labs
    document.getElementById('so-labs-tbody').innerHTML = data.labs.map(l => `
        <tr>
            <td>${new Date(l.timestamp).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})}</td>
            <td>${l.item_name}</td>
            <td>${l.value}</td>
            <td>${l.unit}</td>
        </tr>
    `).join('');

    // Meds
    document.getElementById('so-meds-list').innerHTML = data.meds.length ? data.meds.map(m => `
        <div class="med-item">
            <span class="med-pill"></span>
            <span class="med-name">${m.med_name}</span>
            <span class="med-dose">${m.dose} ${m.frequency}</span>
            <span class="med-since">since ${m.start_date}</span>
        </div>
    `).join('') : '<div style="color:var(--text-dim);font-size:12px">No active medications</div>';

    // Alerts
    document.getElementById('so-alerts-history').innerHTML = data.alerts.length ?
        data.alerts.map(a => `
            <div class="alert-item-detail severity-${a.severity.toLowerCase()}">
                <span class="alert-sev sev-${a.severity.toLowerCase()}">${a.severity}</span>
                <span class="alert-type">${a.alert_type}</span>
                <span class="alert-msg">${a.message}</span>
                ${a.action ? `<span class="alert-action">${a.action}</span>` : ''}
                <span class="alert-time">${new Date(a.timestamp).toLocaleString()}</span>
            </div>
        `).join('') : '<div style="color:var(--text-dim);font-size:12px">No alerts recorded</div>';

    // Chart
    if (typeof Chart !== 'undefined' && data.vitals_history.length > 0) {
        renderDetailChart(data.vitals_history);
    }
}

function renderDetailChart(history) {
    const canvas = document.getElementById('detail-vitals-chart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    if (detailChart) { detailChart.destroy(); }

    const labels = history.map(h => new Date(h.timestamp).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}));

    // Gradient fills
    const hrGrad = ctx.createLinearGradient(0, 0, 0, 260);
    hrGrad.addColorStop(0, 'rgba(239, 68, 68, 0.25)');
    hrGrad.addColorStop(1, 'rgba(239, 68, 68, 0.0)');

    const spo2Grad = ctx.createLinearGradient(0, 0, 0, 260);
    spo2Grad.addColorStop(0, 'rgba(34, 197, 94, 0.20)');
    spo2Grad.addColorStop(1, 'rgba(34, 197, 94, 0.0)');

    detailChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [
                { label: 'HR', data: history.map(h => h.heart_rate), borderColor: '#ef4444', backgroundColor: hrGrad, borderWidth: 2, pointRadius: 0, tension: 0.4, fill: true },
                { label: 'RR', data: history.map(h => h.respiratory_rate), borderColor: '#f59e0b', borderWidth: 1.5, pointRadius: 0, tension: 0.4, fill: false },
                { label: 'SpO₂', data: history.map(h => h.spo2), borderColor: '#22c55e', backgroundColor: spo2Grad, borderWidth: 2, pointRadius: 0, tension: 0.4, yAxisID: 'y1', fill: true },
                { label: 'Temp', data: history.map(h => h.temperature), borderColor: '#8b5cf6', borderWidth: 1.5, pointRadius: 0, tension: 0.4, yAxisID: 'y2', fill: false },
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
                x: {
                    ticks: { maxTicksLimit: 12, color: '#5f6672', font: { family: 'JetBrains Mono', size: 9 } },
                    grid: { color: 'rgba(255,255,255,0.04)', drawBorder: false }
                },
                y: {
                    position: 'left',
                    title: { display: true, text: 'HR / RR', color: '#5f6672', font: { family: 'Inter', size: 10 } },
                    ticks: { color: '#5f6672', font: { family: 'JetBrains Mono', size: 9 } },
                    grid: { color: 'rgba(255,255,255,0.04)', drawBorder: false }
                },
                y1: {
                    position: 'right',
                    title: { display: true, text: 'SpO₂ %', color: '#5f6672', font: { family: 'Inter', size: 10 } },
                    min: 85, max: 100,
                    ticks: { color: '#5f6672', font: { family: 'JetBrains Mono', size: 9 } },
                    grid: { display: false }
                },
                y2: { display: false, min: 35, max: 40 },
            },
            plugins: {
                legend: {
                    labels: { color: '#9aa0a9', usePointStyle: true, pointStyle: 'line', padding: 16, font: { family: 'Inter', size: 11 } }
                },
                tooltip: {
                    backgroundColor: 'rgba(15, 20, 25, 0.95)',
                    borderColor: 'rgba(255,255,255,0.1)',
                    borderWidth: 1,
                    cornerRadius: 8,
                    titleFont: { family: 'JetBrains Mono', size: 11 },
                    bodyFont: { family: 'JetBrains Mono', size: 11 },
                    padding: 10,
                }
            }
        }
    });
}

function highlightVital(val, low, normal_high, warn_high, crit) {
    if (val >= crit) return 'vital-critical';
    if (val >= warn_high) return 'vital-warning';
    if (val <= low - 5) return 'vital-critical';
    if (val <= low) return 'vital-warning';
    return '';
}

function highlightVitalReverse(val, good, warn1, warn2, crit) {
    if (val <= crit) return 'vital-critical';
    if (val <= warn2) return 'vital-warning';
    return '';
}

// Update "last sync" display
setInterval(() => {
    if (lastSyncTime) {
        const el = document.getElementById('last-sync');
        if (el) el.textContent = formatTimeAgo(lastSyncTime);
    }
}, 5000);
