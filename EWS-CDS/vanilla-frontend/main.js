import { createIcons, icons } from 'lucide';
import Chart from 'chart.js/auto';

createIcons({ icons });

let patients = [];
let activeFilter = 'All';
let isReplay = false;
let selectedWard = 'All';
let chartInstances = {}; // to keep track of chart.js instances

const DOM = {
    patientsContainer: document.getElementById('patients-container'),
    wardSelect: document.getElementById('ward-select'),
    btnReplay: document.getElementById('btn-replay'),
    replayIcon: document.getElementById('replay-icon'),
    replayText: document.getElementById('replay-text'),
    countAll: document.getElementById('count-all'),
    countCritical: document.getElementById('count-critical'),
    countWarning: document.getElementById('count-warning'),
    countStable: document.getElementById('count-stable'),
    filters: {
        'All': document.getElementById('filter-all'),
        'Critical': document.getElementById('filter-critical'),
        'Warning': document.getElementById('filter-warning'),
        'Stable': document.getElementById('filter-stable')
    },
    drawer: document.getElementById('patient-drawer'),
    drawerOverlay: document.getElementById('drawer-overlay')
};

function init() {
    DOM.wardSelect.addEventListener('change', (e) => {
        selectedWard = e.target.value;
        fetchData();
    });

    DOM.btnReplay.addEventListener('click', () => {
        isReplay = !isReplay;
        if(isReplay) {
            DOM.btnReplay.className = "flex items-center space-x-1 px-3 py-1.5 rounded-full text-xs font-bold transition-colors border bg-blue-600/20 text-blue-400 border-blue-500/50 mr-2";
            DOM.replayIcon.classList.add('animate-pulse');
            DOM.replayText.innerText = "Replaying";
        } else {
            DOM.btnReplay.className = "flex items-center space-x-1 px-3 py-1.5 rounded-full text-xs font-bold transition-colors border bg-slate-800/50 text-slate-400 border-slate-700 hover:text-white mr-2";
            DOM.replayIcon.classList.remove('animate-pulse');
            DOM.replayText.innerText = "Mock Replay";
        }
        fetchData();
    });

    Object.keys(DOM.filters).forEach(key => {
        DOM.filters[key].addEventListener('click', () => {
            activeFilter = key;
            updateFilterStyles();
            renderPatients();
        });
    });

    DOM.drawerOverlay.addEventListener('click', closeDrawer);

    fetchData();
    setInterval(fetchData, 15000); // Poll every 15s
}

function updateFilterStyles() {
    Object.keys(DOM.filters).forEach(key => {
        const btn = DOM.filters[key];
        btn.className = `flex shrink-0 items-center space-x-3 px-4 py-2.5 rounded-xl border transition-all ${
            activeFilter === key 
                ? (key==='Critical' ? 'bg-[#ef4444]/20 border-[#ef4444] shadow-[0_0_12px_rgba(239,68,68,0.3)]' :
                   key==='Warning' ? 'bg-yellow-500/20 border-yellow-500 shadow-[0_0_12px_rgba(234,179,8,0.3)]' :
                   key==='Stable' ? 'bg-[#10b981]/20 border-[#10b981] shadow-[0_0_12px_rgba(16,185,129,0.3)]' :
                   'bg-blue-600/20 border-blue-500 shadow-[0_0_12px_rgba(59,130,246,0.3)]')
                : 'bg-[#0f172a] border-slate-700 hover:border-slate-600'
        }`;
    });
}

function fetchData() {
    fetch(`http://localhost:8000/api/ward-data?ward=${selectedWard}&replay=${isReplay}`)
        .then(res => res.json())
        .then(data => {
            patients = data.patients;
            updateStats();
            renderPatients();
        })
        .catch(err => console.error(err));
}

function updateStats() {
    DOM.countAll.innerText = patients.length;
    DOM.countCritical.innerText = patients.filter(p => p.status === 'critical').length;
    DOM.countWarning.innerText = patients.filter(p => p.status === 'warning').length;
    DOM.countStable.innerText = patients.filter(p => p.status === 'stable').length;
}

