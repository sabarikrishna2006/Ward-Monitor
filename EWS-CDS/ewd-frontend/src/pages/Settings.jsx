import React, { useState, useEffect } from 'react';
import { Settings as SettingsIcon, Moon, Sun, Shield, Bell, Database, Monitor } from 'lucide-react';

export default function Settings() {
  const [isLightMode, setIsLightMode] = useState(() => document.documentElement.classList.contains('light'));

  // Keep in sync if theme toggled elsewhere (e.g., Dashboard header)
  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsLightMode(document.documentElement.classList.contains('light'));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  const toggleTheme = () => {
    const next = !isLightMode;
    setIsLightMode(next);
    if (next) {
      document.documentElement.classList.add('light');
      // Ensure no lingering filter hacks
      document.body.style.filter = 'none';
    } else {
      document.documentElement.classList.remove('light');
      document.body.style.filter = 'none';
    }
  };

  const L = isLightMode;

  const sectionClass = L
    ? 'bg-white border border-[#e9d5ff] rounded-xl overflow-hidden'
    : 'bg-[#0f172a] border border-slate-700 rounded-xl overflow-hidden';

  const sectionHeaderClass = L
    ? 'px-5 py-3.5 border-b border-[#e9d5ff] bg-[#f5f0ff] flex items-center'
    : 'px-5 py-3.5 border-b border-slate-800 bg-slate-900/50 flex items-center';

  const titleClass = L ? 'font-bold text-slate-800' : 'font-bold text-white';
  const bodyClass = L ? 'text-slate-700 font-bold' : 'text-slate-200 font-bold';
  const subClass = L ? 'text-xs text-slate-500 mt-0.5' : 'text-xs text-slate-400 mt-0.5';

  return (
    <div className={`p-6 md:p-8 h-full overflow-y-auto ${L ? 'bg-white' : 'bg-[#0b1120]'} ${L ? 'text-slate-800' : 'text-slate-300'}`}
      style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}
    >
      <h1 className={`text-xl font-bold mb-6 flex items-center ${L ? 'text-slate-900' : 'text-white'}`}>
        <SettingsIcon className={`mr-3 w-5 h-5 ${L ? 'text-[#800080]' : 'text-slate-400'}`} />
        System Settings
      </h1>

      <div className="max-w-3xl space-y-5">

        {/* ── Appearance ── */}
        <div className={sectionClass}>
          <div className={sectionHeaderClass}>
            <Monitor className={`w-4 h-4 mr-2 ${L ? 'text-[#800080]' : 'text-purple-400'}`} />
            <h2 className={titleClass}>Appearance</h2>
          </div>
          <div className="p-5 flex items-center justify-between">
            <div>
              <div className={bodyClass}>Theme Preference</div>
              <div className={subClass}>
                {L
                  ? 'Currently: Purple CareOS Light Mode — warm clinical purple interface'
                  : 'Currently: Dark Mode — high-contrast dark interface for low-light wards'}
              </div>
            </div>
            <button
              onClick={toggleTheme}
              className="flex items-center px-4 py-2.5 rounded-xl font-bold text-sm transition-all shadow-sm"
              style={{
                backgroundColor: L ? '#800080' : '#1e293b',
                color: '#ffffff',
                border: L ? '1px solid #6b0070' : '1px solid #334155',
              }}
              onMouseEnter={e => e.currentTarget.style.opacity = '0.85'}
              onMouseLeave={e => e.currentTarget.style.opacity = '1'}
            >
              {L
                ? <><Moon className="w-4 h-4 mr-2" />Switch to Dark</>
                : <><Sun className="w-4 h-4 mr-2 text-yellow-400" />Switch to Light</>}
            </button>
          </div>

          {/* Theme preview chips */}
          <div className={`px-5 pb-5 flex gap-3`}>
            {/* Dark mode chip */}
            <div
              onClick={() => { if (L) toggleTheme(); }}
              className={`flex-1 rounded-xl p-3 border-2 cursor-pointer transition-all ${!L ? 'border-[#800080] bg-[#1e293b]' : 'border-slate-200 bg-slate-50 opacity-60 hover:opacity-90'}`}
            >
              <div className="w-full h-2 rounded bg-[#0f172a] mb-1.5" />
              <div className="w-3/4 h-1.5 rounded bg-[#800080] mb-1" />
              <div className="w-1/2 h-1.5 rounded bg-slate-600" />
              <div className={`text-[10px] font-bold mt-2 ${!L ? 'text-white' : 'text-slate-500'}`}>Dark Mode</div>
            </div>
            {/* Light mode chip */}
            <div
              onClick={() => { if (!L) toggleTheme(); }}
              className={`flex-1 rounded-xl p-3 border-2 cursor-pointer transition-all ${L ? 'border-[#800080] bg-[#f5f0ff]' : 'border-slate-700 bg-[#0f172a] opacity-60 hover:opacity-90'}`}
            >
              <div className="w-full h-2 rounded bg-[#800080] mb-1.5" />
              <div className="w-3/4 h-1.5 rounded bg-[#d8b4fe] mb-1" />
              <div className="w-1/2 h-1.5 rounded bg-[#e9d5ff]" />
              <div className={`text-[10px] font-bold mt-2 ${L ? 'text-[#800080]' : 'text-slate-400'}`}>Purple Light Mode</div>
            </div>
          </div>
        </div>

        {/* ── Alert Configurations ── */}
        <div className={sectionClass}>
          <div className={sectionHeaderClass}>
            <Bell className="w-4 h-4 mr-2 text-pink-400" />
            <h2 className={titleClass}>Alert Configurations</h2>
          </div>
          <div className="p-5 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <div className={bodyClass}>Critical Audio Alarms</div>
                <div className={subClass}>Play sound for NEWS2 ≥ 7.</div>
              </div>
              <div className="w-12 h-6 bg-[#800080] rounded-full relative cursor-pointer shrink-0">
                <div className="absolute right-1 top-1 bg-white w-4 h-4 rounded-full shadow" />
              </div>
            </div>
            <div className={`flex items-center justify-between pt-4 border-t ${L ? 'border-[#e9d5ff]' : 'border-slate-800'}`}>
              <div>
                <div className={bodyClass}>Auto-Escalate to RRT</div>
                <div className={subClass}>Automatically page rapid response after 5 mins of unacknowledged critical alert.</div>
              </div>
              <div className={`w-12 h-6 rounded-full relative cursor-pointer shrink-0 ${L ? 'bg-slate-200' : 'bg-slate-700'}`}>
                <div className={`absolute left-1 top-1 w-4 h-4 rounded-full shadow ${L ? 'bg-slate-400' : 'bg-slate-400'}`} />
              </div>
            </div>
          </div>
        </div>

        {/* ── Security & Compliance ── */}
        <div className={sectionClass}>
          <div className={sectionHeaderClass}>
            <Shield className="w-4 h-4 mr-2 text-emerald-400" />
            <h2 className={titleClass}>Security & Compliance</h2>
          </div>
          <div className="p-5 space-y-3">
            {[
              { label: 'HIPAA-Ready Data Handling', detail: 'All PHI processed locally. No data leaves the hospital network.', active: true },
              { label: 'NABH-Compliant Alerts', detail: 'Alert thresholds aligned with NABH clinical standards.', active: true },
              { label: 'Audit Log', detail: 'All sign-ins and chart accesses are timestamped and stored locally.', active: true },
            ].map(({ label, detail, active }) => (
              <div key={label} className={`flex items-start justify-between gap-4 py-2 border-b last:border-0 ${L ? 'border-[#f0e8ff]' : 'border-slate-800'}`}>
                <div>
                  <div className={bodyClass}>{label}</div>
                  <div className={subClass}>{detail}</div>
                </div>
                <span className={`text-[10px] font-bold px-2 py-1 rounded-full shrink-0 ${active ? 'bg-emerald-500/20 text-emerald-400' : 'bg-slate-700 text-slate-400'}`}>
                  {active ? 'ACTIVE' : 'OFF'}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* ── Data Source ── */}
        <div className={sectionClass}>
          <div className={sectionHeaderClass}>
            <Database className="w-4 h-4 mr-2 text-blue-400" />
            <h2 className={titleClass}>Data Source</h2>
          </div>
          <div className="p-5">
            <div className={bodyClass}>MIMIC-IV De-identified Dataset</div>
            <div className={subClass}>
              All patient records are sourced from MIMIC-IV. Patient names are suppressed; identifiers use HADM_ID only.
            </div>
            <div className="mt-3 flex items-center gap-2">
              <span className="text-[10px] font-bold px-2 py-1 rounded-full bg-blue-500/20 text-blue-400">De-identified</span>
              <span className="text-[10px] font-bold px-2 py-1 rounded-full bg-purple-500/20 text-purple-400">HADM_ID Mapped</span>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
