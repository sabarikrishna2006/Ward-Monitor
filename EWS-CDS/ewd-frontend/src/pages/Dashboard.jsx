import { useState, useEffect, useCallback } from 'react';
import { Search, ChevronDown, ChevronUp, Bell, User, X, Activity, AlertTriangle, Lightbulb, CheckSquare, Heart, Droplets, PhoneForwarded, PlayCircle, UserPlus, Plus, Shield, Settings2, TrendingUp, TrendingDown, Minus, Pill, Clock, BookOpen, FlaskConical } from 'lucide-react';
import { AreaChart, Area, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid, Legend, LineChart, Line, ReferenceLine } from 'recharts';
import { useNavigate } from 'react-router-dom';

// ── Disease presets for patient-specific rules ──
const DISEASE_PRESETS = {
  General: { label: 'General', criticalThreshold: 7, warningThreshold: 5, spo2Scale: 1, spo2AlertBelow: 91, note: 'Standard NHS NEWS2 thresholds.' },
  COPD:    { label: 'COPD', criticalThreshold: 7, warningThreshold: 4, spo2Scale: 2, spo2AlertBelow: 88, note: 'SpO2 Scale 2 (target 88-92%). Alert at NEWS2 ≥ 4 due to hypercapnic drive.' },
  CHF:     { label: 'CHF / Heart Failure', criticalThreshold: 6, warningThreshold: 4, spo2Scale: 1, spo2AlertBelow: 91, note: 'Lower thresholds due to baseline instability. HR <55 may be therapeutic on beta-blockers.' },
  CKD:     { label: 'CKD / Renal', criticalThreshold: 7, warningThreshold: 5, spo2Scale: 1, spo2AlertBelow: 91, note: 'Creatinine baseline elevated; potassium alert threshold lowered. Watch for AKI triggers.' },
  Sepsis:  { label: 'Sepsis / Infection', criticalThreshold: 5, warningThreshold: 3, spo2Scale: 1, spo2AlertBelow: 92, note: 'Early warning: NEWS2 ≥ 3 triggers assessment. Lactate > 1.5 mmol/L is early alert.' },
};