function renderPatients() {
    const filtered = patients.filter(p => activeFilter === 'All' || p.status.toLowerCase() === activeFilter.toLowerCase());
    
    // Sort critical first
    const sorted = filtered.sort((a, b) => {
        const order = { critical: 3, warning: 2, stable: 1 };
        return order[b.status] - order[a.status];
    });

    let html = '';
    sorted.forEach(p => {
        let statusColor, statusBg, statusBorder, shadow;
        if (p.status === 'critical') {
            statusColor = 'text-[#ef4444]'; statusBg = 'bg-[#ef4444]/10'; statusBorder = 'border-[#ef4444]/50'; shadow = 'shadow-[inset_4px_0_0_#ef4444]';
        } else if (p.status === 'warning') {
            statusColor = 'text-yellow-400'; statusBg = 'bg-yellow-400/10'; statusBorder = 'border-yellow-400/50'; shadow = 'shadow-[inset_4px_0_0_#facc15]';
        } else {
            statusColor = 'text-[#10b981]'; statusBg = 'bg-[#10b981]/10'; statusBorder = 'border-[#10b981]/50'; shadow = 'shadow-[inset_4px_0_0_#10b981]';
        }

        html += `
            <div class="patient-row flex items-center bg-[#0f172a] border border-slate-800 rounded-xl p-4 hover:border-slate-600 transition-all cursor-pointer relative overflow-hidden group ${shadow}" data-id="${p.id}">
                <div class="absolute inset-0 bg-gradient-to-r from-transparent via-white/[0.02] to-transparent translate-x-[-100%] group-hover:animate-[shimmer_1.5s_infinite]"></div>
                <div class="w-[50px] md:w-[60px] shrink-0 font-mono text-sm font-bold text-slate-400">${p.bed}</div>
                
                <div class="w-[120px] md:w-[150px] shrink-0">
                    <div class="font-bold text-white group-hover:text-blue-400 transition-colors">${p.name}</div>
                    <div class="text-[10px] text-slate-500 font-medium uppercase tracking-wider mt-0.5">ID: ${p.id}</div>
                </div>

                <div class="w-[120px] shrink-0 hidden md:block">
                    <div class="text-xs text-slate-300 font-medium truncate pr-2">${p.complaint}</div>
                    <div class="text-[10px] text-slate-500 mt-0.5">${p.age}y • ${p.sex}</div>
                </div>

                <div class="flex-1 hidden sm:block h-[40px] px-4">
                    <canvas id="sparkline-${p.id}" class="w-full h-full"></canvas>
                </div>

                <div class="w-[80px] md:w-[130px] shrink-0 flex flex-col items-end justify-center">
                    <div class="flex items-end space-x-2">
                        <div class="text-xs font-bold uppercase tracking-widest ${statusColor} mb-1 hidden md:block">${p.status}</div>
                        <div class="text-2xl font-black ${statusColor} leading-none flex items-center">
                            ${p.news2}
                        </div>
                    </div>
                </div>
            </div>
        `;
    });

    DOM.patientsContainer.innerHTML = html;

    // Attach click events and render charts
    document.querySelectorAll('.patient-row').forEach(row => {
        row.addEventListener('click', () => {
            const id = row.getAttribute('data-id');
            const patient = patients.find(p => p.id === id);
            openDrawer(patient);
        });
        
        const id = row.getAttribute('data-id');
        const patient = patients.find(p => p.id === id);
        renderSparkline(`sparkline-${id}`, patient);
    });
}

