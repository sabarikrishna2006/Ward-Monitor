import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Brain, Zap, ShieldCheck, Lock, ArrowRight, Sun, Moon } from 'lucide-react';

const FEATURES = [
  {
    Icon: Brain,
    title: 'ML-Based Deterioration Prediction',
    desc: 'XGBoost models predict patient deterioration up to 6 hours in advance.',
  },
  {
    Icon: Zap,
    title: 'Zero-Click Clinical Intelligence',
    desc: 'NEWS2 alerts fire automatically — no manual chart review needed.',
  },
  {
    Icon: ShieldCheck,
    title: 'Explainable AI — Every Alert Justified',
    desc: 'Every ML prediction comes with a traceable factor breakdown.',
  },
];

export default function Login() {
  const navigate = useNavigate();
  const [staffId, setStaffId] = useState('');
  const [password, setPassword] = useState('');
  const [isDark, setIsDark] = useState(() => !document.documentElement.classList.contains('light'));

  const toggleTheme = () => {
    const goLight = isDark; // if currently dark → go light
    setIsDark(!goLight);
    if (goLight) document.documentElement.classList.add('light');
    else document.documentElement.classList.remove('light');
  };

  const handleLogin = (e) => {
    e.preventDefault();
    if (staffId && password) navigate('/ward');
  };

  /* ── Shared left-panel content (always dark purple bg) ── */
  const LeftPanel = () => (
    <div
      className="hidden lg:flex lg:w-[52%] flex-col h-full p-10 xl:p-12"
      style={{ backgroundColor: '#200427' }}
    >
      {/* Logo */}
      <div className="flex items-center space-x-3 mb-7">
        <svg width="48" height="48" viewBox="0 0 100 100">
          <polygon points="0,0 100,0 0,100" fill="#000" />
          <polygon points="0,100 100,100 100,0" fill="#800080" />
          <polygon points="0,80 20,100 0,100" fill="#000" />
        </svg>
        <div>
          <div className="text-white text-2xl font-bold leading-none">
            foqal<span className="font-light text-[#d8b4fe]"> analytics</span>
          </div>
          <div className="text-[#a8249c] text-[10px] font-bold tracking-widest uppercase mt-0.5">
            EWS · Deterioration System
          </div>
        </div>
      </div>

      {/* Hero */}
      <div className="mb-6">
        <div className="text-[9px] font-bold text-[#a8249c] tracking-widest uppercase mb-3">
          Early Warning Patient Deterioration System
        </div>
        <h1 className="text-2xl xl:text-3xl font-black text-white leading-tight mb-3">
          Detect patient deterioration<br />
          <span className="text-[#d8b4fe]">before it's a crisis.</span>
        </h1>
        <p className="text-[#a18ba6] text-xs leading-relaxed max-w-sm">
          A real-time clinical intelligence platform that monitors continuous vitals, computes
          validated NEWS2 scores, flags dangerous drug-lab interactions, and surfaces explainable ML predictions.
        </p>
      </div>

      {/* Features */}
      <div className="flex flex-col gap-4 flex-1">
        {FEATURES.map(({ Icon, title, desc }) => (
          <div key={title} className="flex items-start space-x-3">
            <div className="w-8 h-8 rounded-lg flex items-center justify-center bg-[#800080]/20 border border-[#800080]/30 shrink-0 mt-0.5">
              <Icon className="w-4 h-4 text-[#d8b4fe]" />
            </div>
            <div>
              <div className="text-white text-xs font-bold">{title}</div>
              <div className="text-[#a18ba6] text-[11px] mt-0.5 leading-relaxed">{desc}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Compliance badges */}
      <div className="flex flex-wrap gap-2 pt-6">
        {['NABH-Compliant', 'HIPAA-Ready', 'Local-First', 'On-Premise Deployment'].map(tag => (
          <span key={tag} className="text-[9px] font-bold text-[#a18ba6] uppercase tracking-widest border border-[#a8249c]/20 px-2 py-0.5 rounded-full">
            {tag}
          </span>
        ))}
      </div>
    </div>
  );

  if (!isDark) {
    /* ─────────────────── LIGHT MODE ─────────────────── */
    return (
      <div className="flex h-screen w-screen font-sans overflow-hidden" style={{ backgroundColor: '#200427' }}>
        <LeftPanel />

        {/* Right — white login form */}
        <div className="w-full lg:w-[48%] flex items-center justify-center p-6 lg:p-8 bg-white h-full relative">
          {/* Theme toggle */}
          <button
            onClick={toggleTheme}
            className="absolute top-4 right-4 z-50 flex items-center gap-2 px-3 py-1.5 bg-white border border-slate-200 rounded-full text-slate-500 text-xs font-medium shadow-sm hover:bg-slate-50 transition-colors"
          >
            <Moon className="w-3.5 h-3.5" /> Dark Mode
          </button>

          <div className="w-full max-w-[380px]">
            {/* Mobile logo */}
            <div className="flex items-center space-x-3 mb-7 lg:hidden">
              <svg width="40" height="40" viewBox="0 0 100 100">
                <polygon points="0,0 100,0 0,100" fill="#000" />
                <polygon points="0,100 100,100 100,0" fill="#800080" />
                <polygon points="0,80 20,100 0,100" fill="#000" />
              </svg>
              <div>
                <div className="text-slate-900 text-xl font-bold">foqal<span className="font-light text-[#800080]"> analytics</span></div>
                <div className="text-[#a8249c] text-[9px] font-bold tracking-widest uppercase">EWS · Deterioration System</div>
              </div>
            </div>

            <div className="mb-5">
              <h2 className="text-2xl font-black text-slate-900 mb-1">Sign in to your workspace</h2>
              <p className="text-slate-500 text-xs">Early Warning Patient Deterioration System</p>
            </div>

            <form onSubmit={handleLogin} className="space-y-4">
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-700">Hospital email or Staff ID</label>
                <input
                  type="text"
                  required
                  placeholder="name@hospital.edu.in"
                  className="w-full bg-white border border-slate-200 text-slate-900 px-3 py-2.5 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#800080]/30 focus:border-[#800080] transition-all placeholder-slate-400"
                  value={staffId}
                  onChange={e => setStaffId(e.target.value)}
                />
              </div>

              <div className="space-y-1">
                <div className="flex justify-between items-center">
                  <label className="text-xs font-semibold text-slate-700">Password</label>
                  <a href="#" className="text-xs font-medium hover:underline" style={{ color: '#800080' }}>Forgot?</a>
                </div>
                <input
                  type="password"
                  required
                  className="w-full bg-white border border-slate-200 text-slate-900 px-3 py-2.5 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#800080]/30 focus:border-[#800080] transition-all"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                />
              </div>

              <button
                type="submit"
                className="w-full flex items-center justify-center space-x-2 text-white font-bold py-2.5 px-4 rounded-lg transition-all"
                style={{ backgroundColor: '#800080' }}
                onMouseEnter={e => e.currentTarget.style.backgroundColor = '#6b0070'}
                onMouseLeave={e => e.currentTarget.style.backgroundColor = '#800080'}
              >
                <span>Sign In</span>
                <ArrowRight className="w-4 h-4" />
              </button>
            </form>

            <div className="mt-5 text-center space-y-2">
              <p className="text-[11px] text-slate-500 leading-relaxed max-w-xs mx-auto">
                All patient data is processed locally on hospital servers.<br />
                Sign-in is audited and tied to your clinical identity.
              </p>
              <div className="flex items-center justify-center gap-4 pt-1">
                <span className="flex items-center gap-1 text-[10px] text-slate-400 font-medium">
                  <ShieldCheck className="w-3 h-3 text-emerald-500" />HIPAA Ready
                </span>
                <span className="flex items-center gap-1 text-[10px] text-slate-400 font-medium">
                  <Lock className="w-3 h-3 text-[#800080]" />No PHI leaves the network
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  /* ─────────────────── DARK MODE ─────────────────── */
  return (
    <div className="flex h-screen w-screen bg-[#0a0f1c] text-slate-200 overflow-hidden font-sans" style={{ backgroundColor: '#0a0f1c' }}>

      {/* Left Panel — same dark purple */}
      <div className="hidden lg:flex lg:w-[52%] flex-col h-full p-10 xl:p-12 relative overflow-hidden" style={{ backgroundColor: '#0f172a', borderRight: '1px solid #1e293b' }}>
        <div className="absolute inset-0 bg-gradient-to-br from-[#800080]/10 via-transparent to-transparent pointer-events-none" />

        <div className="relative z-10 flex flex-col h-full">
          {/* Logo */}
          <div className="flex items-center space-x-3 mb-7">
            <svg width="48" height="48" viewBox="0 0 100 100">
              <polygon points="0,0 100,0 0,100" fill="#000" />
              <polygon points="0,100 100,100 100,0" fill="#800080" />
              <polygon points="0,80 20,100 0,100" fill="#000" />
            </svg>
            <div>
              <div className="text-white text-2xl font-bold leading-none">
                foqal<span className="font-light text-[#d8b4fe]"> analytics</span>
              </div>
              <div className="text-[#a8249c] text-[10px] font-bold tracking-widest uppercase mt-0.5">
                EWS · Deterioration System
              </div>
            </div>
          </div>

          {/* Hero */}
          <div className="mb-6">
            <div className="text-[9px] font-bold text-[#800080] tracking-widest uppercase mb-3">
              Early Warning Patient Deterioration System
            </div>
            <h1 className="text-2xl xl:text-3xl font-black text-white leading-tight mb-3">
              Detect patient deterioration<br />
              <span className="text-[#d8b4fe]">before it's a crisis.</span>
            </h1>
            <p className="text-slate-400 text-xs max-w-sm leading-relaxed">
              Real-time NEWS2 monitoring, explainable ML predictions, and drug-lab interaction alerts — built for hospital wards.
            </p>
          </div>

          {/* Features */}
          <div className="flex flex-col gap-5 flex-1">
            {FEATURES.map(({ Icon, title, desc }) => (
              <div key={title} className="flex items-start space-x-3">
                <div className="bg-[#800080]/10 p-2 rounded-lg border border-[#800080]/20 mt-0.5 shrink-0">
                  <Icon className="w-5 h-5 text-[#d8b4fe]" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-white">{title}</h3>
                  <p className="text-slate-400 text-xs mt-0.5 leading-relaxed max-w-[85%]">{desc}</p>
                </div>
              </div>
            ))}
          </div>

          <div className="text-slate-600 text-xs pt-4">
            © 2026 Foqal Analytics · CareOS P2 · All data de-identified · HIPAA-Ready
          </div>
        </div>
      </div>

      {/* Right — Dark login form */}
      <div className="w-full lg:w-[48%] flex items-center justify-center p-6 lg:p-8 h-full relative" style={{ backgroundColor: '#0a0f1c' }}>
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-80 h-80 bg-[#800080]/5 rounded-full blur-3xl pointer-events-none" />

        {/* Theme toggle */}
        <button
          onClick={toggleTheme}
          className="absolute top-4 right-4 z-50 flex items-center gap-2 px-3 py-1.5 bg-slate-800 border border-slate-700 rounded-full text-slate-400 text-xs font-medium hover:text-white transition-colors"
        >
          <Sun className="w-3.5 h-3.5" /> Light Mode
        </button>

        <div className="w-full max-w-md relative z-10">
          {/* Mobile logo */}
          <div className="flex items-center space-x-3 mb-8 lg:hidden">
            <svg width="40" height="40" viewBox="0 0 100 100">
              <polygon points="0,0 100,0 0,100" fill="#000" />
              <polygon points="0,100 100,100 100,0" fill="#800080" />
              <polygon points="0,80 20,100 0,100" fill="#000" />
            </svg>
            <div className="text-white text-xl font-bold">foqal<span className="font-light text-[#800080]"> analytics</span></div>
          </div>

          <div className="mb-6">
            <h2 className="text-2xl font-black text-white mb-1">Sign in to your workspace</h2>
            <p className="text-slate-400 text-sm">Authenticate to access the ward monitor</p>
          </div>

          <form onSubmit={handleLogin} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-sm font-semibold text-slate-300 ml-1">Staff ID or Hospital Email</label>
              <input
                type="text"
                required
                placeholder="staff_id or name@hospital.in"
                className="w-full bg-slate-900 border border-slate-700 text-white px-4 py-2.5 rounded-xl text-sm focus:outline-none focus:border-[#800080] transition-all placeholder-slate-600"
                value={staffId}
                onChange={e => setStaffId(e.target.value)}
              />
            </div>

            <div className="space-y-1.5">
              <div className="flex justify-between items-center ml-1">
                <label className="text-sm font-semibold text-slate-300">Password</label>
                <a href="#" className="text-xs text-[#c084fc] hover:underline">Forgot password?</a>
              </div>
              <input
                type="password"
                required
                placeholder="Enter your password"
                className="w-full bg-slate-900 border border-slate-700 text-white px-4 py-2.5 rounded-xl text-sm focus:outline-none focus:border-[#800080] transition-all placeholder-slate-600"
                value={password}
                onChange={e => setPassword(e.target.value)}
              />
            </div>

            <button
              type="submit"
              className="w-full flex items-center justify-center space-x-2 text-white font-bold py-3 px-4 rounded-xl transition-all group mt-2"
              style={{ background: '#800080', boxShadow: '0 4px 20px rgba(128,0,128,0.3)' }}
              onMouseEnter={e => e.currentTarget.style.background = '#6b0070'}
              onMouseLeave={e => e.currentTarget.style.background = '#800080'}
            >
              <span>Secure Login</span>
              <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
            </button>
          </form>

          <div className="mt-6 text-center space-y-2">
            <p className="text-slate-500 text-xs">Secure connection. All access is logged and audited.</p>
            <div className="flex items-center justify-center gap-4 pt-1">
              <span className="flex items-center gap-1 text-[10px] text-slate-500">
                <ShieldCheck className="w-3 h-3 text-emerald-500" />HIPAA Ready
              </span>
              <span className="flex items-center gap-1 text-[10px] text-slate-500">
                <Lock className="w-3 h-3 text-[#800080]" />PHI stays local
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