// ── Helper: compute approximate NEWS2 from a trajectory datapoint ──
function approximateNEWS2FromTrajectory(pt) {
  let s = 0;
  const rr = pt.rr;
  if (rr !== null && rr !== undefined) {
    if (rr <= 8 || rr >= 25) s += 3;
    else if (rr <= 11) s += 1;
    else if (rr >= 21) s += 2;
  }
  const spo2 = pt.spo2;
  if (spo2 !== null && spo2 !== undefined) {
    if (spo2 <= 91) s += 3;
    else if (spo2 <= 93) s += 2;
    else if (spo2 <= 95) s += 1;
  }
  const sbp = pt.sbp;
  if (sbp !== null && sbp !== undefined) {
    if (sbp <= 90) s += 3;
    else if (sbp <= 100) s += 2;
    else if (sbp <= 110) s += 1;
    else if (sbp >= 220) s += 3;
  }
  const hr = pt.hr;
  if (hr !== null && hr !== undefined) {
    if (hr <= 40 || hr > 130) s += 3;
    else if (hr <= 50 || (hr >= 111 && hr <= 130)) s += 1;
    else if (hr >= 91 && hr <= 110) s += 1;
  }
  const temp = pt.temp;
  if (temp !== null && temp !== undefined) {
    if (temp <= 35.0) s += 3;
    else if (temp <= 36.0) s += 1;
    else if (temp >= 38.1 && temp <= 39.0) s += 1;
    else if (temp > 39.0) s += 2;
  }
  return s;
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [patients, setPatients] = useState([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedPatient, setSelectedPatient] = useState(null);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [showAlertPanel, setShowAlertPanel] = useState(false);
  const [activeFilter, setActiveFilter] = useState('All');
  const [timeStr, setTimeStr] = useState('');
  const [expandedAlertId, setExpandedAlertId] = useState(null); // which alert card is expanded
  const [selectedWard, setSelectedWard] = useState('All');
  const [isReplay, setIsReplay] = useState(false);
  const [showAddPatient, setShowAddPatient] = useState(false);
  const [newPatient, setNewPatient] = useState({ hadm_id: '', age: 60, sex: 'M', ward: 'Ward 4B - Acute Care', room: '1', bed: '1', complaint: '', hr: 80, rr: 16, spo2: 98, sbp: 120, dbp: 80, temp: 37.0, air_or_oxygen: 'Air', consciousness: 'A', hypercapnic_failure: 0 });
  const [isLightMode, setIsLightMode] = useState(() => document.documentElement.classList.contains('light'));
  // ── New feature states ──
  const [acknowledgedAlerts, setAcknowledgedAlerts] = useState({}); // { patientId: timestamp }
  const [escalatedAlerts, setEscalatedAlerts] = useState({}); // { patientId: timestamp }
  const [showEscalateModal, setShowEscalateModal] = useState(false);
  const [showPatientRules, setShowPatientRules] = useState(false);
  const [patientRuleOverrides, setPatientRuleOverrides] = useState({}); // { patientId: { preset, criticalThreshold, warningThreshold, note, spo2Scale } }

  // Sync with global theme (controlled from Settings or Login)
  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsLightMode(document.documentElement.classList.contains('light'));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

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
    const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
    fetch(`${API_URL}/api/ward-data?ward=${selectedWard}&replay=${isReplay}`)
      .then(res => res.json())
      .then(data => setPatients(data.patients))
      .catch(err => console.error('Error fetching patient data:', err));
  }, [selectedWard, isReplay]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const getStatusStyles = (status) => {
    switch (status) {
      case 'critical':
        return {
          rowBg: 'bg-[#ef4444]/15',
          rowStyle: {},
          border: 'border border-[#ef4444]',
          solidBg: 'bg-[#ef4444]',
          text: 'text-[#ef4444]',
          hex: '#ef4444',
          glow: '',
          separator: 'bg-[#ef4444]/40',
          lRowBg: 'bg-white',
          lBorder: 'border-l-4 border border-red-100 border-l-[#dc2626]',
          lShadow: 'shadow-[2px_0_0_0_#dc2626_inset]',
          lHex: '#b91c1c', // Richer red for light mode sparklines
          lVitalsBg: 'bg-red-50/50',
        };
      case 'warning':
        return {
          rowBg: 'bg-[#f59e0b]/15',
          rowStyle: {},
          border: 'border border-[#f59e0b]',
          solidBg: 'bg-[#f59e0b]',
          text: 'text-[#f59e0b]',
          hex: '#f59e0b',
          glow: '',
          separator: 'bg-[#f59e0b]/40',
          lRowBg: 'bg-white',
          lBorder: 'border-l-4 border border-amber-100 border-l-[#d97706]',
          lShadow: '',
          lHex: '#b45309', // Richer amber for light mode
          lVitalsBg: 'bg-amber-50/50',
        };
      case 'stable':
        return {
          rowBg: 'bg-[#84cc16]/10',
          rowStyle: {},
          border: 'border border-[#84cc16]/60',
          solidBg: 'bg-[#84cc16]',
          text: 'text-[#84cc16]',
          hex: '#84cc16',
          glow: '',
          separator: 'bg-[#84cc16]/40',
          lRowBg: 'bg-white',
          lBorder: 'border-l-4 border border-green-100 border-l-[#16a34a]',
          lShadow: '',
          lHex: '#15803d', // Richer green for light mode
          lVitalsBg: 'bg-green-50/50',
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
          lRowBg: 'bg-white',
          lBorder: 'border-l-4 border border-slate-200 border-l-slate-400',
          lShadow: '',
          lHex: '#64748b',
          lVitalsBg: 'bg-slate-50/50',
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
      (p.id || '').toLowerCase().includes(searchTerm.toLowerCase()) ||
      (p.hadm_id || '').toString().toLowerCase().includes(searchTerm.toLowerCase());
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
  const COL_BED       = 'w-[60px] shrink-0';
  const COL_PATIENT   = 'w-[140px] shrink-0';
  const COL_SCORE     = 'w-[140px] shrink-0';
  const COL_COMPLAINT = 'w-[180px] lg:w-[220px] shrink-0';
  const COL_VITALS    = 'flex-1';

  // ── Theme tokens — inline, no separate component ──
  const L = isLightMode;
  const th = {
    pageBg:       L ? 'bg-white'            : 'bg-[#0b1120]',
    headerBg:     L ? 'bg-[#800080]'        : 'bg-[#0f172a]',
    headerBorder: L ? 'border-[#6b0070]'    : 'border-slate-800',
    headerText:   L ? 'text-white'          : 'text-slate-300',
    headerSub:    L ? 'text-white/70'       : 'text-slate-400',
    logoAccent:   L ? '#ffffff'             : '#d8b4fe',
    statsBg:      L ? 'bg-[#f5f0ff]'        : 'bg-[#0b1120]',
    statsBorder:  L ? 'border-[#e9d5ff]'    : 'border-slate-800',
    statCard:     L ? 'bg-white border-[#e9d5ff] hover:border-[#800080]/50' : 'bg-[#0f172a] border-slate-700 hover:border-slate-600',
    statCardActive: L ? 'bg-[#f5f0ff] border-[#800080] shadow-[0_0_12px_rgba(128,0,128,0.2)]' : '',
    statText:     L ? 'text-slate-800'      : 'text-white',
    statSubText:  L ? 'text-slate-500'      : 'text-slate-400',
    inputBg:      L ? 'bg-white border-[#e2d4f0] text-slate-900 placeholder-slate-400' : 'bg-slate-800/50 border-slate-700 text-white placeholder-slate-500',
    inputFocus:   L ? 'focus:border-[#800080]' : 'focus:border-[#800080]',
    btnGhost:     L ? 'bg-white border-[#e2d4f0] text-slate-700 hover:bg-slate-50' : 'bg-slate-800/50 border-slate-700 text-slate-400 hover:text-white',
    divider:      L ? 'border-[#e9d5ff]'    : 'border-slate-800',
    legendBg:     L ? 'bg-[#f5f0ff]'        : 'bg-[#0b1120]',
    legendText:   L ? 'text-slate-600'      : 'text-slate-200',
    legendLabel:  L ? 'text-slate-500 font-bold' : 'text-slate-400',
    tableHdrBg:   L ? 'bg-[#800080]'        : 'bg-[#0b1120]',
    tableHdrText: L ? 'text-white'          : 'text-white',
    tableHdrBorder: L ? 'border-[#6b0070]/40' : 'border-slate-700',
    rowBorder:    L ? 'border-white/20'     : 'border-slate-700/40',
    rowText:      L ? 'text-slate-800'      : 'text-white',
    rowSubText:   L ? 'text-slate-500'      : 'text-slate-400',
    complaintText: L ? 'text-slate-700'     : 'text-slate-200',
    vitalVal:     L ? 'text-slate-800'      : 'text-white',
    vitalUnit:    L ? 'text-slate-500'      : 'text-slate-400',
    scoreCard:    L ? 'bg-white border-[#800080]/30' : 'bg-slate-900/60',
    alertBg:      L ? 'bg-white'            : 'bg-[#0f172a]',
    alertBorder:  L ? 'border-[#e9d5ff]'    : 'border-slate-800',
    alertHdr:     L ? 'bg-[#f5f0ff]'        : 'bg-[#0b1120]',
    alertCardBg:  L ? 'bg-white'            : 'bg-slate-800',
    alertCardHover: L ? 'hover:bg-slate-50' : 'hover:bg-slate-750',
    alertDetailBg: L ? 'bg-[#fafafa]'       : 'bg-slate-900',
    alertSubBg:   L ? 'bg-[#f5f0ff]'        : 'bg-slate-800',
    alertSubBorder: L ? 'border-[#e9d5ff]'  : 'border-slate-700',
    alertSubText: L ? 'text-slate-700'      : 'text-slate-300',
    drawerBg:     L ? 'bg-white'            : 'bg-[#0b1120]',
    drawerHdrBg:  L ? 'bg-[#800080]'        : 'bg-[#0f172a]',
    drawerHdrBorder: L ? 'border-[#6b0070]' : 'border-slate-800',
    drawerHdrText: L ? 'text-white'         : 'text-white',
    drawerSubText: L ? 'text-white/70'      : 'text-slate-400',
    drawerCard:   L ? 'bg-[#f5f0ff] border-[#e9d5ff]' : 'bg-slate-900/60 border-slate-700',
    drawerTable:  L ? 'bg-white border-[#e9d5ff]' : 'bg-[#0f172a] border-slate-800',
    drawerTableHdr: L ? 'bg-[#f5f0ff]'     : 'bg-slate-800/40',
    drawerTH:     L ? 'text-slate-500'      : 'text-slate-400',
    drawerTD:     L ? 'text-slate-800'      : 'text-white',
    drawerTDMuted: L ? 'text-slate-500'     : 'text-slate-400',
    drawerRowHov: L ? 'hover:bg-[#f5f0ff]' : 'hover:bg-slate-800/30',
    drawerDivide: L ? 'divide-[#e9d5ff]'   : 'divide-slate-800/60',
    drawerMedBg:  L ? 'bg-white border-[#e9d5ff]' : 'bg-[#0f172a] border-slate-800',
    btnPrimary:   L ? 'bg-[#800080] hover:bg-[#6b0070] text-white' : 'bg-blue-600 hover:bg-blue-500 text-white',
    btnEscalate:  'bg-[#ef4444] hover:bg-red-600 text-white',
    userAvatar:   L ? 'bg-[#800080]/20 border-[#800080]/50' : 'bg-blue-600/20 border-blue-500/50',
    userAvatarIcon: L ? 'text-[#800080]'   : 'text-blue-400',
    userBorder:   L ? 'border-[#6b0070]'   : 'border-slate-700',
    modalBg:      L ? 'bg-white border-[#e9d5ff]'  : 'bg-[#0f172a] border-slate-700',
    modalHdrBg:   L ? 'bg-[#f5f0ff]'       : 'bg-[#0b1120]',
    modalInput:   L ? 'bg-white border-[#e9d5ff] text-slate-900' : 'bg-slate-800 border-slate-700 text-white',
    modalLabel:   L ? 'text-slate-600'      : 'text-slate-400',
    chartTooltipBg: L ? '#ffffff'           : '#0f172a',
    chartTooltipBorder: L ? '#e9d5ff'       : '#1e293b',
    chartGrid:    L ? '#e9d5ff'             : '#1e293b',
    chartAxis:    L ? '#94a3b8'             : '#64748b',
  };

  return (
    <div className={`flex flex-col h-screen ${th.pageBg} text-slate-300 font-sans overflow-hidden`}>

      {/* ══════════════════════════════════════════════════════
          TOP NAVIGATION BAR
      ══════════════════════════════════════════════════════ */}
      <header className={`h-14 flex items-center justify-between px-4 md:px-6 ${th.headerBg} border-b ${th.headerBorder} shrink-0 relative z-20`}>
        {/* Ward selector */}
        <div className="flex items-center">
          <div
            className="flex items-center rounded-lg px-3 py-1.5 cursor-pointer"
            style={{ backgroundColor: L ? 'rgba(255,255,255,0.12)' : 'rgba(255,255,255,0.05)', border: L ? '1px solid rgba(255,255,255,0.2)' : '1px solid rgba(255,255,255,0.08)' }}
          >
            <select
              value={selectedWard}
              onChange={(e) => setSelectedWard(e.target.value)}
              className="font-bold tracking-wider text-xs uppercase focus:outline-none cursor-pointer border-0 bg-transparent text-white"
              style={{ color: '#ffffff', backgroundColor: 'transparent' }}
            >
              <option value="All" style={{ backgroundColor: '#200427', color: '#fff' }}>ALL WARDS</option>
              <option value="Ward 4B - Acute Care" style={{ backgroundColor: '#200427', color: '#fff' }}>WARD 4B — ACUTE CARE / ICU</option>
              <option value="Ward 7A - Step Down" style={{ backgroundColor: '#200427', color: '#fff' }}>WARD 7A — STEP DOWN</option>
            </select>
            <ChevronDown className="ml-1 w-3 h-3 pointer-events-none text-white/70" />
          </div>
        </div>

        <div className="flex items-center space-x-2 md:space-x-3">
          <span className={`${th.headerSub} text-xs hidden xl:block pr-3 border-r ${L ? 'border-white/20' : 'border-slate-700'}`}>
            {timeStr}
          </span>

          <button
            onClick={() => setIsReplay(!isReplay)}
            className={`hidden sm:flex items-center space-x-1 px-2.5 py-1.5 rounded-full text-xs font-bold transition-colors border ${isReplay
              ? 'bg-blue-600/20 text-blue-400 border-blue-500/50'
              : L ? 'bg-white/10 text-white/70 border-white/20 hover:bg-white/20' : 'bg-slate-800/50 text-slate-400 border-slate-700 hover:text-white'}`}
          >
            <PlayCircle className={`w-3.5 h-3.5 ${isReplay ? 'animate-pulse' : ''}`} />
            <span className="hidden md:inline">{isReplay ? 'Replaying' : 'Replay'}</span>
          </button>

          <button
            onClick={() => setShowAddPatient(true)}
            className={`flex items-center space-x-1 px-2.5 py-1.5 rounded-full text-xs font-bold transition-colors border ${L ? 'bg-white/10 text-white/80 border-white/20 hover:bg-white/20' : 'bg-slate-800/50 text-slate-400 border-slate-700 hover:text-white'}`}
          >
            <UserPlus className="w-3.5 h-3.5" />
            <span className="hidden md:inline">Admit</span>
          </button>

          <div className="relative">
            <Search className={`w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 ${L ? 'text-white/50' : 'text-slate-500'}`} />
            <input
              type="text"
              placeholder="Search by Patient ID..."
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
              className={`pl-8 pr-3 py-1.5 border rounded-full text-xs focus:outline-none transition-all w-36 md:w-48 ${L ? 'bg-white/10 border-white/20 text-white placeholder-white/40 focus:bg-white/20' : 'bg-slate-800/50 border-slate-700 text-white placeholder-slate-500 focus:border-[#800080]'}`}
            />
          </div>

          <button
            onClick={() => { setShowAlertPanel(!showAlertPanel); setIsDrawerOpen(false); }}
            className={`relative p-2 rounded-full transition-colors ${L ? 'hover:bg-white/10' : 'hover:bg-slate-800'}`}
          >
            <Bell className={`w-5 h-5 ${criticalPatients.length > 0 ? 'text-[#ef4444]' : L ? 'text-white/70' : 'text-slate-400'} ${criticalPatients.length > 0 ? 'drop-shadow-[0_0_6px_rgba(239,68,68,0.8)]' : ''}`} />
            {criticalPatients.length > 0 && (
              <>
                <span className="absolute -top-1 -right-1 min-w-[16px] h-[16px] bg-[#ef4444] text-white text-[9px] font-black rounded-full flex items-center justify-center px-1 shadow-lg">
                  {criticalPatients.length}
                </span>
                <span className="absolute -top-1 -right-1 min-w-[16px] h-[16px] bg-[#ef4444] rounded-full animate-ping opacity-60" />
              </>
            )}
          </button>

          <div className={`flex items-center space-x-2 pl-2 md:pl-3 border-l ${L ? 'border-white/20' : 'border-slate-700'}`}>
            <div className="text-right hidden lg:block">
              <p className={`text-xs font-medium ${th.headerText}`}>Sabari</p>
              <p className={`text-[10px] ${th.headerSub}`}>Charge Nurse</p>
            </div>
            <div className={`w-7 h-7 rounded-full ${th.userAvatar} border flex items-center justify-center`}>
              <User className={`w-3.5 h-3.5 ${th.userAvatarIcon}`} />
            </div>
          </div>
        </div>
      </header>

      {/* ══════════════════════════════════════════════════════
          COMBINED STATS + FILTER BAR
      ══════════════════════════════════════════════════════ */}
      <div className={`px-6 py-3 ${th.statsBg} border-b ${th.statsBorder} shrink-0`}>
        <div className="flex items-center space-x-3 mb-3 flex-wrap gap-y-2">
          {/* Total */}
          <button
            onClick={() => setActiveFilter('All')}
            className={`flex items-center space-x-3 px-4 py-2.5 rounded-xl border transition-all ${activeFilter === 'All'
              ? (L ? `${th.statCardActive}` : 'bg-blue-600/20 border-blue-500 shadow-[0_0_12px_rgba(59,130,246,0.3)]')
              : th.statCard
              }`}
          >
            <div className={`p-1.5 rounded-lg ${L ? 'bg-[#800080]/10' : 'bg-blue-500/20'}`}><User className={`w-5 h-5 ${L ? 'text-[#800080]' : 'text-blue-400'}`} /></div>
            <div className="text-left">
              <div className={`text-2xl font-black leading-none ${th.statText}`}>{patients.length}</div>
              <div className={`text-[10px] uppercase font-bold tracking-wider mt-0.5 ${th.statSubText}`}>Total Patients</div>
            </div>
          </button>

          {/* Critical */}
          <button
            onClick={() => setActiveFilter('Critical')}
            className={`flex items-center space-x-3 px-4 py-2.5 rounded-xl border transition-all ${activeFilter === 'Critical'
              ? 'bg-[#ef4444]/20 border-[#ef4444] shadow-[0_0_12px_rgba(239,68,68,0.3)]'
              : th.statCard
              }`}
          >
            <div className="p-1.5 bg-[#ef4444]/20 rounded-lg"><AlertTriangle className="text-[#ef4444] w-5 h-5" /></div>
            <div className="text-left">
              <div className={`text-2xl font-black leading-none ${criticalPatients.length > 0 ? 'text-[#ef4444]' : th.statText}`}>{criticalPatients.length}</div>
              <div className={`text-[10px] uppercase font-bold tracking-wider mt-0.5 ${th.statSubText}`}>Critical</div>
            </div>
          </button>

          {/* Warning */}
          <button
            onClick={() => setActiveFilter('Warning')}
            className={`flex items-center space-x-3 px-4 py-2.5 rounded-xl border transition-all ${activeFilter === 'Warning'
              ? 'bg-[#f59e0b]/20 border-[#f59e0b]'
              : th.statCard
              }`}
          >
            <div className="p-1.5 bg-[#f59e0b]/20 rounded-lg"><Activity className="text-[#f59e0b] w-5 h-5" /></div>
            <div className="text-left">
              <div className={`text-2xl font-black leading-none ${activeFilter === 'Warning' ? 'text-[#f59e0b]' : th.statText}`}>{warningPatients.length}</div>
              <div className={`text-[10px] uppercase font-bold tracking-wider mt-0.5 ${th.statSubText}`}>Warning</div>
            </div>
          </button>

          {/* Stable */}
          <button
            onClick={() => setActiveFilter('Stable')}
            className={`flex items-center space-x-3 px-4 py-2.5 rounded-xl border transition-all ${activeFilter === 'Stable'
              ? 'bg-[#84cc16]/20 border-[#84cc16]'
              : th.statCard
              }`}
          >
            <div className="p-1.5 bg-[#84cc16]/20 rounded-lg"><CheckSquare className="text-[#84cc16] w-5 h-5" /></div>
            <div className="text-left">
              <div className={`text-2xl font-black leading-none ${activeFilter === 'Stable' ? 'text-[#84cc16]' : th.statText}`}>{stablePatients.length}</div>
              <div className={`text-[10px] uppercase font-bold tracking-wider mt-0.5 ${th.statSubText}`}>Stable</div>
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

          {/* ── NEWS2 LEGEND ── */}
          <div className={`flex items-center flex-wrap gap-x-5 gap-y-1 px-4 py-2 shrink-0 ${th.legendBg} border-b ${th.statsBorder}`}>
            <span className={`text-xs font-bold uppercase tracking-wider ${th.legendLabel}`}>NEWS2 Risk Levels:</span>
            <div className="flex items-center space-x-1.5">
              <span className="w-3 h-3 rounded-full bg-[#ef4444] shrink-0" />
              <span className={`text-sm font-semibold ${th.legendText}`}>≥ 7 (Critical — Emergent)</span>
            </div>
            <div className="flex items-center space-x-1.5">
              <span className="w-3 h-3 rounded-full bg-[#f59e0b] shrink-0" />
              <span className={`text-sm font-semibold ${th.legendText}`}>5–6 (Medium — Urgent review)</span>
            </div>
            <div className="flex items-center space-x-1.5">
              <span className="w-3 h-3 rounded-full bg-[#84cc16] shrink-0" />
              <span className={`text-sm font-semibold ${th.legendText}`}>0–4 (Low — Nurse assessment)</span>
            </div>
          </div>

          <div className="flex-1 overflow-x-auto flex flex-col">
            <div className="min-w-[900px] flex-1 flex flex-col">
              {/* ── COLUMN HEADER ── */}
              <div
                className={`flex items-end shrink-0 ${th.tableHdrBg} border-b-2 ${th.tableHdrBorder} px-3`}
                style={{ paddingTop: '6px', paddingBottom: '0px' }}
              >
                <div className={`${COL_BED} text-center border-r ${th.tableHdrBorder}`}>
                  <span className={`text-[10px] font-bold ${th.tableHdrText} uppercase tracking-wider pb-1 block`}>Bed</span>
                </div>
                <div className={`${COL_PATIENT} px-3 border-r ${th.tableHdrBorder}`}>
                  <span className={`text-[10px] font-bold ${th.tableHdrText} uppercase tracking-wider pb-1 block`}>Patient / MRN</span>
                </div>
                <div className={`${COL_SCORE} text-center border-r ${th.tableHdrBorder}`}>
                  <span className={`text-[10px] font-bold ${th.tableHdrText} uppercase tracking-wider pb-1 block`}>Score</span>
                </div>
                <div className={`${COL_COMPLAINT} px-3 border-r ${th.tableHdrBorder}`}>
                  <span className={`text-[10px] font-bold ${th.tableHdrText} uppercase tracking-wider pb-1 block`}>Complaint / Flag</span>
                </div>
                <div className={`${COL_VITALS} flex flex-col px-1`}>
                  <div className={`text-[10px] font-bold ${th.tableHdrText} uppercase tracking-wider pb-0.5 text-center`}>
                    Vital Signs Trajectories (Past 24 Hrs)
                  </div>
                  <div className="flex w-full pb-1">
                    {['HR', 'RR', 'SpO2', 'BP', 'Temp'].map((v, i) => (
                      <div key={v} className={`flex-1 text-center text-[10px] font-bold ${th.tableHdrText} uppercase ${i < 4 ? `border-r ${th.tableHdrBorder}` : ''}`}>
                        {v}
                      </div>
                    ))}
                  </div>
                </div>
              </div>

          {/* ── ROWS ── */}
          <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2" style={{ scrollbarWidth: 'none', msOverflowStyle: 'none', WebkitOverflowScrolling: 'touch' }}>
            {sortedPatients.map((patient) => {
              const s = getStatusStyles(patient.status);
              return (
                <div
                  key={patient.id}
                  onClick={() => handlePatientClick(patient)}
                  className={`flex items-stretch cursor-pointer rounded-lg transition-all duration-150 hover:brightness-[1.03] ${L ? `${s.lRowBg} ${s.lBorder} shadow-sm hover:shadow-md` : `${s.rowBg} ${s.border} ${s.glow}`} ${patient.status === 'critical' ? 'row-critical-blink' : ''}`}
                  style={{ minHeight: '96px' }}
                >
                  {/* Bed badge */}
                  <div className={`${COL_BED} flex items-center justify-center py-3 px-1 border-r ${th.rowBorder}`}>
                    <div className={`w-10 h-10 rounded-lg ${s.solidBg} flex items-center justify-center text-white font-black text-sm shadow`}>
                      {patient.bed}
                    </div>
                  </div>

                  {/* Patient info — ID is primary identifier (MIMIC de-identified) */}
                  <div className={`${COL_PATIENT} flex flex-col justify-center py-2 px-3 border-r ${th.rowBorder}`}>
                    <div className={`font-black text-base leading-tight tracking-tight truncate ${s.text}`}>{patient.name || patient.id}</div>
                    <div className={`text-[10px] font-semibold mt-0.5 ${L ? 'text-slate-400' : 'text-slate-500'} uppercase tracking-wider`}>{patient.id}</div>
                    <div className={`text-[11px] mt-0.5 ${L ? 'text-slate-500' : 'text-slate-400'}`}>{patient.age}y · {patient.sex}</div>
                  </div>

                  {/* NEWS2 + ML Score */}
                  <div className={`${COL_SCORE} flex items-center justify-center gap-1.5 border-r ${th.rowBorder} px-1.5 py-3`}>
                    <div className={`flex flex-col items-center justify-center rounded-lg border px-2 py-1.5 min-w-[38px] ${s.border} ${th.scoreCard}`}>
                      <span className={`text-[8px] font-black uppercase tracking-wider ${s.text}`}>NEWS2</span>
                      <span className={`text-2xl font-black leading-none mt-0.5 ${th.rowText}`}>{patient.news2}</span>
                    </div>
                    <div className={`flex flex-col items-center justify-center rounded-lg border px-2 py-1.5 min-w-[38px] ${s.border} ${th.scoreCard}`}>
                      <span className={`text-[8px] font-black uppercase tracking-wider ${s.text}`}>ML%</span>
                      <span className={`text-2xl font-black leading-none mt-0.5 ${th.rowText}`}>{patient.mlRisk}</span>
                    </div>
                  </div>

                  {/* Chief complaint + brief flag + drug-lab badge */}
                  <div className={`${COL_COMPLAINT} flex flex-col justify-start py-2 px-3 border-r ${th.rowBorder}`}>
                    <span className={`text-[11px] font-semibold leading-snug line-clamp-2 mt-1 ${th.complaintText}`}>
                      {patient.complaint}
                    </span>
                    
                    {patient.briefFlag && (
                      <span className={`text-[10px] font-medium leading-snug mt-1.5 line-clamp-2 ${
                        patient.status === 'critical' ? 'text-[#ef4444]'
                        : patient.status === 'warning' ? 'text-[#f59e0b]'
                        : 'text-slate-400'
                      }`}>
                        ⚠ {patient.briefFlag}
                      </span>
                    )}

                    {patient.drugLabAlerts && patient.drugLabAlerts.length > 0 && (
                      <span className="drug-alert-badge mt-1.5 inline-block text-[10px] px-1.5 py-0.5 rounded-sm font-bold w-max">
                        💊 Drug-Lab Alert
                      </span>
                    )}
                  </div>

                  {/* 5 Vitals sparklines */}
                  <div className={`${COL_VITALS} flex items-stretch py-1 px-1 ${L ? `${s.lVitalsBg} rounded-r-md border-l border-white/50` : ''}`}>
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
                          className={`flex-1 flex flex-col pt-1 ${i < 4 ? `border-r ${th.rowBorder}` : ''} px-1`}
                        >
                          <div className="text-center leading-none mb-1.5">
                            <span className={`text-sm font-black ${th.vitalVal}`}>{displayVal}</span>
                            <span className={`text-[10px] font-bold ml-0.5 ${th.vitalUnit}`}>{unit}</span>
                          </div>
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
                                  stroke={L ? s.lHex : s.hex}
                                  strokeWidth={2}
                                  fill={L ? s.lHex : s.hex}
                                  fillOpacity={L ? 0.15 : 0.22}
                                  isAnimationActive={false}
                                  dot={false}
                                  baseValue="dataMin"
                                  connectNulls={true}
                                />
                              </AreaChart>
                            </ResponsiveContainer>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                </div>
              );
            })}
          </div>
            </div>
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
            ALERT SIDEBAR
        ══════════════════════════════════════════════════════ */}
        <aside
          className={`fixed inset-y-0 right-0 w-full sm:w-96 ${th.alertBg} border-l ${th.alertBorder} shadow-2xl transform transition-transform duration-300 ease-in-out z-50 flex flex-col ${showAlertPanel ? 'translate-x-0' : 'translate-x-full'}`}
        >
          <div className={`p-4 border-b ${th.alertBorder} flex justify-between items-center sticky top-0 ${th.alertHdr} z-10`}>
            <div className="flex items-center space-x-2">
              <AlertTriangle className="w-5 h-5 text-[#ef4444]" />
              <h2 className={`text-base font-bold ${L ? 'text-slate-800' : 'text-white'}`}>Active Alerts</h2>
              {criticalPatients.length > 0 && (
                <span className="bg-[#ef4444] text-white text-xs font-bold px-2 py-0.5 rounded-full">
                  {criticalPatients.length}
                </span>
              )}
            </div>
            <button onClick={() => setShowAlertPanel(false)} className={`p-1 rounded-full ${L ? 'hover:bg-slate-100' : 'hover:bg-slate-800'}`}>
              <X className={`w-4 h-4 ${L ? 'text-slate-500' : 'text-slate-400'}`} />
            </button>
          </div>

          <div className="flex-1 overflow-y-auto p-4 space-y-3" style={{ scrollbarWidth: 'none' }}>
            {criticalPatients.length === 0 ? (
              <div className={`text-center py-8 text-sm ${L ? 'text-slate-400' : 'text-slate-500'}`}>No active critical alerts.</div>
            ) : (
              criticalPatients.map(patient => {
                const isExpanded = expandedAlertId === patient.id;
                return (
                  <div key={`alert-${patient.id}`} className="rounded-xl border-l-4 border-[#ef4444] shadow-lg overflow-hidden">
                    <div
                      onClick={() => setExpandedAlertId(isExpanded ? null : patient.id)}
                      className={`flex justify-between items-center ${th.alertCardBg} ${th.alertCardHover} px-4 py-3 cursor-pointer transition-colors`}
                    >
                      <div>
                        <h3 className={`font-black text-base tracking-tight ${L ? 'text-slate-800' : 'text-white'}`}>{patient.id}</h3>
                        <p className={`text-xs ${L ? 'text-slate-500' : 'text-slate-400'}`}>Bed {patient.bed} · {patient.age}y {patient.sex} · NEWS2: {patient.news2}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="bg-[#ef4444] text-white text-[9px] font-black px-2 py-0.5 rounded animate-pulse">CRITICAL</span>
                        {isExpanded
                          ? <ChevronUp className={`w-4 h-4 ${L ? 'text-slate-400' : 'text-slate-400'}`} />
                          : <ChevronDown className={`w-4 h-4 ${L ? 'text-slate-400' : 'text-slate-400'}`} />}
                      </div>
                    </div>

                    {isExpanded && (
                      <div className={`${th.alertDetailBg} px-4 pt-3 pb-4 space-y-3`}>
                        <div className={`${th.alertSubBg} rounded-lg p-3 border ${th.alertSubBorder}`}>
                          <p className="text-[10px] font-bold text-[#ef4444] uppercase tracking-wider mb-1">Reason for Flag</p>
                          <p className={`text-xs leading-relaxed ${th.alertSubText}`}>
                            {patient.mlExplanation || 'Critical deterioration detected by ML monitoring.'}
                          </p>
                        </div>

                        {patient.drugLabAlerts && patient.drugLabAlerts.length > 0 && (
                          <div className="bg-[#ef4444]/10 rounded-lg p-3 border border-[#ef4444]/30 mb-3">
                            <p className="text-[10px] font-bold text-[#ef4444] uppercase tracking-wider mb-1 flex items-center">
                              <Shield className="w-3 h-3 mr-1" /> Medication Alert
                            </p>
                            {patient.drugLabAlerts.map((alert, idx) => (
                              <div key={idx} className="mb-2 last:mb-0">
                                <p className={`text-xs font-bold ${L ? 'text-slate-800' : 'text-white'}`}>{alert.rule_name}</p>
                                <p className={`text-[11px] leading-snug mt-0.5 ${th.alertSubText}`}>{alert.message}</p>
                              </div>
                            ))}
                          </div>
                        )}

                        <div className={`${th.alertSubBg} rounded-lg p-3 border ${th.alertSubBorder}`}>
                          <p className="text-[10px] font-bold text-yellow-500 uppercase tracking-wider mb-1">Immediate Action</p>
                          <p className={`text-xs leading-relaxed ${th.alertSubText}`}>
                            {patient.recommendedAction || 'Bedside assessment required immediately.'}
                          </p>
                        </div>

                        <div className="flex gap-2">
                          <button
                            onClick={e => { e.stopPropagation(); handlePatientClick(patient); }}
                            className={`flex-1 text-xs font-bold py-2 rounded-lg transition-colors ${th.btnPrimary}`}
                          >
                            View Patient Chart
                          </button>
                          <button
                            onClick={e => e.stopPropagation()}
                            className={`flex-1 text-xs font-bold py-2 rounded-lg flex justify-center items-center transition-colors shadow-[0_0_8px_rgba(239,68,68,0.4)] ${th.btnEscalate}`}
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
          className={`fixed inset-y-0 right-0 w-full lg:w-3/4 ${th.drawerBg} border-l ${L ? 'border-[#e9d5ff]' : 'border-slate-700'} shadow-[0_0_50px_rgba(0,0,0,0.4)] transform transition-transform duration-500 ease-in-out z-60 flex flex-col ${isDrawerOpen ? 'translate-x-0' : 'translate-x-full'}`}
          style={{ zIndex: 60 }}
        >
          {selectedPatient && (() => {
            const ds = getStatusStyles(selectedPatient.status);
            return (
              <>
                {/* Drawer Header */}
                <div className={`h-[72px] px-8 border-b ${th.drawerHdrBorder} flex justify-between items-center ${th.drawerHdrBg} shrink-0`}>
                  <div className="flex items-center space-x-4">
                    <div className={`w-12 h-12 rounded-xl flex items-center justify-center text-xl font-black text-white ${ds.solidBg} shadow-lg`}>
                      {selectedPatient.bed}
                    </div>
                    <div>
                      <div className="flex items-center gap-2 mb-0.5">
                        <h2 className={`text-xl font-black tracking-tight ${th.drawerHdrText}`}>{selectedPatient.id}</h2>
                        <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wider ${L ? 'bg-white/20 text-white/80' : 'bg-white/10 text-white/70'}`}>HADM ID</span>
                      </div>
                      <p className={`text-xs ${th.drawerSubText}`}>
                        {selectedPatient.age} yrs · {selectedPatient.sex} · Bed {selectedPatient.bed} · Admitted: {selectedPatient.admitted}
                      </p>
                    </div>
                  </div>
                  <button onClick={() => setIsDrawerOpen(false)} className={`p-2 rounded-full ${L ? 'hover:bg-white/10' : 'hover:bg-slate-800'}`}>
                    <X className={`w-5 h-5 ${th.drawerHdrText}`} />
                  </button>
                  <button
                    onClick={() => setShowPatientRules(true)}
                    title="Patient-Specific Alert Rules"
                    className={`p-2 rounded-full transition-colors ${L ? 'hover:bg-white/10 text-white/70 hover:text-white' : 'hover:bg-slate-800 text-slate-400 hover:text-white'}`}
                  >
                    <Settings2 className="w-5 h-5" />
                  </button>
                </div>

                {/* Drawer Scrollable Content */}
                <div className={`flex-1 overflow-y-auto p-6 space-y-6 ${th.drawerBg}`} style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}>

                  {/* Clinical Alert section */}
                  <div className={`border-l-4 rounded-r-xl p-5 flex flex-col lg:flex-row gap-5 ${
                    selectedPatient.status === 'critical' ? 'border-[#ef4444] bg-[#ef4444]/10'
                    : selectedPatient.status === 'warning' ? 'border-[#f59e0b] bg-[#f59e0b]/10'
                    : 'border-[#84cc16] bg-[#84cc16]/10'
                  }`}>

                    {/* LEFT — ML explanation + actions */}
                    <div className="flex-1 space-y-3">
                      <div className="flex items-center space-x-2 mb-1">
                        <AlertTriangle className={`w-5 h-5 ${
                          selectedPatient.status === 'critical' ? 'text-[#ef4444]'
                          : selectedPatient.status === 'warning' ? 'text-[#f59e0b]'
                          : 'text-[#84cc16]'
                        }`} />
                        <h3 className={`text-lg font-bold ${
                          selectedPatient.status === 'critical' ? 'text-[#ef4444]'
                          : selectedPatient.status === 'warning' ? 'text-[#f59e0b]'
                          : 'text-[#84cc16]'
                        }`}>
                          {selectedPatient.status === 'critical' ? 'Critical Deterioration Alert'
                          : selectedPatient.status === 'warning' ? 'Warning: Early Deterioration Detected'
                          : 'Status: Stable — Routine Monitoring'}
                        </h3>
                      </div>

                      <div className={`p-4 rounded-lg border ${th.drawerCard}`}>
                        <h4 className={`text-xs font-bold uppercase tracking-wider mb-2 flex items-center ${L ? 'text-slate-500' : 'text-slate-300'}`}>
                          <Activity className="w-3.5 h-3.5 mr-1.5 text-[#800080]" /> ML Risk Explanation
                        </h4>
                        <p className={`text-sm leading-relaxed ${L ? 'text-slate-800' : 'text-white'}`}>
                          {selectedPatient.mlExplanation || 'High risk of clinical deterioration based on vital sign trajectory.'}
                        </p>
                      </div>

                      <div className={`p-4 rounded-lg border ${th.drawerCard}`}>
                        <h4 className={`text-xs font-bold uppercase tracking-wider mb-2 flex items-center ${L ? 'text-slate-500' : 'text-slate-300'}`}>
                          <Lightbulb className="w-3.5 h-3.5 mr-1.5 text-yellow-500" /> Recommended Action
                        </h4>
                        <p className={`text-sm leading-relaxed ${L ? 'text-slate-800' : 'text-white'}`}>
                          {selectedPatient.recommendedAction || 'Immediate bedside assessment. Consider rapid response escalation.'}
                        </p>
                      </div>

                      {/* Acknowledge / Escalate buttons */}
                      <div className="flex space-x-3 pt-1">
                        {(() => {
                          const patId = selectedPatient.id;
                          const isAcked = !!acknowledgedAlerts[patId];
                          const isEsc = !!escalatedAlerts[patId];
                          return (
                            <>
                              <button
                                onClick={() => {
                                  if (!isAcked) {
                                    setAcknowledgedAlerts(prev => ({ ...prev, [patId]: new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}) }));
                                  }
                                }}
                                className={`font-bold py-2.5 px-5 rounded-lg flex items-center text-sm transition-all ${
                                  isAcked
                                    ? 'bg-amber-500/20 text-amber-400 border border-amber-500/50 cursor-default'
                                    : th.btnPrimary
                                }`}
                              >
                                <CheckSquare className="w-4 h-4 mr-2" />
                                {isAcked ? `ACK'd · ${acknowledgedAlerts[patId]}` : 'Acknowledge'}
                              </button>

                              {selectedPatient.status === 'critical' && (
                                <button
                                  onClick={() => {
                                    if (!isEsc) setShowEscalateModal(true);
                                  }}
                                  className={`font-bold py-2.5 px-5 rounded-lg flex items-center text-sm transition-all ${
                                    isEsc
                                      ? 'bg-orange-500/20 text-orange-400 border border-orange-500/50 cursor-default'
                                      : `shadow-[0_0_12px_rgba(239,68,68,0.4)] ${th.btnEscalate}`
                                  }`}
                                >
                                  <PhoneForwarded className="w-4 h-4 mr-2" />
                                  {isEsc ? `RRT NOTIFIED · ${escalatedAlerts[patId]}` : 'Escalate to RRT'}
                                </button>
                              )}
                            </>
                          );
                        })()}
                      </div>
                    </div>

                    {/* RIGHT — NEWS2 score breakdown */}
                    <div className={`w-[280px] shrink-0 rounded-xl p-5 border flex flex-col ${th.drawerCard}`}>
                      <p className={`text-[10px] font-bold uppercase tracking-wider mb-3 ${L ? 'text-slate-500' : 'text-slate-400'}`}>Current NEWS2 Score</p>
                      <div className={`flex items-center justify-between mb-4 pb-4 border-b ${L ? 'border-[#e9d5ff]' : 'border-slate-700'}`}>
                        <span className={`text-5xl font-black ${L ? 'text-slate-800' : 'text-white'}`}>{selectedPatient.news2}</span>
                        <span className={`px-3 py-1.5 rounded-lg font-bold text-xs ${getNEWSLabel(selectedPatient.news2).color}`}>
                          {getNEWSLabel(selectedPatient.news2).text}
                        </span>
                      </div>
                      <p className={`text-sm font-bold mb-2 ${L ? 'text-slate-800' : 'text-white'}`}>Score Factors</p>
                      <div className="space-y-2 flex-1">
                        {selectedPatient.newsFactors?.map((f, i) => (
                          <div key={i} className={`flex justify-between items-center rounded px-3 py-1.5 ${L ? 'bg-white border border-[#e9d5ff]' : 'bg-slate-800'}`}>
                            <span className={`text-xs ${L ? 'text-slate-600' : 'text-slate-400'}`}>{f.name}</span>
                            <span className={`text-xs font-bold px-2 py-0.5 rounded ${f.score >= 3 ? 'bg-[#ef4444] text-white' : f.score > 0 ? 'bg-[#f59e0b] text-black' : L ? 'bg-slate-100 text-slate-600' : 'bg-slate-700 text-white'}`}>
                              {f.score}
                            </span>
                          </div>
                        ))}
                        {(!selectedPatient.newsFactors || selectedPatient.newsFactors.length === 0) && (
                          <p className={`text-xs italic ${L ? 'text-slate-400' : 'text-slate-500'}`}>All factors normal</p>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* 24-Hour Vitals Graph */}
                  <div>
                    <h3 className={`text-base font-bold mb-3 flex items-center ${L ? 'text-slate-800' : 'text-white'}`}>
                      <Activity className="w-4 h-4 mr-2 text-[#800080]" /> 24-Hour Vitals Trajectory
                    </h3>

                  {/* ── NEWS2 Score Trend ── */}
                  {(() => {
                    const trendData = (selectedPatient.trajectory || []).map((pt, i) => ({
                      time: pt.time,
                      news2: approximateNEWS2FromTrajectory(pt),
                    }));
                    const scores = trendData.map(d => d.news2).filter(s => s !== undefined);
                    const first = scores[0], last = scores[scores.length - 1];
                    const trend = (last - first);
                    const TrendIcon = trend > 1 ? TrendingUp : trend < -1 ? TrendingDown : Minus;
                    const trendColor = trend > 1 ? '#ef4444' : trend < -1 ? '#10b981' : '#f59e0b';
                    const trendLabel = trend > 1 ? 'Worsening' : trend < -1 ? 'Improving' : 'Stable';
                    const rulesForPatient = patientRuleOverrides[selectedPatient.id] || DISEASE_PRESETS.General;
                    return (
                      <div className={`mb-5 rounded-xl border p-4 ${L ? 'bg-[#f5f0ff] border-[#e9d5ff]' : 'bg-[#0f172a] border-slate-800'}`}>
                        <div className="flex items-center justify-between mb-3">
                          <h4 className={`text-sm font-bold flex items-center ${L ? 'text-slate-700' : 'text-white'}`}>
                            <TrendIcon className="w-4 h-4 mr-2" style={{ color: trendColor }} /> NEWS2 Score Trend (24h)
                          </h4>
                          <div className="flex items-center gap-3">
                            <span
                              className="text-[10px] font-bold px-2 py-0.5 rounded-full uppercase"
                              style={{ backgroundColor: `${trendColor}20`, color: trendColor }}
                            >
                              {trendLabel} · {last >= 0 ? `+${last}` : last} from baseline
                            </span>
                            <span className={`text-[10px] ${L ? 'text-slate-500' : 'text-slate-400'}`}>
                              Current: <span className="font-black" style={{ color: last >= (rulesForPatient.criticalThreshold || 7) ? '#ef4444' : last >= (rulesForPatient.warningThreshold || 5) ? '#f59e0b' : '#84cc16' }}>{selectedPatient.news2}</span>
                            </span>
                          </div>
                        </div>
                        <div style={{ height: 120 }}>
                          <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={trendData} margin={{ top: 5, right: 10, left: -20, bottom: 0 }}>
                              <CartesianGrid strokeDasharray="3 3" stroke={th.chartGrid} vertical={false} />
                              <XAxis dataKey="time" stroke={th.chartAxis} tick={{ fontSize: 9 }} interval="preserveStartEnd" />
                              <YAxis stroke={th.chartAxis} tick={{ fontSize: 9 }} domain={[0, 12]} />
                              <Tooltip
                                contentStyle={{ backgroundColor: th.chartTooltipBg, borderColor: th.chartTooltipBorder, fontSize: 11 }}
                                formatter={(val) => [val, 'NEWS2']}
                              />
                              <ReferenceLine y={rulesForPatient.criticalThreshold || 7} stroke="#ef4444" strokeDasharray="4 2" label={{ value: 'Critical', fill: '#ef4444', fontSize: 9, position: 'right' }} />
                              <ReferenceLine y={rulesForPatient.warningThreshold || 5} stroke="#f59e0b" strokeDasharray="4 2" label={{ value: 'Warning', fill: '#f59e0b', fontSize: 9, position: 'right' }} />
                              <Line
                                type="monotone" dataKey="news2"
                                stroke={last >= (rulesForPatient.criticalThreshold || 7) ? '#ef4444' : last >= (rulesForPatient.warningThreshold || 5) ? '#f59e0b' : '#84cc16'}
                                strokeWidth={2.5} dot={{ r: 3 }} activeDot={{ r: 5 }}
                              />
                            </LineChart>
                          </ResponsiveContainer>
                        </div>
                      </div>
                    );
                  })()}
                    <div className={`h-72 rounded-xl p-4 border ${L ? 'bg-[#f5f0ff] border-[#e9d5ff]' : 'bg-[#0f172a] border-slate-800'}`}>
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={selectedPatient.trajectory} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
                          <defs>
                            <linearGradient id="gHR" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#ef4444" stopOpacity={0.5} /><stop offset="95%" stopColor="#ef4444" stopOpacity={0} /></linearGradient>
                            <linearGradient id="gRR" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#f59e0b" stopOpacity={0.5} /><stop offset="95%" stopColor="#f59e0b" stopOpacity={0} /></linearGradient>
                            <linearGradient id="gSpO2" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#10b981" stopOpacity={0.5} /><stop offset="95%" stopColor="#10b981" stopOpacity={0} /></linearGradient>
                            <linearGradient id="gBP" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#3b82f6" stopOpacity={0.5} /><stop offset="95%" stopColor="#3b82f6" stopOpacity={0} /></linearGradient>
                            <linearGradient id="gTemp" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#a855f7" stopOpacity={0.5} /><stop offset="95%" stopColor="#a855f7" stopOpacity={0} /></linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" stroke={th.chartGrid} vertical={false} />
                          <XAxis dataKey="time" stroke={th.chartAxis} tick={{ fontSize: 10 }} />
                          <YAxis yAxisId="l" stroke={th.chartAxis} tick={{ fontSize: 10 }} />
                          <YAxis yAxisId="r" orientation="right" stroke={th.chartAxis} tick={{ fontSize: 10 }} />
                          <Tooltip contentStyle={{ backgroundColor: th.chartTooltipBg, borderColor: th.chartTooltipBorder, color: L ? '#1e293b' : '#f1f5f9', fontSize: 12 }} />
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
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                    {/* Vitals table */}
                    <div className={`rounded-xl border overflow-hidden ${th.drawerTable}`}>
                      <div className={`p-3 border-b ${L ? 'border-[#e9d5ff]' : 'border-slate-800'} ${th.drawerTableHdr} flex items-center`}>
                        <Heart className={`w-4 h-4 mr-2 ${L ? 'text-[#800080]' : 'text-slate-300'}`} />
                        <h3 className={`text-sm font-bold ${L ? 'text-slate-800' : 'text-white'}`}>Recent Vitals</h3>
                      </div>
                      <table className="w-full text-left">
                        <thead>
                          <tr className={`border-b ${L ? 'border-[#e9d5ff]' : 'border-slate-800'}`}>
                            {['Time', 'HR', 'RR', 'SpO2', 'BP', 'Temp'].map(h => (
                              <th key={h} className={`px-3 py-2 text-[10px] font-bold uppercase ${th.drawerTH}`}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {selectedPatient.recentVitals?.map((v, i) => (
                            <tr key={i} className={`border-b ${L ? 'border-[#e9d5ff]/50' : 'border-slate-800/50'} ${th.drawerRowHov}`}>
                              <td className={`px-3 py-2 text-xs ${th.drawerTDMuted}`}>{v.time}</td>
                              <td className={`px-3 py-2 text-xs font-medium ${th.drawerTD}`}>{v.hr}</td>
                              <td className={`px-3 py-2 text-xs font-medium ${th.drawerTD}`}>{v.rr}</td>
                              <td className={`px-3 py-2 text-xs font-medium ${th.drawerTD}`}>{v.spo2}%</td>
                              <td className={`px-3 py-2 text-xs ${L ? 'text-slate-700' : 'text-slate-300'}`}>{v.sbp}/{v.dbp}</td>
                              <td className={`px-3 py-2 text-xs font-medium ${th.drawerTD}`}>{v.temp}°</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>

                    {/* Labs table */}
                    <div className={`rounded-xl border overflow-hidden ${th.drawerTable}`}>
                      <div className={`p-3 border-b ${L ? 'border-[#e9d5ff]' : 'border-slate-800'} ${th.drawerTableHdr} flex items-center`}>
                        <Droplets className={`w-4 h-4 mr-2 ${L ? 'text-[#800080]' : 'text-slate-300'}`} />
                        <h3 className={`text-sm font-bold ${L ? 'text-slate-800' : 'text-white'}`}>Lab Results</h3>
                      </div>
                      <table className="w-full text-left">
                        <thead>
                          <tr className={`border-b ${L ? 'border-[#e9d5ff]' : 'border-slate-800'}`}>
                            {['Time', 'Test', 'Value', 'Unit'].map(h => (
                              <th key={h} className={`px-3 py-2 text-[10px] font-bold uppercase ${th.drawerTH}`}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {selectedPatient.recentLabs?.map((lab, i) => (
                            <tr key={i} className={`border-b ${L ? 'border-[#e9d5ff]/50' : 'border-slate-800/50'} ${th.drawerRowHov}`}>
                              <td className={`px-3 py-2 text-xs ${th.drawerTDMuted}`}>
                                {lab.time?.includes('T') ? lab.time.split('T').pop().substring(0, 5) : lab.time}
                              </td>
                              <td className={`px-3 py-2 text-xs ${L ? 'text-slate-600' : 'text-slate-300'}`}>{lab.test}</td>
                              <td className={`px-3 py-2 text-xs font-bold ${th.drawerTD}`}>{lab.value}</td>
                              <td className={`px-3 py-2 text-xs ${th.drawerTDMuted}`}>{lab.unit}</td>
                            </tr>
                          ))}
                          {(!selectedPatient.recentLabs || selectedPatient.recentLabs.length === 0) && (
                            <tr>
                              <td colSpan="4" className={`px-3 py-4 text-center text-xs ${L ? 'text-slate-400' : 'text-slate-500'}`}>No recent labs available.</td>
                            </tr>
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  {/* Active Medications */}
                  <div className={`rounded-xl border overflow-hidden ${th.drawerMedBg}`}>
                    <div className={`p-3 border-b ${L ? 'border-[#e9d5ff]' : 'border-slate-800'} ${th.drawerTableHdr} flex items-center`}>
                      <span className="text-base mr-2">💊</span>
                      <h3 className={`text-sm font-bold ${L ? 'text-slate-800' : 'text-white'}`}>Active Medications</h3>
                      {selectedPatient.medications?.length > 0 && (
                        <span className={`ml-2 text-[10px] border px-2 py-0.5 rounded-full font-bold ${L ? 'bg-[#f5f0ff] text-[#800080] border-[#800080]/30' : 'bg-blue-600/20 text-blue-400 border-blue-500/30'}`}>
                          {selectedPatient.medications.length}
                        </span>
                      )}
                    </div>
                    {selectedPatient.medications && selectedPatient.medications.length > 0 ? (
                      <div className={`divide-y ${th.drawerDivide}`}>
                        {selectedPatient.medications.map((med, i) => (
                          <div key={i} className={`flex items-center justify-between px-4 py-2.5 transition-colors ${th.drawerRowHov}`}>
                            <span className={`text-sm font-bold ${L ? 'text-slate-800' : 'text-white'}`}>{med.name}</span>
                            <span className={`text-xs font-medium ${L ? 'text-slate-500' : 'text-slate-400'}`}>{med.dose} · {med.frequency}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className={`px-4 py-4 text-center text-xs italic ${L ? 'text-slate-400' : 'text-slate-500'}`}>No active medications recorded.</div>
                    )}
                  </div>

                  {/* ── Drug-Lab Interaction Explanation Panel ── */}
                  {selectedPatient.drugLabAlerts && selectedPatient.drugLabAlerts.length > 0 && (
                    <div className="space-y-3">
                      {selectedPatient.drugLabAlerts.map((alert, ai) => (
                        <div
                          key={ai}
                          className={`rounded-xl border-l-4 overflow-hidden ${
                            alert.severity === 'CRITICAL'
                              ? 'border-l-[#ef4444] bg-[#ef4444]/8'
                              : 'border-l-[#f59e0b] bg-[#f59e0b]/8'
                          } ${L ? 'border border-[#e9d5ff]' : 'border border-slate-700'}`}
                        >
                          {/* Panel Header */}
                          <div className={`flex items-center justify-between px-4 py-3 border-b ${
                            alert.severity === 'CRITICAL'
                              ? L ? 'bg-red-50 border-red-100' : 'bg-[#ef4444]/10 border-[#ef4444]/20'
                              : L ? 'bg-amber-50 border-amber-100' : 'bg-[#f59e0b]/10 border-[#f59e0b]/20'
                          }`}>
                            <div className="flex items-center gap-2">
                              <FlaskConical className="w-4 h-4" style={{ color: alert.severity === 'CRITICAL' ? '#ef4444' : '#f59e0b' }} />
                              <span
                                className="text-xs font-black uppercase tracking-wider"
                                style={{ color: alert.severity === 'CRITICAL' ? '#ef4444' : '#f59e0b' }}
                              >
                                💊 Drug-Lab Interaction Detected
                              </span>
                            </div>
                            <span
                              className="text-[10px] font-bold px-2 py-0.5 rounded-full"
                              style={{
                                backgroundColor: alert.severity === 'CRITICAL' ? '#ef444420' : '#f59e0b20',
                                color: alert.severity === 'CRITICAL' ? '#ef4444' : '#f59e0b',
                              }}
                            >
                              {alert.severity}
                            </span>
                          </div>

                          {/* Panel Body */}
                          <div className="px-4 py-3 space-y-3">
                            {/* Rule name + trigger */}
                            <div>
                              <p className={`text-xs font-bold uppercase tracking-wider mb-1 ${ L ? 'text-slate-500' : 'text-slate-400'}`}>
                                Interaction Rule
                              </p>
                              <p className={`text-sm font-semibold ${L ? 'text-slate-800' : 'text-white'}`}>{alert.rule_name}</p>
                            </div>

                            {/* Lab trigger */}
                            <div className={`flex flex-wrap gap-2`}>
                              <div className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs ${
                                L ? 'bg-[#f5f0ff] border border-[#e9d5ff] text-slate-700' : 'bg-slate-800 border border-slate-700 text-slate-300'
                              }`}>
                                <FlaskConical className="w-3 h-3 text-purple-400" />
                                <span className="font-semibold capitalize">{alert.lab_name}:</span>
                                <span className="font-black" style={{ color: alert.severity === 'CRITICAL' ? '#ef4444' : '#f59e0b' }}>
                                  {typeof alert.lab_value === 'number' ? alert.lab_value.toFixed(2) : alert.lab_value}
                                </span>
                              </div>
                              {alert.triggering_meds?.map((med, mi) => (
                                <div key={mi} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs ${
                                  L ? 'bg-blue-50 border border-blue-100 text-blue-700' : 'bg-blue-900/30 border border-blue-800/50 text-blue-300'
                                }`}>
                                  <Pill className="w-3 h-3" />
                                  <span className="font-semibold capitalize">{med}</span>
                                </div>
                              ))}
                            </div>

                            {/* Message (mechanism) */}
                            <div className={`p-3 rounded-lg border ${
                              L ? 'bg-white border-[#e9d5ff]' : 'bg-slate-900 border-slate-700'
                            }`}>
                              <p className={`text-[10px] font-bold uppercase tracking-wider mb-1 ${ L ? 'text-slate-400' : 'text-slate-500'}`}>Clinical Significance</p>
                              <p className={`text-sm leading-relaxed ${L ? 'text-slate-800' : 'text-white'}`}>{alert.message}</p>
                            </div>

                            {/* Recommended Steps */}
                            <div className={`p-3 rounded-lg border ${
                              alert.severity === 'CRITICAL'
                                ? L ? 'bg-red-50 border-red-100' : 'bg-red-900/10 border-red-800/30'
                                : L ? 'bg-amber-50 border-amber-100' : 'bg-amber-900/10 border-amber-800/30'
                            }`}>
                              <p className={`text-[10px] font-bold uppercase tracking-wider mb-2 flex items-center gap-1.5 ${
                                alert.severity === 'CRITICAL' ? 'text-[#ef4444]' : 'text-[#f59e0b]'
                              }`}>
                                <Lightbulb className="w-3 h-3" /> Recommended Steps
                              </p>
                              <div className="space-y-1">
                                {alert.action.split('. ').filter(s => s.trim()).map((step, si) => (
                                  <div key={si} className="flex gap-2 items-start">
                                    <span
                                      className="text-[10px] font-black w-4 h-4 rounded-full flex items-center justify-center shrink-0 mt-0.5"
                                      style={{
                                        backgroundColor: alert.severity === 'CRITICAL' ? '#ef444420' : '#f59e0b20',
                                        color: alert.severity === 'CRITICAL' ? '#ef4444' : '#f59e0b',
                                      }}
                                    >
                                      {si + 1}
                                    </span>
                                    <p className={`text-xs leading-relaxed ${L ? 'text-slate-700' : 'text-slate-300'}`}>{step.trim()}{step.trim().endsWith('.') ? '' : '.'}</p>
                                  </div>
                                ))}
                              </div>
                            </div>

                            {/* Guideline source */}
                            {alert.guideline && (
                              <div className="flex items-center gap-1.5">
                                <BookOpen className={`w-3 h-3 ${L ? 'text-slate-400' : 'text-slate-500'}`} />
                                <p className={`text-[10px] ${L ? 'text-slate-400' : 'text-slate-500'}`}>
                                  Source: <span className="font-semibold">{alert.guideline}</span>
                                </p>
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                </div>
              </>
            );
          })()}
        </aside>

        {/* ══════════════════════════════════════════════════════
            PATIENT-SPECIFIC RULES MODAL
        ══════════════════════════════════════════════════════ */}
        {showPatientRules && selectedPatient && (() => {
          const patId = selectedPatient.id;
          const current = patientRuleOverrides[patId] || { ...DISEASE_PRESETS.General, preset: 'General', suppressNote: '' };
          const setField = (key, val) => setPatientRuleOverrides(prev => ({
            ...prev,
            [patId]: { ...(prev[patId] || { ...DISEASE_PRESETS.General, preset: 'General', suppressNote: '' }), [key]: val }
          }));
          return (
            <div className="fixed inset-0 bg-black/70 z-[200] flex items-center justify-center p-4" onClick={() => setShowPatientRules(false)}>
              <div
                className={`border rounded-2xl w-full max-w-md shadow-2xl overflow-hidden flex flex-col ${th.modalBg}`}
                onClick={e => e.stopPropagation()}
              >
                {/* Modal Header */}
                <div className={`p-4 border-b ${th.statsBorder} flex justify-between items-center ${th.modalHdrBg}`}>
                  <div className="flex items-center gap-2">
                    <Settings2 className={`w-5 h-5 ${L ? 'text-[#800080]' : 'text-purple-400'}`} />
                    <div>
                      <h2 className={`text-sm font-black ${L ? 'text-slate-800' : 'text-white'}`}>Patient-Specific Alert Rules</h2>
                      <p className={`text-[10px] ${L ? 'text-slate-500' : 'text-slate-400'}`}>HADM ID: {patId} · Overrides global NEWS2 thresholds</p>
                    </div>
                  </div>
                  <button onClick={() => setShowPatientRules(false)} className={L ? 'text-slate-400 hover:text-slate-800' : 'text-slate-500 hover:text-white'}>
                    <X className="w-5 h-5" />
                  </button>
                </div>

                <div className="p-5 space-y-5 overflow-y-auto" style={{ scrollbarWidth: 'none' }}>

                  {/* Disease Profile Presets */}
                  <div>
                    <label className={`block text-xs font-bold uppercase tracking-wider mb-2 ${L ? 'text-slate-500' : 'text-slate-400'}`}>Disease Profile Preset</label>
                    <div className="grid grid-cols-3 gap-2">
                      {Object.entries(DISEASE_PRESETS).map(([key, preset]) => {
                        const isSelected = (current.preset || 'General') === key;
                        return (
                          <button
                            key={key}
                            onClick={() => {
                              setPatientRuleOverrides(prev => ({
                                ...prev,
                                [patId]: { ...preset, preset: key, suppressNote: current.suppressNote || '' }
                              }));
                            }}
                            className={`text-xs font-bold py-2 px-3 rounded-lg border transition-all text-left ${
                              isSelected
                                ? L ? 'bg-[#800080] text-white border-[#800080]' : 'bg-purple-600/30 text-purple-300 border-purple-500'
                                : L ? 'bg-white border-[#e9d5ff] text-slate-600 hover:border-[#800080]/50' : 'bg-slate-800 border-slate-700 text-slate-400 hover:border-purple-700'
                            }`}
                          >
                            {key}
                          </button>
                        );
                      })}
                    </div>
                    {current.note && (
                      <p className={`text-[10px] mt-2 italic ${L ? 'text-slate-500' : 'text-slate-400'}`}>{current.note}</p>
                    )}
                  </div>

                  {/* Threshold Sliders */}
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className={`block text-xs font-bold uppercase mb-1 ${th.modalLabel}`}>Critical Alert (NEWS2 ≥)</label>
                      <div className="flex items-center gap-2">
                        <input
                          type="range" min="3" max="10" step="1"
                          value={current.criticalThreshold || 7}
                          onChange={e => setField('criticalThreshold', parseInt(e.target.value))}
                          className="flex-1 accent-[#ef4444]"
                        />
                        <span className={`text-lg font-black w-8 text-center ${L ? 'text-slate-800' : 'text-white'}`}>
                          {current.criticalThreshold || 7}
                        </span>
                      </div>
                    </div>
                    <div>
                      <label className={`block text-xs font-bold uppercase mb-1 ${th.modalLabel}`}>Warning Alert (NEWS2 ≥)</label>
                      <div className="flex items-center gap-2">
                        <input
                          type="range" min="2" max="7" step="1"
                          value={current.warningThreshold || 5}
                          onChange={e => setField('warningThreshold', parseInt(e.target.value))}
                          className="flex-1 accent-[#f59e0b]"
                        />
                        <span className={`text-lg font-black w-8 text-center ${L ? 'text-slate-800' : 'text-white'}`}>
                          {current.warningThreshold || 5}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* SpO2 Scale */}
                  <div>
                    <label className={`block text-xs font-bold uppercase tracking-wider mb-2 ${L ? 'text-slate-500' : 'text-slate-400'}`}>SpO2 Monitoring Scale</label>
                    <div className="flex gap-3">
                      {[1, 2].map(scale => (
                        <button
                          key={scale}
                          onClick={() => setField('spo2Scale', scale)}
                          className={`flex-1 py-2.5 px-3 rounded-lg border text-xs font-bold transition-all ${
                            (current.spo2Scale || 1) === scale
                              ? L ? 'bg-[#800080] text-white border-[#800080]' : 'bg-purple-600/30 text-purple-300 border-purple-500'
                              : L ? 'bg-white border-[#e9d5ff] text-slate-600' : 'bg-slate-800 border-slate-700 text-slate-400'
                          }`}
                        >
                          Scale {scale}<br />
                          <span className="text-[9px] font-normal opacity-70">
                            {scale === 1 ? 'Standard (target ≥96%)' : 'COPD (target 88-92%)'}
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* Clinical Note / Override Reason */}
                  <div>
                    <label className={`block text-xs font-bold uppercase tracking-wider mb-2 ${L ? 'text-slate-500' : 'text-slate-400'}`}>Clinical Override Note</label>
                    <textarea
                      rows={2}
                      placeholder="e.g. Therapeutic bradycardia on beta-blockers — HR < 55 expected..."
                      value={current.suppressNote || ''}
                      onChange={e => setField('suppressNote', e.target.value)}
                      className={`w-full border rounded-lg px-3 py-2 text-xs resize-none ${th.modalInput}`}
                    />
                    <p className={`text-[9px] mt-1 ${L ? 'text-slate-400' : 'text-slate-500'}`}>
                      This note will appear in patient records when thresholds are overridden.
                    </p>
                  </div>

                  {/* Summary of active rule */}
                  <div className={`rounded-lg p-3 border text-xs ${
                    L ? 'bg-[#f5f0ff] border-[#e9d5ff] text-slate-600' : 'bg-slate-800/60 border-slate-700 text-slate-400'
                  }`}>
                    <span className="font-bold">Active rule:</span> Alert CRITICAL at NEWS2 ≥ {current.criticalThreshold || 7}, WARNING at NEWS2 ≥ {current.warningThreshold || 5}.
                    SpO2 Scale {current.spo2Scale || 1} (alert below {current.spo2AlertBelow || 91}%).
                  </div>

                </div>

                {/* Footer */}
                <div className={`p-4 border-t ${th.statsBorder} ${th.modalHdrBg} flex justify-end gap-3`}>
                  <button
                    onClick={() => {
                      setPatientRuleOverrides(prev => {
                        const next = { ...prev };
                        delete next[patId];
                        return next;
                      });
                    }}
                    className={`px-4 py-2 rounded-lg text-xs font-bold transition-colors ${L ? 'text-slate-400 hover:text-slate-800' : 'text-slate-500 hover:text-white'}`}
                  >
                    Reset to Default
                  </button>
                  <button
                    onClick={() => setShowPatientRules(false)}
                    className={`px-5 py-2 rounded-lg text-xs font-bold flex items-center gap-1.5 transition-colors ${th.btnPrimary}`}
                  >
                    <CheckSquare className="w-3.5 h-3.5" /> Apply Rules
                  </button>
                </div>
              </div>
            </div>
          );
        })()}

        {/* ══════════════════════════════════════════════════════
            ESCALATE CONFIRMATION MODAL
        ══════════════════════════════════════════════════════ */}
        {showEscalateModal && selectedPatient && (
          <div className="fixed inset-0 bg-black/80 z-[300] flex items-center justify-center p-4">
            <div className={`border rounded-2xl w-full max-w-sm shadow-2xl overflow-hidden ${
              L ? 'bg-white border-red-200' : 'bg-[#0f172a] border-red-900/50'
            }`}>
              <div className={`p-4 ${L ? 'bg-red-50 border-b border-red-100' : 'bg-red-900/20 border-b border-red-900/30'}`}>
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-[#ef4444]/20 flex items-center justify-center">
                    <PhoneForwarded className="w-5 h-5 text-[#ef4444]" />
                  </div>
                  <div>
                    <h2 className={`text-sm font-black ${L ? 'text-slate-800' : 'text-white'}`}>Escalate to Rapid Response Team</h2>
                    <p className={`text-[11px] ${L ? 'text-slate-500' : 'text-slate-400'}`}>This will notify the on-call RRT immediately</p>
                  </div>
                </div>
              </div>
              <div className="p-5 space-y-3">
                <div className={`rounded-lg p-3 border text-xs ${
                  L ? 'bg-slate-50 border-slate-200' : 'bg-slate-800 border-slate-700'
                }`}>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <p className={`text-[9px] uppercase font-bold ${L ? 'text-slate-400' : 'text-slate-500'}`}>Patient</p>
                      <p className={`font-black ${L ? 'text-slate-800' : 'text-white'}`}>{selectedPatient.id}</p>
                    </div>
                    <div>
                      <p className={`text-[9px] uppercase font-bold ${L ? 'text-slate-400' : 'text-slate-500'}`}>NEWS2 Score</p>
                      <p className="font-black text-[#ef4444]">{selectedPatient.news2}</p>
                    </div>
                    <div>
                      <p className={`text-[9px] uppercase font-bold ${L ? 'text-slate-400' : 'text-slate-500'}`}>Ward / Bed</p>
                      <p className={`font-semibold ${L ? 'text-slate-700' : 'text-slate-300'}`}>{selectedPatient.ward} · Bed {selectedPatient.bed}</p>
                    </div>
                    <div>
                      <p className={`text-[9px] uppercase font-bold ${L ? 'text-slate-400' : 'text-slate-500'}`}>Alert Reason</p>
                      <p className={`font-semibold ${L ? 'text-slate-700' : 'text-slate-300'}`}>{selectedPatient.complaint}</p>
                    </div>
                  </div>
                </div>
                <p className={`text-xs ${L ? 'text-slate-500' : 'text-slate-400'}`}>
                  ⚠️ In production: this action sends a pager/SMS alert to the on-call physician and RRT team with the above patient details.
                </p>
              </div>
              <div className="px-5 pb-5 flex gap-3">
                <button
                  onClick={() => setShowEscalateModal(false)}
                  className={`flex-1 py-2.5 rounded-lg text-xs font-bold border transition-colors ${
                    L ? 'border-slate-200 text-slate-500 hover:text-slate-800' : 'border-slate-700 text-slate-400 hover:text-white'
                  }`}
                >
                  Cancel
                </button>
                <button
                  onClick={() => {
                    const patId = selectedPatient.id;
                    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                    setEscalatedAlerts(prev => ({ ...prev, [patId]: timeStr }));
                    setAcknowledgedAlerts(prev => ({ ...prev, [patId]: prev[patId] || timeStr }));
                    setShowEscalateModal(false);
                  }}
                  className="flex-1 py-2.5 rounded-lg text-xs font-black text-white bg-[#ef4444] hover:bg-red-600 transition-colors flex items-center justify-center gap-2 shadow-[0_0_20px_rgba(239,68,68,0.5)]"
                >
                  <PhoneForwarded className="w-4 h-4" /> Confirm — Notify RRT
                </button>
              </div>
            </div>
          </div>
        )}
        {showAddPatient && (
          <div className="fixed inset-0 bg-black/60 z-[100] flex items-center justify-center p-4">
            <div className={`border rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden flex flex-col max-h-full ${th.modalBg}`}>
              <div className={`p-4 border-b ${th.statsBorder} flex justify-between items-center ${th.modalHdrBg}`}>
                <h2 className={`text-lg font-bold flex items-center ${L ? 'text-slate-800' : 'text-white'}`}>
                  <UserPlus className={`w-5 h-5 mr-2 ${L ? 'text-[#800080]' : 'text-blue-400'}`} /> Admit New Patient
                </h2>
                <button onClick={() => setShowAddPatient(false)} className={L ? 'text-slate-500 hover:text-slate-800' : 'text-slate-400 hover:text-white'}><X className="w-5 h-5" /></button>
              </div>
              <div className="p-6 overflow-y-auto space-y-4" style={{ scrollbarWidth: 'thin' }}>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className={`block text-xs font-bold uppercase mb-1 ${th.modalLabel}`}>Patient ID / HADM ID</label>
                    <input type="text" value={newPatient.hadm_id} onChange={e => setNewPatient({...newPatient, hadm_id: e.target.value})} className={`w-full border rounded-lg px-3 py-2 text-sm ${th.modalInput}`} placeholder="e.g. 2845937" />
                    <div className={`text-[10px] mt-1 ${th.modalLabel} opacity-70`}>MIMIC HADM_ID — no patient name</div>
                  </div>
                  <div>
                    <label className={`block text-xs font-bold uppercase mb-1 ${th.modalLabel}`}>Chief Complaint</label>
                    <input type="text" value={newPatient.complaint} onChange={e => setNewPatient({...newPatient, complaint: e.target.value})} className={`w-full border rounded-lg px-3 py-2 text-sm ${th.modalInput}`} placeholder="e.g. Sepsis" />
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <label className={`block text-xs font-bold uppercase mb-1 ${th.modalLabel}`}>Age</label>
                    <input type="number" value={newPatient.age} onChange={e => setNewPatient({...newPatient, age: parseInt(e.target.value)})} className={`w-full border rounded-lg px-3 py-2 text-sm ${th.modalInput}`} />
                  </div>
                  <div>
                    <label className={`block text-xs font-bold uppercase mb-1 ${th.modalLabel}`}>Sex</label>
                    <select value={newPatient.sex} onChange={e => setNewPatient({...newPatient, sex: e.target.value})} className={`w-full border rounded-lg px-3 py-2 text-sm ${th.modalInput}`}>
                      <option>M</option><option>F</option>
                    </select>
                  </div>
                  <div>
                    <label className={`block text-xs font-bold uppercase mb-1 ${th.modalLabel}`}>Ward</label>
                    <select value={newPatient.ward} onChange={e => setNewPatient({...newPatient, ward: e.target.value})} className={`w-full border rounded-lg px-3 py-2 text-sm ${th.modalInput}`}>
                      <option>Ward 4B - Acute Care</option><option>Ward 7A - Step Down</option>
                    </select>
                  </div>
                </div>
                
                <h3 className={`text-sm font-bold border-b pb-2 mt-6 mb-4 ${L ? 'text-slate-700 border-[#e9d5ff]' : 'text-slate-300 border-slate-800'}`}>Initial Vitals</h3>
                <div className="grid grid-cols-3 gap-4">
                  {[
                    ['Heart Rate', 'hr', 'number'], ['Resp Rate', 'rr', 'number'], ['SpO2 (%)', 'spo2', 'number'],
                    ['Systolic BP', 'sbp', 'number'], ['Diastolic BP', 'dbp', 'number'], ['Temp (°C)', 'temp', 'number'],
                  ].map(([label, field, type]) => (
                    <div key={field}>
                      <label className={`block text-xs font-bold uppercase mb-1 ${th.modalLabel}`}>{label}</label>
                      <input type={type} step={field === 'temp' ? '0.1' : undefined} value={newPatient[field]} onChange={e => setNewPatient({...newPatient, [field]: parseFloat(e.target.value)})} className={`w-full border rounded-lg px-3 py-2 text-sm ${th.modalInput}`} />
                    </div>
                  ))}
                  <div>
                    <label className={`block text-xs font-bold uppercase mb-1 ${th.modalLabel}`}>Air/Oxygen</label>
                    <select value={newPatient.air_or_oxygen} onChange={e => setNewPatient({...newPatient, air_or_oxygen: e.target.value})} className={`w-full border rounded-lg px-3 py-2 text-sm ${th.modalInput}`}>
                      <option value="Air">Air</option><option value="Oxygen">Oxygen</option>
                    </select>
                  </div>
                  <div>
                    <label className={`block text-xs font-bold uppercase mb-1 ${th.modalLabel}`}>Consciousness</label>
                    <select value={newPatient.consciousness} onChange={e => setNewPatient({...newPatient, consciousness: e.target.value})} className={`w-full border rounded-lg px-3 py-2 text-sm ${th.modalInput}`}>
                      <option value="A">Alert (A)</option><option value="C">Confusion (C)</option>
                      <option value="V">Voice (V)</option><option value="P">Pain (P)</option>
                      <option value="U">Unresponsive (U)</option>
                    </select>
                  </div>
                  <div>
                    <label className={`block text-xs font-bold uppercase mb-1 ${th.modalLabel}`}>Resp Failure</label>
                    <select value={newPatient.hypercapnic_failure} onChange={e => setNewPatient({...newPatient, hypercapnic_failure: parseInt(e.target.value)})} className={`w-full border rounded-lg px-3 py-2 text-sm ${th.modalInput}`}>
                      <option value={0}>No (Scale 1)</option><option value={1}>Yes (Scale 2)</option>
                    </select>
                  </div>
                </div>
              </div>
              <div className={`p-4 border-t ${th.statsBorder} ${th.modalHdrBg} flex justify-end space-x-3`}>
                <button onClick={() => setShowAddPatient(false)} className={`px-4 py-2 rounded-lg text-sm font-bold transition-colors ${L ? 'text-slate-500 hover:text-slate-800' : 'text-slate-400 hover:text-white'}`}>Cancel</button>
                <button 
                  onClick={() => {
                    const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
                    fetch(`${API_URL}/api/patients`, {
                      method: 'POST', headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ ...newPatient, name: newPatient.hadm_id })
                    }).then(() => { setShowAddPatient(false); fetchData(); });
                  }} 
                  className={`px-4 py-2 rounded-lg text-sm font-bold flex items-center transition-colors ${th.btnPrimary}`}
                >
                  <Plus className="w-4 h-4 mr-1" /> Admit Patient
                </button>
              </div>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