function renderSparkline(canvasId, patient) {
    const canvas = document.getElementById(canvasId);
    if(!canvas) return;

    if (chartInstances[canvasId]) {
        chartInstances[canvasId].destroy();
    }

    // Map news2 score trend if available in trajectory, else use heart_rate as proxy for movement
    // Since trajectory only has HR/RR/SPO2 etc, we just plot HR for visual effect, like Recharts did
    const data = patient.trajectory.map(t => t.hr);
    
    let color = '#10b981';
    let gradientStart = 'rgba(16,185,129,0.2)';
    if (patient.status === 'critical') { color = '#ef4444'; gradientStart = 'rgba(239,68,68,0.2)'; }
    else if (patient.status === 'warning') { color = '#facc15'; gradientStart = 'rgba(234,179,8,0.2)'; }

    const ctx = canvas.getContext('2d');
    let gradient = ctx.createLinearGradient(0, 0, 0, 40);
    gradient.addColorStop(0, gradientStart);
    gradient.addColorStop(1, 'rgba(0,0,0,0)');

    chartInstances[canvasId] = new Chart(canvas, {
        type: 'line',
        data: {
            labels: patient.trajectory.map(t => t.time),
            datasets: [{
                data: data,
                borderColor: color,
                borderWidth: 2,
                backgroundColor: gradient,
                fill: true,
                pointRadius: 0,
                tension: 0.4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            scales: { x: { display: false }, y: { display: false, min: Math.min(...data) - 10, max: Math.max(...data) + 10 } },
            animation: false
        }
    });
}

function openDrawer(patient) {
    let statusColor = 'text-[#10b981]';
    let alertBg = 'bg-[#10b981]/20';
    let alertBorder = 'border-[#10b981]';
    
    if (patient.status === 'critical') {
        statusColor = 'text-[#ef4444]'; alertBg = 'bg-[#ef4444]/20'; alertBorder = 'border-[#ef4444]';
    } else if (patient.status === 'warning') {
        statusColor = 'text-yellow-400'; alertBg = 'bg-yellow-400/20'; alertBorder = 'border-yellow-400';
    }

    let drugAlertsHtml = '';
    if (patient.drugLabAlerts && patient.drugLabAlerts.length > 0) {
        drugAlertsHtml = `
            <div class="bg-[#ef4444]/10 rounded-lg p-3 border border-[#ef4444]/30 mb-3">
                <p class="text-[10px] font-bold text-[#ef4444] uppercase tracking-wider mb-1 flex items-center">
                    <i data-lucide="shield-alert" class="w-3 h-3 mr-1"></i> Medication Alert
                </p>
                ${patient.drugLabAlerts.map(a => `
                    <div class="mb-2 last:mb-0">
                        <p class="text-xs text-white font-bold">${a.rule_name}</p>
                        <p class="text-[11px] text-slate-300 leading-snug mt-0.5">${a.message}</p>
                    </div>
                `).join('')}
            </div>
        `;
    }

    let factorsHtml = '';
    patient.newsFactors.forEach(f => {
        factorsHtml += `
            <div class="flex justify-between items-center bg-slate-800/50 p-2 rounded border border-slate-700/50">
                <span class="text-xs text-slate-300 font-medium">${f.name}</span>
                <span class="text-xs font-black text-white bg-slate-700 px-2 py-0.5 rounded">+${f.score}</span>
            </div>
        `;
    });

    DOM.drawer.innerHTML = `
        <div class="p-4 md:p-6 border-b border-slate-800 flex justify-between items-start bg-[#0b1120]">
            <div>
                <div class="flex items-center space-x-3 mb-1">
                    <h2 class="text-xl font-black text-white tracking-tight">${patient.name}</h2>
                    <span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider border bg-slate-800 border-slate-600 text-slate-300">
                        ${patient.bed}
                    </span>
                </div>
                <div class="text-xs font-medium text-slate-400 flex items-center">
                    ID: ${patient.id} <span class="mx-2">•</span> ${patient.age}y <span class="mx-2">•</span> ${patient.sex}
                </div>
            </div>
            <button id="close-drawer" class="p-2 bg-slate-800 hover:bg-slate-700 rounded-full text-slate-400 hover:text-white transition-colors">
                <i data-lucide="x" class="w-5 h-5"></i>
            </button>
        </div>

        <div class="flex-1 overflow-y-auto p-4 md:p-6 space-y-6">
            <!-- Alert Card -->
            <div class="${alertBg} border ${alertBorder} rounded-xl p-4 flex items-start space-x-4">
                <div class="p-2 bg-[#0b1120]/50 rounded-lg shrink-0 mt-1">
                    <i data-lucide="alert-triangle" class="w-6 h-6 ${statusColor}"></i>
                </div>
                <div>
                    <h3 class="font-bold text-white text-sm mb-1">${patient.status === 'critical' ? 'High Risk of Deterioration' : patient.status === 'warning' ? 'Early Signs of Instability' : 'Stable Condition'}</h3>
                    <p class="text-xs text-slate-300 leading-relaxed">${patient.mlExplanation}</p>
                    <div class="mt-3 inline-flex items-center space-x-1 text-[10px] font-bold uppercase tracking-wider text-white bg-[#0b1120]/50 px-3 py-1.5 rounded-lg border border-white/10">
                        <i data-lucide="zap" class="w-3.5 h-3.5 mr-1"></i> AI Risk Score: ${patient.mlRisk}%
                    </div>
                </div>
            </div>

            ${drugAlertsHtml}

            <!-- NEWS2 Breakdown -->
            <div>
                <div class="flex items-center justify-between mb-3">
                    <h3 class="text-sm font-bold text-slate-200 uppercase tracking-wider flex items-center">
                        <i data-lucide="activity" class="w-4 h-4 mr-2 text-blue-400"></i> NEWS2 Score Breakdown
                    </h3>
                    <div class="text-2xl font-black ${statusColor}">${patient.news2}</div>
                </div>
                <div class="space-y-2">
                    ${factorsHtml || '<div class="text-xs text-slate-500">No abnormal factors contributing to score.</div>'}
                </div>
            </div>

            <!-- Vitals Chart -->
            <div>
                <h3 class="text-sm font-bold text-slate-200 uppercase tracking-wider mb-3">24h Heart Rate Trend</h3>
                <div class="h-[200px] w-full bg-[#0b1120] rounded-xl border border-slate-800 p-2">
                    <canvas id="drawer-chart"></canvas>
                </div>
            </div>
        </div>
    `;

    createIcons({ icons, nameAttr: 'data-lucide' });
    document.getElementById('close-drawer').addEventListener('click', closeDrawer);
    DOM.drawer.classList.remove('translate-x-full');
    DOM.drawerOverlay.classList.remove('hidden');

    // Render big chart
    const canvas = document.getElementById('drawer-chart');
    if (chartInstances['drawer-chart']) { chartInstances['drawer-chart'].destroy(); }
    
    const ctx = canvas.getContext('2d');
    let gradient = ctx.createLinearGradient(0, 0, 0, 200);
    gradient.addColorStop(0, 'rgba(59,130,246,0.5)');
    gradient.addColorStop(1, 'rgba(0,0,0,0)');

    chartInstances['drawer-chart'] = new Chart(canvas, {
        type: 'line',
        data: {
            labels: patient.trajectory.map(t => t.time),
            datasets: [{
                label: 'Heart Rate',
                data: patient.trajectory.map(t => t.hr),
                borderColor: '#3b82f6',
                backgroundColor: gradient,
                fill: true,
                tension: 0.4,
                pointBackgroundColor: '#3b82f6',
                pointRadius: 3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: { grid: { color: '#1e293b' }, ticks: { color: '#64748b', font: { size: 10 } } },
                y: { grid: { color: '#1e293b' }, ticks: { color: '#64748b', font: { size: 10 } } }
            },
            plugins: { legend: { display: false } }
        }
    });
}

function closeDrawer() {
    DOM.drawer.classList.add('translate-x-full');
    DOM.drawerOverlay.classList.add('hidden');
}

// Start
init();
