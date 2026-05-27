import { useState, useEffect, useCallback } from 'react';
import { Search, ChevronDown, ChevronUp, Bell, User, X, Activity, AlertTriangle, Lightbulb, CheckSquare, Heart, Droplets, PhoneForwarded } from 'lucide-react';
import { AreaChart, Area, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid, Legend } from 'recharts';

export default function Dashboard() {
  const [patients, setPatients] = useState([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedPatient, setSelectedPatient] = useState(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [showAlertPanel, setShowAlertPanel] = useState(false);
  const [activeFilter, setActiveFilter] = useState('All');
  const [timeStr, setTimeStr] = useState('');
  const [expandedAlertId, setExpandedAlertId] = useState(null); // which alert card is expanded

  // Real-time clock
  useEffect(() => {
    const tick = () => {
      const d = new Date();
      setTimeStr(`${d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} / ${d.toLocaleDateString()}`);
    };
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, []);

  // Fetch data — extracted so we can call it on interval too
  const fetchData = useCallback(() => {
    fetch('http://localhost:8000/api/ward-data')
      .then(res => res.json())
      .then(data => setPatients(data.patients))
      .catch(err => console.error('Error fetching patient data:', err));
  }, []);

  // Initial fetch + 30-second auto-refresh
  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const getStatusStyles = (status) => {
    switch (status) {
      case 'critical':
        return {
          rowBg: '',
          rowStyle: {},  // animation (row-critical-blink) handles the background + glow
          border: 'border border-[#ef4444]',
          solidBg: 'bg-[#ef4444]',
          text: 'text-[#ef4444]',
          hex: '#ef4444',
          glow: '',  // glow handled by animation
          separator: 'bg-[#ef4444]/40',
        };
      case 'warning':
        return {
          rowBg: '',
          rowStyle: { backgroundColor: 'rgba(245,158,11,0.10)' },
          border: 'border border-[#f59e0b]',
          solidBg: 'bg-[#f59e0b]',
          text: 'text-[#f59e0b]',
          hex: '#f59e0b',
          glow: '',
          separator: 'bg-[#f59e0b]/40',
        };
      case 'stable':
        return {
          rowBg: '',
          rowStyle: { backgroundColor: 'rgba(132,204,22,0.08)' },
          border: 'border border-[#84cc16]/60',
          solidBg: 'bg-[#84cc16]',
          text: 'text-[#84cc16]',
          hex: '#84cc16',
          glow: '',
          separator: 'bg-[#84cc16]/40',
        };
      default:
        return {
          rowBg: 'bg-slate-800',
          rowStyle: {},
          border: 'border border-slate-600',
          solidBg: 'bg-slate-600',
          text: 'text-slate-400',
          hex: '#94a3b8',
          glow: '',
          separator: 'bg-slate-600/40',
        };
    }
  };

  const getNEWSLabel = (score) => {
    if (score >= 7) return { text: 'HIGH RISK', color: 'bg-[#ef4444] text-white' };
    if (score >= 5) return { text: 'MEDIUM RISK', color: 'bg-[#f59e0b] text-black' };
    return { text: 'LOW RISK', color: 'bg-[#84cc16] text-black' };
  };

  const handlePatientClick = (patient) => {
    setSelectedPatient(patient);
    setIsDrawerOpen(true);
    setShowAlertPanel(false);
  };

  const filteredPatients = patients.filter(p => {
    const matchesSearch =
      p.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      p.id.toLowerCase().includes(searchTerm.toLowerCase());
    if (!matchesSearch) return false;
    if (activeFilter === 'All') return true;
    return p.status.toLowerCase() === activeFilter.toLowerCase();
  });

  const sortedPatients = [...filteredPatients].sort((a, b) => {
    const order = { critical: 3, warning: 2, stable: 1 };
    return order[b.status] - order[a.status];
  });

  const criticalPatients = patients.filter(p => p.status === 'critical');
  const warningPatients = patients.filter(p => p.status === 'warning');
  const stablePatients = patients.filter(p => p.status === 'stable');

  // Column layout constants (must match between header and rows exactly)
  const COL_BED = 'w-[60px] shrink-0';
  const COL_PATIENT = 'w-[150px] shrink-0';
  const COL_COMPLAINT = 'w-[120px] shrink-0';
  const COL_VITALS = 'flex-1'; // takes all remaining space
  const COL_SCORE = 'w-[130px] shrink-0';

  return (
    <div className="flex flex-col h-screen bg-[#0b1120] text-slate-300 font-sans overflow-hidden">

      {/* ══════════════════════════════════════════════════════
          TOP NAVIGATION BAR
      ══════════════════════════════════════════════════════ */}
      <header className="h-14 flex items-center justify-between px-6 bg-[#0f172a] border-b border-slate-800 shrink-0 relative z-20">
        <div className="flex items-center space-x-4">
          <div className="flex items-center space-x-2">
            <div className="w-7 h-7 rounded bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-[0_0_12px_rgba(59,130,246,0.5)]">
              <Activity className="text-white w-4 h-4" />
            </div>
            <h1 className="text-lg font-bold text-white tracking-wide">
              EarlyWarning<span className="text-blue-400 font-medium">AI</span>
            </h1>
          </div>
          <div className="h-5 w-px bg-slate-700" />
          <h2 className="text-slate-400 font-semibold tracking-wider text-xs flex items-center uppercase">
            Ward 4B — Acute Care / ICU
            <ChevronDown className="ml-1 w-3 h-3" />
          </h2>
        </div>

        <div className="flex items-center space-x-5">
          <span className="text-slate-400 text-xs hidden lg:block pr-5 border-r border-slate-700">
            Time: {timeStr}
          </span>

          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              placeholder="Search patients..."
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
              className="pl-9 pr-4 py-1.5 bg-slate-800/50 border border-slate-700 rounded-full text-xs focus:outline-none focus:border-blue-500 transition-all w-52 text-white placeholder-slate-500"
            />
          </div>

          <button
            onClick={() => { setShowAlertPanel(!showAlertPanel); setIsDrawerOpen(false); }}
            className="relative p-2 hover:bg-slate-800 rounded-full transition-colors"
          >
            {/* Big bell with pulsing glow when alerts exist */}
            <Bell className={`w-6 h-6 ${criticalPatients.length > 0 ? 'text-[#ef4444]' : 'text-slate-400'} ${criticalPatients.length > 0 ? 'drop-shadow-[0_0_6px_rgba(239,68,68,0.8)]' : ''}`} />
            {criticalPatients.length > 0 && (
              <>
                {/* Count badge */}
                <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] bg-[#ef4444] text-white text-[10px] font-black rounded-full flex items-center justify-center px-1 shadow-lg">
                  {criticalPatients.length}
                </span>
                {/* Ping animation ring */}
                <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] bg-[#ef4444] rounded-full animate-ping opacity-60" />
              </>
            )}
          </button>

          <div className="flex items-center space-x-2 pl-4 border-l border-slate-700">
            <div className="text-right hidden md:block">
              <p className="text-xs font-medium text-white">Sarah Jenkins, RN</p>
              <p className="text-[10px] text-slate-500">Charge Nurse</p>
            </div>
            <div className="w-8 h-8 rounded-full bg-blue-600/20 border border-blue-500/50 flex items-center justify-center">
              <User className="w-4 h-4 text-blue-400" />
            </div>
          </div>
        </div>
      </header>

      {/* ══════════════════════════════════════════════════════
          COMBINED STATS + FILTER BAR  (matches image 3)
      ══════════════════════════════════════════════════════ */}
      <div className="px-6 py-3 bg-[#0b1120] border-b border-slate-800 shrink-0">
        {/* Stats cards row */}
        <div className="flex items-center space-x-3 mb-3">
          {/* Total */}
          <button
            onClick={() => setActiveFilter('All')}
            className={`flex items-center space-x-3 px-4 py-2.5 rounded-xl border transition-all ${activeFilter === 'All'
              ? 'bg-blue-600/20 border-blue-500 shadow-[0_0_12px_rgba(59,130,246,0.3)]'
              : 'bg-[#0f172a] border-slate-700 hover:border-slate-600'
              }`}
          >
            <div className="p-1.5 bg-blue-500/20 rounded-lg"><User className="text-blue-400 w-5 h-5" /></div>
            <div className="text-left">
              <div className="text-2xl font-black text-white leading-none">{patients.length}</div>
              <div className="text-[10px] text-slate-400 uppercase font-bold tracking-wider mt-0.5">Total Patients</div>
            </div>
          </button>

          {/* Critical */}
          <button
            onClick={() => setActiveFilter('Critical')}
            className={`flex items-center space-x-3 px-4 py-2.5 rounded-xl border transition-all ${activeFilter === 'Critical'
              ? 'bg-[#ef4444]/20 border-[#ef4444] shadow-[0_0_12px_rgba(239,68,68,0.3)]'
              : 'bg-[#0f172a] border-slate-700 hover:border-slate-600'
              }`}
          >
            <div className="p-1.5 bg-[#ef4444]/20 rounded-lg"><AlertTriangle className="text-[#ef4444] w-5 h-5" /></div>
            <div className="text-left">
              <div className={`text-2xl font-black leading-none ${criticalPatients.length > 0 ? 'text-[#ef4444]' : 'text-white'}`}>{criticalPatients.length}</div>
              <div className="text-[10px] text-slate-400 uppercase font-bold tracking-wider mt-0.5">Critical</div>
            </div>
          </button>

          {/* Warning */}
          <button
            onClick={() => setActiveFilter('Warning')}
            className={`flex items-center space-x-3 px-4 py-2.5 rounded-xl border transition-all ${activeFilter === 'Warning'
              ? 'bg-[#f59e0b]/20 border-[#f59e0b]'
              : 'bg-[#0f172a] border-slate-700 hover:border-slate-600'
              }`}
          >
            <div className="p-1.5 bg-[#f59e0b]/20 rounded-lg"><Activity className="text-[#f59e0b] w-5 h-5" /></div>
            <div className="text-left">
              <div className={`text-2xl font-black leading-none ${activeFilter === 'Warning' ? 'text-[#f59e0b]' : 'text-white'}`}>{warningPatients.length}</div>
              <div className="text-[10px] text-slate-400 uppercase font-bold tracking-wider mt-0.5">Warning</div>
            </div>
          </button>

          {/* Stable */}
          <button
            onClick={() => setActiveFilter('Stable')}
            className={`flex items-center space-x-3 px-4 py-2.5 rounded-xl border transition-all ${activeFilter === 'Stable'
              ? 'bg-[#84cc16]/20 border-[#84cc16]'
              : 'bg-[#0f172a] border-slate-700 hover:border-slate-600'
              }`}
          >
            <div className="p-1.5 bg-[#84cc16]/20 rounded-lg"><CheckSquare className="text-[#84cc16] w-5 h-5" /></div>
            <div className="text-left">
              <div className={`text-2xl font-black leading-none ${activeFilter === 'Stable' ? 'text-[#84cc16]' : 'text-white'}`}>{stablePatients.length}</div>
              <div className="text-[10px] text-slate-400 uppercase font-bold tracking-wider mt-0.5">Stable</div>
            </div>
          </button>
        </div>

      </div>

      {/* ══════════════════════════════════════════════════════
          MAIN CONTENT AREA
      ══════════════════════════════════════════════════════ */}
      <div className="flex-1 flex overflow-hidden relative">

        {/* ── TABLE ── */}
        <main className="flex-1 overflow-hidden flex flex-col">

          {/* ── COLUMN HEADER ── uses border-r on each col, exactly matching rows */}
          <div
            className="flex items-end shrink-0 bg-[#0b1120] border-b-2 border-slate-700 px-3"
            style={{ paddingTop: '6px', paddingBottom: '0px' }}
          >
            {/* Bed */}
            <div className={`${COL_BED} text-center border-r border-slate-700`}>
              <span className="text-[10px] font-bold text-white uppercase tracking-wider pb-1 block">Bed</span>
            </div>

            {/* Patient */}
            <div className={`${COL_PATIENT} px-3 border-r border-slate-700`}>
              <span className="text-[10px] font-bold text-white uppercase tracking-wider pb-1 block">Patient / MRN</span>
            </div>

            {/* Complaint */}
            <div className={`${COL_COMPLAINT} px-3 border-r border-slate-700`}>
              <span className="text-[10px] font-bold text-white uppercase tracking-wider pb-1 block">Chief Complaint</span>
            </div>

            {/* Vitals — with title + sub-labels */}
            <div className={`${COL_VITALS} flex flex-col px-1 border-r border-slate-700`}>
              <div className="text-[10px] font-bold text-white uppercase tracking-wider pb-0.5 text-center">
                Vital Signs Trajectories (Past 24 Hrs)
              </div>
              {/* Individual vital labels — white, centred above each sparkline */}
              <div className="flex w-full pb-1">
                {['HR', 'RR', 'SpO2', 'BP', 'Temp'].map((v, i) => (
                  <div key={v} className={`flex-1 text-center text-[10px] font-bold text-white uppercase ${i < 4 ? 'border-r border-slate-700/50' : ''}`}>
                    {v}
                  </div>
                ))}
              </div>
            </div>

            {/* Score */}
            <div className={`${COL_SCORE} text-center`}>
              <span className="text-[10px] font-bold text-white uppercase tracking-wider pb-1 block">Score</span>
            </div>
          </div>

          {/* ── ROWS ── separated, rounded, scrollbar hidden ── */}
          <div className="flex-1 overflow-y-auto no-scrollbar px-3 py-2 space-y-2" style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}>
            {sortedPatients.map((patient) => {
              const s = getStatusStyles(patient.status);
              return (
                <div
                  key={patient.id}
                  onClick={() => handlePatientClick(patient)}
                  className={`flex items-stretch cursor-pointer rounded-lg transition-all duration-150 hover:brightness-110 ${s.border} ${s.glow} ${patient.status === 'critical' ? 'row-critical-blink' : ''}`}
                  style={{ minHeight: '96px', ...s.rowStyle }}
                >
                  {/* Bed badge */}
                  <div className={`${COL_BED} flex items-center justify-center py-3 px-1 border-r border-slate-700/40`}>
                    <div className={`w-10 h-10 rounded-lg ${s.solidBg} flex items-center justify-center text-white font-black text-sm shadow`}>
                      {patient.bed}
                    </div>
                  </div>

                  {/* Patient info */}
                  <div className={`${COL_PATIENT} flex flex-col justify-center py-3 px-3 border-r border-slate-700/40`}>
                    <div className="font-bold text-white text-sm leading-tight truncate">{patient.name}</div>
                    <div className="text-[11px] text-slate-400 mt-0.5">{patient.id}</div>
                    <div className="text-[11px] text-slate-500">{patient.age}y {patient.sex}</div>
                  </div>

                  {/* Chief complaint */}
                  <div className={`${COL_COMPLAINT} flex items-center py-3 px-3 border-r border-slate-700/40`}>
                    <span className="text-[11px] text-slate-300 font-medium leading-snug line-clamp-3">
                      {patient.complaint}
                    </span>
                  </div>

                  {/* 5 Vitals sparklines — large value+unit, clear gap, tall plot filling from bottom */}
                  <div className={`${COL_VITALS} flex items-stretch py-1 px-1`}>
                    {[
                      { key: 'hr',   unit: 'bpm'  },
                      { key: 'rr',   unit: 'br/m' },
                      { key: 'spo2', unit: '%'    },
                      { key: 'sbp',  unit: 'mmHg' },
                      { key: 'temp', unit: '°C'   },
                    ].map(({ key, unit }, i) => {
                      const lastVal = patient.trajectory
                        ? [...patient.trajectory].reverse().find(t => t[key] != null)?.[key]
                        : null;
                      const displayVal = lastVal != null
                        ? (key === 'temp' ? lastVal.toFixed(1) : Math.round(lastVal))
                        : '—';
                      return (
                        <div
                          key={key}
                          className={`flex-1 flex flex-col pt-1 ${i < 4 ? 'border-r border-slate-700/40' : ''} px-1`}
                        >
                          {/* Numeric value + unit — large and clearly readable */}
                          <div className="text-center leading-none mb-1.5">
                            <span className="text-sm font-black text-white">{displayVal}</span>
                            <span className="text-[10px] font-bold text-slate-400 ml-0.5">{unit}</span>
                          </div>
                          {/* Sparkline — fills remaining height, anchored to bottom */}
                          <div style={{ flex: 1, minHeight: 0 }}>
                            <ResponsiveContainer width="100%" height="100%">
                              <AreaChart
                                data={patient.trajectory}
                                margin={{ top: 4, right: 2, bottom: 0, left: 2 }}
                              >
                                <YAxis domain={['dataMin', 'auto']} hide />
                                <Area
                                  type="monotone"
                                  dataKey={key}
                                  stroke={s.hex}
                                  strokeWidth={2}
                                  fill={s.hex}
                                  fillOpacity={0.22}
                                  isAnimationActive={false}
                                  dot={false}
                                  baseValue="dataMin"
                                />
                              </AreaChart>
                            </ResponsiveContainer>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {/* NEWS2 + ML Score — boxed, prominent */}
                  <div className={`${COL_SCORE} flex items-center justify-center gap-2 border-l border-slate-700/40 px-2 py-3`}>
                    <div className={`flex flex-col items-center justify-center rounded-lg border px-2 py-1.5 min-w-[38px] ${s.border} bg-slate-900/60`}>
                      <span className={`text-[8px] font-black uppercase tracking-wider ${s.text}`}>NEWS2</span>
                      <span className="text-2xl font-black text-white leading-none mt-0.5">{patient.news2}</span>
                    </div>
                    <div className={`flex flex-col items-center justify-center rounded-lg border px-2 py-1.5 min-w-[38px] ${s.border} bg-slate-900/60`}>
                      <span className={`text-[8px] font-black uppercase tracking-wider ${s.text}`}>ML</span>
                      <span className="text-2xl font-black text-white leading-none mt-0.5">{patient.mlRisk}</span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </main>

        {/* ── OVERLAY to close drawers on outside click — fixed, covers full page ── */}
        {(isDrawerOpen || showAlertPanel) && (
          <div
            className="fixed inset-0 bg-black/40 z-40"
            onClick={() => { setIsDrawerOpen(false); setShowAlertPanel(false); }}
          />
        )}

        {/* ══════════════════════════════════════════════════════
            ALERT SIDEBAR — fixed from page top
        ══════════════════════════════════════════════════════ */}
        <aside
          className={`fixed inset-y-0 right-0 w-96 bg-[#0f172a] border-l border-slate-800 shadow-2xl transform transition-transform duration-300 ease-in-out z-50 flex flex-col ${showAlertPanel ? 'translate-x-0' : 'translate-x-full'}`}
        >
          <div className="p-4 border-b border-slate-800 flex justify-between items-center sticky top-0 bg-[#0b1120] z-10">
            <div className="flex items-center space-x-2">
              <AlertTriangle className="w-5 h-5 text-[#ef4444]" />
              <h2 className="text-base font-bold text-white">Active Alerts</h2>
              {criticalPatients.length > 0 && (
                <span className="bg-[#ef4444] text-white text-xs font-bold px-2 py-0.5 rounded-full">
                  {criticalPatients.length}
                </span>
              )}
            </div>
            <button onClick={() => setShowAlertPanel(false)} className="p-1 hover:bg-slate-800 rounded-full">
              <X className="w-4 h-4 text-slate-400" />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-4 space-y-3">
            {criticalPatients.length === 0 ? (
              <div className="text-center text-slate-500 py-8 text-sm">No active critical alerts.</div>
            ) : (
              criticalPatients.map(patient => {
                const isExpanded = expandedAlertId === patient.id;
                return (
                  <div key={`alert-${patient.id}`} className="rounded-xl border-l-4 border-[#ef4444] shadow-lg overflow-hidden">

                    {/* Collapsed header — always visible, tap to expand */}
                    <div
                      onClick={() => setExpandedAlertId(isExpanded ? null : patient.id)}
                      className="flex justify-between items-center bg-slate-800 hover:bg-slate-750 px-4 py-3 cursor-pointer transition-colors"
                    >
                      <div>
                        <h3 className="font-bold text-white text-sm">{patient.name}</h3>
                        <p className="text-xs text-slate-400">Bed {patient.bed} • NEWS2: {patient.news2}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="bg-[#ef4444] text-white text-[9px] font-black px-2 py-0.5 rounded animate-pulse">CRITICAL</span>
                        {isExpanded
                          ? <ChevronUp className="w-4 h-4 text-slate-400" />
                          : <ChevronDown className="w-4 h-4 text-slate-400" />}
                      </div>
                    </div>

                    {/* Expanded details — shown only when this card is expanded */}
                    {isExpanded && (
                      <div className="bg-slate-900 px-4 pt-3 pb-4 space-y-3">

                        {/* Reason for Flag */}
                        <div className="bg-slate-800 rounded-lg p-3 border border-slate-700">
                          <p className="text-[10px] font-bold text-[#ef4444] uppercase tracking-wider mb-1">Reason for Flag</p>
                          <p className="text-xs text-slate-300 leading-relaxed">
                            {patient.mlExplanation || 'Critical deterioration detected by ML monitoring.'}
                          </p>
                        </div>

                        {/* Immediate Action */}
                        <div className="bg-slate-800 rounded-lg p-3 border border-slate-700">
                          <p className="text-[10px] font-bold text-yellow-400 uppercase tracking-wider mb-1">Immediate Action</p>
                          <p className="text-xs text-slate-300 leading-relaxed">
                            {patient.recommendedAction || 'Bedside assessment required immediately.'}
                          </p>
                        </div>

                        {/* Action buttons */}
                        <div className="flex gap-2">
                          <button
                            onClick={e => { e.stopPropagation(); handlePatientClick(patient); }}
                            className="flex-1 bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold py-2 rounded-lg transition-colors"
                          >
                            View Patient Chart
                          </button>
                          <button
                            onClick={e => e.stopPropagation()}
                            className="flex-1 bg-[#ef4444] hover:bg-red-600 text-white text-xs font-bold py-2 rounded-lg flex justify-center items-center transition-colors shadow-[0_0_8px_rgba(239,68,68,0.4)]"
                          >
                            <PhoneForwarded className="w-3 h-3 mr-1" /> Escalate
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>
        </aside>

        {/* ══════════════════════════════════════════════════════
            PATIENT DETAIL DRAWER — fixed from page top, 75% width
        ══════════════════════════════════════════════════════ */}
        <aside
          className={`fixed inset-y-0 right-0 w-3/4 bg-[#0b1120] border-l border-slate-700 shadow-[0_0_50px_rgba(0,0,0,0.6)] transform transition-transform duration-500 ease-in-out z-60 flex flex-col ${isDrawerOpen ? 'translate-x-0' : 'translate-x-full'}`}
          style={{ zIndex: 60 }}
        >
          {selectedPatient && (() => {
            const ds = getStatusStyles(selectedPatient.status);
            return (
              <>
                {/* Drawer Header */}
                <div className="h-[72px] px-8 border-b border-slate-800 flex justify-between items-center bg-[#0f172a] shrink-0">
                  <div className="flex items-center space-x-4">
                    <div className={`w-12 h-12 rounded-xl flex items-center justify-center text-xl font-black text-white ${ds.solidBg} shadow-lg`}>
                      {selectedPatient.bed}
                    </div>
                    <div>
                      <h2 className="text-xl font-black text-white">{selectedPatient.name}</h2>
                      <p className="text-xs text-slate-400">
                        {selectedPatient.id} • {selectedPatient.age} yrs • {selectedPatient.sex} • Admitted: {selectedPatient.admitted}
                      </p>
                    </div>
                  </div>
                  <button onClick={() => setIsDrawerOpen(false)} className="p-2 hover:bg-slate-800 rounded-full">
                    <X className="w-5 h-5 text-slate-400" />
                  </button>
                </div>

                {/* Drawer Scrollable Content */}
                <div className="flex-1 overflow-y-auto p-6 space-y-6 bg-[#0b1120]">

                  {/* Deterioration Alert — side by side */}
                  {(selectedPatient.status === 'critical' || selectedPatient.status === 'warning') && (
                    <div className={`border-l-4 rounded-r-xl p-5 flex flex-col lg:flex-row gap-5 ${selectedPatient.status === 'critical' ? 'border-[#ef4444] bg-[#ef4444]/10' : 'border-[#f59e0b] bg-[#f59e0b]/10'}`}>

                      {/* LEFT — ML explanation + actions */}
                      <div className="flex-1 space-y-3">
                        <div className="flex items-center space-x-2 mb-1">
                          <AlertTriangle className={`w-5 h-5 ${selectedPatient.status === 'critical' ? 'text-[#ef4444]' : 'text-[#f59e0b]'}`} />
                          <h3 className={`text-lg font-bold ${selectedPatient.status === 'critical' ? 'text-[#ef4444]' : 'text-[#f59e0b]'}`}>
                            {selectedPatient.status === 'critical' ? 'Critical Deterioration Alert' : 'Warning: Early Deterioration Detected'}
                          </h3>
                        </div>

                        <div className="bg-slate-900/60 p-4 rounded-lg border border-slate-700">
                          <h4 className="text-xs font-bold text-slate-300 uppercase tracking-wider mb-2 flex items-center">
                            <Activity className="w-3.5 h-3.5 mr-1.5 text-blue-400" /> ML Risk Explanation
                          </h4>
                          <p className="text-sm text-white leading-relaxed">
                            {selectedPatient.mlExplanation || 'High risk of clinical deterioration based on vital sign trajectory.'}
                          </p>
                        </div>

                        <div className="bg-slate-900/60 p-4 rounded-lg border border-slate-700">
                          <h4 className="text-xs font-bold text-slate-300 uppercase tracking-wider mb-2 flex items-center">
                            <Lightbulb className="w-3.5 h-3.5 mr-1.5 text-yellow-400" /> Recommended Action
                          </h4>
                          <p className="text-sm text-white leading-relaxed">
                            {selectedPatient.recommendedAction || 'Immediate bedside assessment. Consider rapid response escalation.'}
                          </p>
                        </div>

                        <div className="flex space-x-3 pt-1">
                          <button className="bg-blue-600 hover:bg-blue-500 text-white font-bold py-2.5 px-5 rounded-lg flex items-center text-sm transition-colors">
                            <CheckSquare className="w-4 h-4 mr-2" /> Acknowledge
                          </button>
                          {selectedPatient.status === 'critical' && (
                            <button className="bg-[#ef4444] hover:bg-red-600 text-white font-bold py-2.5 px-5 rounded-lg flex items-center text-sm transition-colors shadow-[0_0_12px_rgba(239,68,68,0.4)]">
                              <PhoneForwarded className="w-4 h-4 mr-2" /> Escalate to RRT
                            </button>
                          )}
                        </div>
                      </div>

                      {/* RIGHT — NEWS2 score breakdown */}
                      <div className="w-[280px] shrink-0 bg-slate-900/60 rounded-xl p-5 border border-slate-800 flex flex-col">
                        <p className="text-[10px] text-slate-400 font-bold uppercase tracking-wider mb-3">Current NEWS2 Score</p>
                        <div className="flex items-center justify-between mb-4 pb-4 border-b border-slate-700">
                          <span className="text-5xl font-black text-white">{selectedPatient.news2}</span>
                          <span className={`px-3 py-1.5 rounded-lg font-bold text-xs ${getNEWSLabel(selectedPatient.news2).color}`}>
                            {getNEWSLabel(selectedPatient.news2).text}
                          </span>
                        </div>
                        <p className="text-sm font-bold text-white mb-2">Score Factors</p>
                        <div className="space-y-2 flex-1">
                          {selectedPatient.newsFactors?.map((f, i) => (
                            <div key={i} className="flex justify-between items-center bg-slate-800 rounded px-3 py-1.5">
                              <span className="text-slate-400 text-xs">{f.name}</span>
                              <span className={`text-white text-xs font-bold px-2 py-0.5 rounded ${f.score >= 3 ? 'bg-[#ef4444]' : f.score > 0 ? 'bg-[#f59e0b] text-black' : 'bg-slate-700'}`}>
                                {f.score}
                              </span>
                            </div>
                          ))}
                          {(!selectedPatient.newsFactors || selectedPatient.newsFactors.length === 0) && (
                            <p className="text-slate-500 text-xs italic">All factors normal</p>
                          )}
                        </div>
                      </div>
                    </div>
                  )}

                  {/* 24-Hour Vitals Graph */}
                  <div>
                    <h3 className="text-base font-bold text-white mb-3 flex items-center">
                      <Activity className="w-4 h-4 mr-2 text-blue-400" /> 24-Hour Vitals Trajectory
                    </h3>
                    <div className="h-72 bg-[#0f172a] rounded-xl p-4 border border-slate-800">
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={selectedPatient.trajectory} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                          <defs>
                            <linearGradient id="gHR" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#ef4444" stopOpacity={0.5} /><stop offset="95%" stopColor="#ef4444" stopOpacity={0} /></linearGradient>
                            <linearGradient id="gRR" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#f59e0b" stopOpacity={0.5} /><stop offset="95%" stopColor="#f59e0b" stopOpacity={0} /></linearGradient>
                            <linearGradient id="gSpO2" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#10b981" stopOpacity={0.5} /><stop offset="95%" stopColor="#10b981" stopOpacity={0} /></linearGradient>
                            <linearGradient id="gBP" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#3b82f6" stopOpacity={0.5} /><stop offset="95%" stopColor="#3b82f6" stopOpacity={0} /></linearGradient>
                            <linearGradient id="gTemp" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#a855f7" stopOpacity={0.5} /><stop offset="95%" stopColor="#a855f7" stopOpacity={0} /></linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                          <XAxis dataKey="time" stroke="#64748b" tick={{ fontSize: 10 }} />
                          <YAxis yAxisId="l" stroke="#64748b" tick={{ fontSize: 10 }} />
                          <YAxis yAxisId="r" orientation="right" stroke="#64748b" tick={{ fontSize: 10 }} />
                          <Tooltip
                            contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#f1f5f9', fontSize: 12 }}
                          />
                          <Legend verticalAlign="top" height={30} iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11 }} />
                          <Area yAxisId="l" type="monotone" dataKey="hr" name="HR" stroke="#ef4444" fill="url(#gHR)" strokeWidth={2.5} dot={false} />
                          <Area yAxisId="l" type="monotone" dataKey="rr" name="RR" stroke="#f59e0b" fill="url(#gRR)" strokeWidth={2.5} dot={false} />
                          <Area yAxisId="r" type="monotone" dataKey="spo2" name="SpO2" stroke="#10b981" fill="url(#gSpO2)" strokeWidth={2.5} dot={false} />
                          <Area yAxisId="l" type="monotone" dataKey="sbp" name="BP" stroke="#3b82f6" fill="url(#gBP)" strokeWidth={2.5} dot={false} />
                          <Area yAxisId="l" type="monotone" dataKey="temp" name="Temp" stroke="#a855f7" fill="url(#gTemp)" strokeWidth={2.5} dot={false} />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                  </div>

                  {/* Recent Vitals + Labs tables */}
                  <div className="grid grid-cols-2 gap-5">
                    {/* Vitals table */}
                    <div className="bg-[#0f172a] rounded-xl border border-slate-800 overflow-hidden">
                      <div className="p-3 border-b border-slate-800 bg-slate-800/40 flex items-center">
                        <Heart className="w-4 h-4 text-slate-300 mr-2" />
                        <h3 className="text-sm font-bold text-white">Recent Vitals</h3>
                      </div>
                      <table className="w-full text-left">
                        <thead>
                          <tr className="border-b border-slate-800">
                            {['Time', 'HR', 'RR', 'SpO2', 'BP', 'Temp'].map(h => (
                              <th key={h} className="px-3 py-2 text-[10px] font-bold text-slate-400 uppercase">{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {selectedPatient.recentVitals?.map((v, i) => (
                            <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                              <td className="px-3 py-2 text-xs text-slate-400">{v.time}</td>
                              <td className="px-3 py-2 text-xs font-medium text-white">{v.hr}</td>
                              <td className="px-3 py-2 text-xs font-medium text-white">{v.rr}</td>
                              <td className="px-3 py-2 text-xs font-medium text-white">{v.spo2}%</td>
                              <td className="px-3 py-2 text-xs text-slate-300">{v.sbp}/{v.dbp}</td>
                              <td className="px-3 py-2 text-xs font-medium text-white">{v.temp}°</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>

                    {/* Labs table */}
                    <div className="bg-[#0f172a] rounded-xl border border-slate-800 overflow-hidden">
                      <div className="p-3 border-b border-slate-800 bg-slate-800/40 flex items-center">
                        <Droplets className="w-4 h-4 text-slate-300 mr-2" />
                        <h3 className="text-sm font-bold text-white">Lab Results</h3>
                      </div>
                      <table className="w-full text-left">
                        <thead>
                          <tr className="border-b border-slate-800">
                            {['Time', 'Test', 'Value', 'Unit'].map(h => (
                              <th key={h} className="px-3 py-2 text-[10px] font-bold text-slate-400 uppercase">{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {selectedPatient.recentLabs?.map((lab, i) => (
                            <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                              <td className="px-3 py-2 text-xs text-slate-400">
                                {lab.time?.includes('T') ? lab.time.split('T').pop().substring(0, 5) : lab.time}
                              </td>
                              <td className="px-3 py-2 text-xs text-slate-300">{lab.test}</td>
                              <td className="px-3 py-2 text-xs font-bold text-white">{lab.value}</td>
                              <td className="px-3 py-2 text-xs text-slate-400">{lab.unit}</td>
                            </tr>
                          ))}
                          {(!selectedPatient.recentLabs || selectedPatient.recentLabs.length === 0) && (
                            <tr>
                              <td colSpan="4" className="px-3 py-4 text-center text-xs text-slate-500">No recent labs available.</td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>

                </div>
              </>
            );
          })()}
        </aside>

      </div>
    </div>
  );
}
