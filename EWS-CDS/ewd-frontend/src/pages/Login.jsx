import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, ShieldCheck, Zap, Lock, User, ArrowRight } from 'lucide-react';

export default function Login() {
  const navigate = useNavigate();
  const [nurseId, setNurseId] = useState('');
  const [password, setPassword] = useState('');

  const handleLogin = (e) => {
    e.preventDefault();
    // In a real app, authenticate with backend here
    if (nurseId && password) {
      navigate('/ward');
    }
  };

  return (
    <div className="flex h-screen bg-obsidian text-slate-200 overflow-hidden">
      
      {/* Left Panel: Product Features & Assurance */}
      <div className="hidden lg:flex lg:w-1/2 bg-slate-900 relative overflow-hidden flex-col justify-between p-10 border-r border-slate-800">
        
        <div className="absolute inset-0 bg-[url('https://images.unsplash.com/photo-1551076805-e1869033e561?q=80&w=2574&auto=format&fit=crop')] bg-cover bg-center opacity-10 mix-blend-luminosity"></div>
        <div className="absolute inset-0 bg-gradient-to-t from-obsidian via-obsidian/80 to-transparent"></div>

        <div className="relative z-10">
          <div className="flex items-center space-x-3 mb-8">
            <div className="bg-criticalRed p-3 rounded-xl shadow-lg shadow-criticalRed/20">
              <Activity className="w-8 h-8 text-white" />
            </div>
            <span className="text-3xl font-bold tracking-wide text-white">EWD<span className="text-slate-400 font-light">Monitor</span></span>
          </div>

          <h1 className="text-3xl font-bold text-white mb-4 leading-tight">
            Targeted Real-time<br/>
            <span className="text-stableTeal">Early Warning System</span>
          </h1>
          <p className="text-base text-slate-400 max-w-md mb-8">
            Empowering critical care teams to detect physiological deterioration before it happens. Built for the modern clinical workflow.
          </p>

          <div className="space-y-5">
            <div className="flex items-start space-x-4">
              <div className="bg-stableTeal/10 p-3 rounded-lg border border-stableTeal/20 mt-1">
                <Zap className="w-6 h-6 text-stableTeal" />
              </div>
              <div>
                <h3 className="text-xl font-semibold text-white">Zero-Click Interpretation</h3>
                <p className="text-slate-400 mt-1">Actionable alerts that explicitly highlight driving factors, requiring no extra clicks to understand patient acuity.</p>
              </div>
            </div>
            
            <div className="flex items-start space-x-4">
              <div className="bg-warningAmber/10 p-3 rounded-lg border border-warningAmber/20 mt-1">
                <Activity className="w-6 h-6 text-warningAmber" />
              </div>
              <div>
                <h3 className="text-xl font-semibold text-white">Continuous Trajectories</h3>
                <p className="text-slate-400 mt-1">Real-time integration with bedside monitors provides seamless sparklines directly in the ward triage view.</p>
              </div>
            </div>

            <div className="flex items-start space-x-4">
              <div className="bg-blue-500/10 p-3 rounded-lg border border-blue-500/20 mt-1">
                <ShieldCheck className="w-6 h-6 text-blue-500" />
              </div>
              <div>
                <h3 className="text-xl font-semibold text-white">Clinical Assurance</h3>
                <p className="text-slate-400 mt-1">Explainable AI models transparently show the 'Why' behind every early warning alert and recommend next steps.</p>
              </div>
            </div>
          </div>
        </div>
        
        <div className="relative z-10 text-slate-500 text-sm">
          &copy; 2026 Hospital Systems Inc. • HIPAA Compliant
        </div>
      </div>

      {/* Right Panel: Login Form */}
      <div className="w-full lg:w-1/2 flex items-start justify-center pt-12 p-8 bg-obsidian relative">
        
        {/* Subtle background glow */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 bg-stableTeal/5 rounded-full blur-3xl pointer-events-none"></div>

        <div className="w-full max-w-md relative z-10">
          <div className="text-center mb-7">
            <h2 className="text-3xl font-bold text-white mb-2">Welcome back</h2>
            <p className="text-slate-400">Please authenticate to access the ward monitor</p>
          </div>

          <form onSubmit={handleLogin} className="space-y-6">
            <div className="space-y-2">
              <label className="text-sm font-medium text-slate-300 ml-1">Staff ID</label>
              <div className="relative">
                <User className="w-5 h-5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
                <input 
                  type="text" 
                  required
                  placeholder="Enter your Nurse or Doctor ID" 
                  className="w-full bg-slate-900 border border-slate-700 text-white pl-10 pr-4 py-3 rounded-xl focus:outline-none focus:border-stableTeal focus:ring-1 focus:ring-stableTeal transition-all shadow-inner"
                  value={nurseId}
                  onChange={(e) => setNurseId(e.target.value)}
                />
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between ml-1">
                <label className="text-sm font-medium text-slate-300">Password</label>
                <a href="#" className="text-xs text-stableTeal hover:text-teal-400 transition-colors">Forgot password?</a>
              </div>
              <div className="relative">
                <Lock className="w-5 h-5 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
                <input 
                  type="password" 
                  required
                  placeholder="Enter your password" 
                  className="w-full bg-slate-900 border border-slate-700 text-white pl-10 pr-4 py-3 rounded-xl focus:outline-none focus:border-stableTeal focus:ring-1 focus:ring-stableTeal transition-all shadow-inner"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>
            </div>

            <button 
              type="submit"
              className="w-full flex items-center justify-center space-x-2 bg-stableTeal hover:bg-teal-500 text-white font-medium py-3 px-4 rounded-xl transition-all shadow-lg shadow-stableTeal/20 mt-4 group"
            >
              <span>Secure Login</span>
              <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
            </button>
          </form>
          
          <div className="mt-8 text-center text-sm text-slate-500">
            Secure connection established. All access is logged.
          </div>
        </div>
      </div>
    </div>
  );
}
