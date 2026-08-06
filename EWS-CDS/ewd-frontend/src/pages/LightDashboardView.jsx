import React from 'react';
import { Search, ChevronDown, Bell, User, Activity, AlertTriangle, CheckSquare, Heart, Droplets, PhoneForwarded, PlayCircle, UserPlus, Shield, Sun, Moon, LayoutDashboard, Users, FileText, LogOut } from 'lucide-react';

export default function LightDashboardView({
  filteredPatients,
  stats,
  searchTerm,
  setSearchTerm,
  selectedWard,
  setSelectedWard,
  timeStr,
  isReplay,
  setIsReplay,
  setShowAddPatient,
  isLightMode,
  setIsLightMode,
  criticalPatients,
  navigate
}) {
  const COL_BED       = 'w-16';
  const COL_PATIENT   = 'w-48';
  const COL_SCORE     = 'w-36';
  const COL_COMPLAINT = 'w-64';
  const COL_VITALS    = 'flex-1';

  return (
    <div className="flex h-screen bg-[#fafafa] text-slate-800 font-sans overflow-hidden">
      
      {/* ══════════════════════════════════════════════════════
          SIDEBAR
      ══════════════════════════════════════════════════════ */}
      <aside className="w-64 flex flex-col shrink-0 text-white relative z-20 shadow-2xl" style={{backgroundColor: '#200427'}}>
        <div className="p-6">
          <div className="flex items-center space-x-3 mb-1">
            <svg width="28" height="28" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
              <polygon points="0,0 100,0 0,100" fill="#000000" />
              <polygon points="0,100 100,100 100,0" fill="#800080" />
              <polygon points="0,80 20,100 0,100" fill="#000000" />
            </svg>
            <h1 className="text-xl font-bold tracking-tight leading-none">foqal<br/><span className="font-light text-[#d8b4fe] text-xs">analytics</span></h1>
          </div>
          <div className="text-[#a8249c] text-[10px] font-bold tracking-widest uppercase ml-[40px]">CareOS · Cardiology</div>
        </div>

        <div className="mt-8 px-4 flex-1">
          <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-4 px-4">Workflows</div>
          
          <nav className="space-y-1">
            <a href="#" className="flex items-center space-x-3 px-4 py-3 rounded-lg bg-[#800080]/20 border-l-2 border-[#800080] text-white">
              <LayoutDashboard className="w-4 h-4 text-[#d8b4fe]" />
              <span className="font-medium text-sm">Dashboard</span>
            </a>
            
            <a href="#" className="flex items-center space-x-3 px-4 py-3 rounded-lg text-slate-400 hover:bg-white/5 hover:text-white transition-colors border-l-2 border-transparent">
              <Users className="w-4 h-4" />
              <span className="font-medium text-sm">Patients</span>
            </a>
            
            <a href="#" className="flex items-center space-x-3 px-4 py-3 rounded-lg text-slate-400 hover:bg-white/5 hover:text-white transition-colors border-l-2 border-transparent">
              <FileText className="w-4 h-4" />
              <span className="font-medium text-sm">Reports</span>
            </a>
          </nav>
        </div>

        <div className="p-6">
          <div className="inline-flex items-center space-x-2 bg-emerald-900/30 border border-emerald-500/30 px-3 py-1.5 rounded-full">
            <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            <span className="text-[10px] font-bold text-emerald-400 uppercase tracking-wider">System Healthy</span>
          </div>
          <div className="text-[10px] text-slate-500 mt-3">Foqal Analytics · CareOS v1.0</div>
        </div>
      </aside>

      {/* ══════════════════════════════════════════════════════
          MAIN CONTENT AREA
      ══════════════════════════════════════════════════════ */}
      <div className="flex-1 flex flex-col overflow-hidden relative">
        
        {/* TOP BAR */}
        <header className="h-16 flex items-center justify-between px-8 bg-white border-b border-slate-200 shrink-0 z-10 shadow-sm">
          
          <div className="flex items-center text-sm">
            <span className="text-slate-400">Workflows <span className="mx-2">&gt;</span></span>
            <span className="font-bold text-slate-800">Dashboard</span>
          </div>

          <div className="flex items-center space-x-6">
            <div className="flex items-center space-x-4">
              <span className="text-slate-400 text-xs font-medium">{timeStr}</span>
              
              <div className="relative">
                <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  type="text"
                  placeholder="Search patients..."
                  value={searchTerm}
                  onChange={e => setSearchTerm(e.target.value)}
                  className="pl-9 pr-4 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#800080]/20 focus:border-[#800080] transition-all w-64 placeholder-slate-400 text-slate-800"
                />
              </div>

              <select 
                value={selectedWard}
                onChange={(e) => setSelectedWard(e.target.value)}
                className="bg-slate-50 border border-slate-200 text-slate-700 text-sm py-2 px-3 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#800080]/20 focus:border-[#800080] cursor-pointer"
              >
                <option value="All">All Wards</option>
                <option value="Ward 4B - Acute Care">Ward 4B — Acute Care / ICU</option>
                <option value="Ward 7A - Step Down">Ward 7A — Step Down</option>
              </select>

              <button 
                onClick={() => setIsReplay(!isReplay)} 
                className={`flex items-center space-x-1 px-3 py-2 rounded-lg text-sm font-medium transition-colors border ${isReplay ? 'bg-blue-50 text-blue-600 border-blue-200' : 'bg-slate-50 text-slate-600 border-slate-200 hover:bg-slate-100'}`}
              >
                <PlayCircle className={`w-4 h-4 ${isReplay ? 'animate-pulse' : ''}`} />
                <span>{isReplay ? 'Replaying' : 'Mock Replay'}</span>
              </button>

              <button 
                onClick={() => setShowAddPatient(true)} 
                className="flex items-center space-x-1 px-3 py-2 rounded-lg bg-slate-50 border border-slate-200 text-slate-600 text-sm font-medium hover:bg-slate-100 transition-colors"
              >
                <UserPlus className="w-4 h-4" />
                <span>Admit</span>
              </button>

              <button
                onClick={() => setIsLightMode(!isLightMode)}
                className="p-2 hover:bg-slate-100 rounded-full transition-colors text-slate-500"
                title="Toggle Light/Dark Theme"
              >
                {isLightMode ? <Moon className="w-5 h-5" /> : <Sun className="w-5 h-5" />}
              </button>
            </div>

            <div className="flex items-center space-x-3 pl-6 border-l border-slate-200">
              <div className="w-10 h-10 rounded-lg bg-[#800080] flex items-center justify-center text-white font-bold shadow-md shadow-[#800080]/20">
                AV
              </div>
              <div className="text-left hidden lg:block">
                <p className="text-sm font-bold text-slate-800 leading-tight">Ashmit Verma</p>
                <p className="text-[10px] text-slate-400 font-medium tracking-wide uppercase">ASHMIT24134@IIITD.AC.IN</p>
              </div>
              <button onClick={() => navigate('/')} className="ml-2 p-2 hover:bg-slate-100 rounded-lg text-slate-400 transition-colors">
                <LogOut className="w-4 h-4" />
              </button>
            </div>
          </div>
        </header>

        {/* DASHBOARD BODY */}
        <main className="flex-1 overflow-auto p-8 relative">
          
          <div className="mb-6 flex items-center space-x-3">
            <div className="h-0.5 w-4 bg-[#800080]"></div>
            <h2 className="text-xs font-black text-[#800080] tracking-widest uppercase">Pipeline Dashboard</h2>
          </div>

          <h1 className="text-3xl font-black text-slate-900 mb-8 tracking-tight">
            Early Warning <span className="text-[#800080]">Dashboard</span>
          </h1>

          {/* STATS CARDS */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
            <div className="bg-white rounded-xl p-6 shadow-sm border border-slate-200 relative overflow-hidden group">
              <div className="absolute -right-6 -top-6 w-32 h-32 bg-blue-500/5 rounded-full blur-3xl group-hover:bg-blue-500/10 transition-colors"></div>
              <div className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">Total Patients</div>
              <div className="text-4xl font-black text-slate-800 mb-4">{stats.total}</div>
              <div className="inline-flex items-center px-2.5 py-1 rounded-full bg-slate-100 text-slate-600 text-xs font-medium">
                • Monitored locally
              </div>
            </div>

            <div className="bg-white rounded-xl p-6 shadow-sm border border-slate-200 relative overflow-hidden group">
              <div className="absolute -right-6 -top-6 w-32 h-32 bg-orange-500/5 rounded-full blur-3xl group-hover:bg-orange-500/10 transition-colors"></div>
              <div className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">Medium Risk (Warning)</div>
              <div className="text-4xl font-black text-slate-800 mb-4">{stats.warning}</div>
              <div className="inline-flex items-center px-2.5 py-1 rounded-full bg-orange-50 text-orange-600 text-xs font-medium">
                • Needs urgent review
              </div>
            </div>

            <div className="bg-white rounded-xl p-6 shadow-sm border border-slate-200 relative overflow-hidden group">
              <div className="absolute -right-6 -top-6 w-32 h-32 bg-red-500/5 rounded-full blur-3xl group-hover:bg-red-500/10 transition-colors"></div>
              <div className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">High Risk (Critical)</div>
              <div className="text-4xl font-black text-slate-800 mb-4">{stats.critical}</div>
              <div className="inline-flex items-center px-2.5 py-1 rounded-full bg-red-50 text-red-600 text-xs font-medium font-bold">
                ↑ Emergent response
              </div>
            </div>
          </div>

          {/* ACUITY TABLE */}
          <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden mb-8">
            <div className="px-6 py-4 border-b border-slate-200 flex justify-between items-center bg-slate-50/50">
              <h3 className="text-xs font-bold text-slate-500 uppercase tracking-widest">Active Queue by Acuity</h3>
              <div className="flex space-x-6 text-[10px] font-bold uppercase tracking-wider">
                <span className="flex items-center"><span className="w-2 h-2 rounded-full bg-red-500 mr-1.5" /> ≥ 7 Critical</span>
                <span className="flex items-center"><span className="w-2 h-2 rounded-full bg-orange-500 mr-1.5" /> 5-6 Warning</span>
                <span className="flex items-center"><span className="w-2 h-2 rounded-full bg-emerald-500 mr-1.5" /> 0-4 Stable</span>
              </div>
            </div>

            {/* Table Header */}
            <div className="flex items-center bg-white border-b border-slate-200 text-[10px] font-bold text-slate-400 uppercase tracking-widest shrink-0">
              <div className={`p-3 border-r border-slate-200 text-center ${COL_BED}`}>Bed</div>
              <div className={`p-3 border-r border-slate-200 ${COL_PATIENT}`}>Patient / MRN</div>
              <div className={`p-3 border-r border-slate-200 text-center ${COL_SCORE}`}>Score</div>
              <div className={`p-3 border-r border-slate-200 ${COL_COMPLAINT}`}>Complaint / Flag</div>
              <div className={`p-3 flex items-center justify-between ${COL_VITALS}`}>
                <span className="w-1/5 text-center">HR</span>
                <span className="w-1/5 text-center">RR</span>
                <span className="w-1/5 text-center">SPO2</span>
                <span className="w-1/5 text-center">BP</span>
                <span className="w-1/5 text-center">TEMP</span>
              </div>
            </div>

            {/* Patient Rows */}
            <div className="divide-y divide-slate-100">
              {filteredPatients.map(patient => {
                let s = { 
                  bg: 'hover:bg-slate-50', 
                  borderLeft: 'border-l-4 border-emerald-500', 
                  newsBg: 'bg-emerald-50', 
                  newsText: 'text-emerald-700', 
                  newsBorder: 'border-emerald-200' 
                };
                if (patient.status === 'critical') {
                  s = { 
                    bg: 'bg-red-50/30 hover:bg-red-50/60', 
                    borderLeft: 'border-l-4 border-red-500', 
                    newsBg: 'bg-red-100', 
                    newsText: 'text-red-700', 
                    newsBorder: 'border-red-200' 
                  };
                } else if (patient.status === 'warning') {
                  s = { 
                    bg: 'bg-orange-50/30 hover:bg-orange-50/60', 
                    borderLeft: 'border-l-4 border-orange-500', 
                    newsBg: 'bg-orange-100', 
                    newsText: 'text-orange-700', 
                    newsBorder: 'border-orange-200' 
                  };
                }

                return (
                  <div key={patient.id} className={`flex items-stretch transition-colors cursor-pointer group ${s.bg} ${s.borderLeft}`}>
                    
                    <div className={`${COL_BED} flex items-center justify-center p-3 border-r border-slate-100`}>
                      <span className="font-bold text-slate-600 text-sm">{patient.room}-{patient.bed}</span>
                    </div>

                    <div className={`${COL_PATIENT} flex flex-col justify-center py-3 px-4 border-r border-slate-100`}>
                      <div className="font-bold text-slate-800 text-sm leading-tight truncate">{patient.name}</div>
                      <div className="text-[11px] text-slate-500 mt-0.5">{patient.id}</div>
                      <div className="text-[11px] text-slate-400">{patient.age}y {patient.sex}</div>
                    </div>

                    <div className={`${COL_SCORE} flex items-center justify-center gap-2 border-r border-slate-100 px-2 py-3`}>
                      <div className={`flex flex-col items-center justify-center rounded-lg border px-2 py-1.5 min-w-[44px] ${s.newsBorder} ${s.newsBg}`}>
                        <span className={`text-[8px] font-black uppercase tracking-wider ${s.newsText}`}>NEWS2</span>
                        <span className={`text-2xl font-black leading-none mt-0.5 ${s.newsText}`}>{patient.news2}</span>
                      </div>
                      <div className={`flex flex-col items-center justify-center rounded-lg border px-2 py-1.5 min-w-[44px] border-slate-200 bg-white`}>
                        <span className="text-[8px] font-black uppercase tracking-wider text-slate-500">ML%</span>
                        <span className="text-2xl font-black text-slate-700 leading-none mt-0.5">{patient.mlRisk}</span>
                      </div>
                    </div>

                    <div className={`${COL_COMPLAINT} flex flex-col justify-center py-3 px-4 border-r border-slate-100`}>
                      <span className="text-[11px] text-slate-700 font-semibold leading-snug line-clamp-2">
                        {patient.complaint}
                      </span>
                      {patient.briefFlag && (
                        <span className={`text-[10px] font-bold leading-snug mt-1.5 line-clamp-2 ${
                          patient.status === 'critical' ? 'text-red-600' : patient.status === 'warning' ? 'text-orange-600' : 'text-slate-500'
                        }`}>
                          ⚠ {patient.briefFlag}
                        </span>
                      )}
                      {patient.drugLabAlerts && patient.drugLabAlerts.length > 0 && (
                        <span className="mt-1.5 inline-block text-[10px] px-2 py-0.5 rounded border bg-amber-50 border-amber-200 text-amber-700 font-bold w-max shadow-sm">
                          💊 Drug-Lab Alert
                        </span>
                      )}
                    </div>

                    <div className={`${COL_VITALS} flex items-center p-2`}>
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
                          <div key={key} className="flex-1 flex flex-col items-center justify-center h-full px-1 border-r border-slate-100 last:border-0 relative">
                            <span className="text-base font-bold text-slate-800">{displayVal}</span>
                            <span className="text-[8px] text-slate-400 uppercase font-bold tracking-wider mt-0.5">{unit}</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
              
              {filteredPatients.length === 0 && (
                <div className="p-8 text-center text-slate-500 text-sm font-medium">
                  No patients found matching your criteria.
                </div>
              )}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
