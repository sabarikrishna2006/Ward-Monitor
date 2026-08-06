import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Activity, Heart, Droplets, AlertTriangle, Lightbulb, FileText } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';

const mockVitalHistory = [
  { time: '08:00', hr: 85, bpSys: 110, bpDia: 70, spo2: 98 },
  { time: '09:00', hr: 90, bpSys: 108, bpDia: 68, spo2: 97 },
  { time: '10:00', hr: 95, bpSys: 100, bpDia: 65, spo2: 95 },
  { time: '11:00', hr: 105, bpSys: 95, bpDia: 60, spo2: 92 },
  { time: '12:00', hr: 115, bpSys: 88, bpDia: 55, spo2: 90 },
  { time: '13:00', hr: 125, bpSys: 85, bpDia: 50, spo2: 88 }, // Current
];

export default function PatientDetail() {
  const navigate = useNavigate();
  const { id } = useParams();

  // Mock patient data for demonstration
  const patient = {
    id: id || '1001',
    name: 'John Doe',
    age: 65,
    gender: 'Male',
    bed: 'ICU-01',
    admissionDate: '2026-05-24',
    diagnosis: 'Sepsis Query',
    news2: 7,
    status: 'critical',
    hr: 115,
    bp: '105/65',
    spo2: 92,
    temp: 39.5,
    rr: 20,
    factors: [
      { name: "Heart Rate", score: 2 },
      { name: "Systolic BP", score: 1 },
      { name: "SpO2 (Scale 1)", score: 2 },
      { name: "Temperature", score: 2 }
    ]
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-obsidian overflow-auto">
      {/* Header */}
      <header className="h-auto md:h-20 py-4 md:py-0 border-b border-slate-800 flex flex-col md:flex-row items-start md:items-center px-4 md:px-8 bg-obsidianCard sticky top-0 z-10">
        <button 
          onClick={() => navigate('/ward')}
          className="mb-4 md:mb-0 mr-0 md:mr-6 p-2 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>
        
        <div className="flex-1 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center space-x-3">
              <span>{patient.name}</span>
              <span className="text-sm font-normal text-slate-400 border border-slate-700 px-2 py-0.5 rounded bg-slate-800">
                {patient.age}y • {patient.gender} • ID: {patient.id}
              </span>
            </h1>
            <p className="text-slate-400 text-sm">Bed: <span className="text-white font-medium">{patient.bed}</span> • Admitted: {patient.admissionDate} • Primary: {patient.diagnosis}</p>
          </div>
          
          <div className="flex items-center space-x-6">
            <div className="text-right">
              <p className="text-sm text-slate-400 font-medium uppercase tracking-wider">Current NEWS2</p>
              <div className="flex items-center justify-end space-x-2">
                <span className="text-3xl font-black text-criticalRed">{patient.news2}</span>
                <span className="text-criticalRed font-semibold bg-criticalRed/10 px-2 py-1 rounded border border-criticalRed/20">Critical</span>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content Grid */}
      <div className="p-4 md:p-8 grid grid-cols-1 lg:grid-cols-3 gap-8">
        
        {/* Left Column: Vitals Graph */}
        <div className="col-span-1 lg:col-span-2 space-y-8">
          <div className="bg-obsidianCard p-6 rounded-xl border border-slate-800 shadow-2xl">
            <h2 className="text-lg font-bold text-white mb-6 flex items-center space-x-2">
              <Activity className="w-5 h-5 text-stableTeal" />
              <span>Vital Signs Trajectory (Last 6 Hours)</span>
            </h2>
            
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={mockVitalHistory} margin={{ top: 5, right: 30, left: 20, bottom: 5 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                  <XAxis dataKey="time" stroke="#64748b" />
                  <YAxis yAxisId="left" stroke="#64748b" />
                  <YAxis yAxisId="right" orientation="right" stroke="#64748b" />
                  <Tooltip 
                    contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', color: '#f1f5f9' }}
                    itemStyle={{ color: '#f1f5f9' }}
                  />
                  <Legend />
                  <Line yAxisId="left" type="monotone" dataKey="hr" name="Heart Rate" stroke="#ef4444" strokeWidth={3} dot={{ r: 4 }} activeDot={{ r: 8 }} />
                  <Line yAxisId="left" type="monotone" dataKey="bpSys" name="BP Sys" stroke="#3b82f6" strokeWidth={2} />
                  <Line yAxisId="left" type="monotone" dataKey="bpDia" name="BP Dia" stroke="#60a5fa" strokeWidth={2} strokeDasharray="5 5" />
                  <Line yAxisId="right" type="monotone" dataKey="spo2" name="SpO2 %" stroke="#10b981" strokeWidth={3} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            
            {/* Current Vitals Summary Row */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-8 pt-8 border-t border-slate-800">
              <div className="p-4 rounded-lg bg-slate-800/50 border border-slate-700">
                <p className="text-slate-400 text-sm mb-1 flex items-center space-x-2"><Heart className="w-4 h-4"/> <span>Heart Rate</span></p>
                <p className="text-3xl font-bold text-criticalRed">{patient.hr} <span className="text-sm font-normal text-slate-500">bpm</span></p>
              </div>
              <div className="p-4 rounded-lg bg-slate-800/50 border border-slate-700">
                <p className="text-slate-400 text-sm mb-1 flex items-center space-x-2"><Activity className="w-4 h-4"/> <span>Blood Pressure</span></p>
                <p className="text-3xl font-bold text-warningAmber">{patient.bp} <span className="text-sm font-normal text-slate-500">mmHg</span></p>
              </div>
              <div className="p-4 rounded-lg bg-slate-800/50 border border-slate-700">
                <p className="text-slate-400 text-sm mb-1 flex items-center space-x-2"><Droplets className="w-4 h-4"/> <span>SpO2</span></p>
                <p className="text-3xl font-bold text-warningAmber">{patient.spo2} <span className="text-sm font-normal text-slate-500">%</span></p>
              </div>
              <div className="p-4 rounded-lg bg-slate-800/50 border border-slate-700">
                <p className="text-slate-400 text-sm mb-1">Temperature</p>
                <p className="text-3xl font-bold text-warningAmber">{patient.temp} <span className="text-sm font-normal text-slate-500">°C</span></p>
              </div>
            </div>
          </div>
        </div>

        {/* Right Column: AI Explanations & Next Steps */}
        <div className="col-span-1 space-y-6">
          
          {/* NEWS2 Breakdown Card */}
          <div className="bg-obsidianCard border border-slate-800 rounded-xl p-6 shadow-2xl">
            <h3 className="text-lg font-bold text-white mb-4 flex items-center space-x-2">
              <Activity className="w-5 h-5 text-criticalRed" />
              <span>NEWS2 Breakdown</span>
            </h3>
            <p className="text-xs text-slate-400 mb-4">Showing only parameters contributing to the current risk score.</p>
            <div className="space-y-2">
              {patient.factors.map((f, i) => (
                <div key={i} className="flex justify-between items-center bg-slate-800 rounded px-3 py-2">
                  <span className="text-slate-300 text-sm">{f.name}</span>
                  <span className={`text-white text-xs font-bold px-2.5 py-1 rounded ${f.score >= 3 ? 'bg-criticalRed' : 'bg-warningAmber text-black'}`}>
                    +{f.score}
                  </span>
                </div>
              ))}
            </div>
            <div className="mt-4 pt-3 border-t border-slate-700 flex justify-between items-center">
              <span className="text-white font-bold text-sm">Total Score</span>
              <span className="text-2xl font-black text-criticalRed">{patient.news2}</span>
            </div>
          </div>

          {/* Explainable AI Alert Card */}
          <div className="bg-criticalRed/10 border border-criticalRed/30 rounded-xl p-6 shadow-2xl">
            <div className="flex items-start space-x-3 mb-4">
              <AlertTriangle className="w-6 h-6 text-criticalRed flex-shrink-0 mt-1" />
              <div>
                <h3 className="text-lg font-bold text-criticalRed">Deterioration Alert</h3>
                <p className="text-white font-medium mt-1">High Risk of Septic Shock</p>
              </div>
            </div>
            
            <div className="mt-4">
              <p className="text-sm text-slate-300 mb-2 font-medium uppercase tracking-wider">AI Risk Factors:</p>
              <ul className="space-y-2">
                <li className="flex items-center justify-between text-sm bg-slate-900/50 p-2 rounded">
                  <span className="text-slate-300">Heart Rate ↑↑</span>
                  <span className="text-criticalRed font-bold">125 bpm</span>
                </li>
                <li className="flex items-center justify-between text-sm bg-slate-900/50 p-2 rounded">
                  <span className="text-slate-300">Systolic BP ↓↓</span>
                  <span className="text-criticalRed font-bold">85 mmHg</span>
                </li>
                <li className="flex items-center justify-between text-sm bg-slate-900/50 p-2 rounded">
                  <span className="text-slate-300">Temp ↑</span>
                  <span className="text-warningAmber font-bold">38.5 °C</span>
                </li>
              </ul>
            </div>
          </div>

          {/* Recommended Next Steps */}
          <div className="bg-obsidianCard border border-slate-800 rounded-xl p-6 shadow-2xl">
            <h3 className="text-lg font-bold text-white mb-4 flex items-center space-x-2">
              <Lightbulb className="w-5 h-5 text-warningAmber" />
              <span>Recommended Actions</span>
            </h3>
            
            <div className="space-y-3">
              <label className="flex items-start space-x-3 p-3 rounded-lg bg-slate-800/50 hover:bg-slate-800 transition-colors cursor-pointer border border-slate-700">
                <input type="checkbox" className="mt-1 w-4 h-4 accent-stableTeal rounded border-slate-600 bg-slate-700" />
                <div>
                  <p className="text-sm font-medium text-white">Review Sepsis Six Pathway</p>
                  <p className="text-xs text-slate-400">Time critical intervention required</p>
                </div>
              </label>
              
              <label className="flex items-start space-x-3 p-3 rounded-lg bg-slate-800/50 hover:bg-slate-800 transition-colors cursor-pointer border border-slate-700">
                <input type="checkbox" className="mt-1 w-4 h-4 accent-stableTeal rounded border-slate-600 bg-slate-700" />
                <div>
                  <p className="text-sm font-medium text-white">Administer IV Fluids</p>
                  <p className="text-xs text-slate-400">Protocol: 500ml crystalloid stat</p>
                </div>
              </label>

              <label className="flex items-start space-x-3 p-3 rounded-lg bg-slate-800/50 hover:bg-slate-800 transition-colors cursor-pointer border border-slate-700">
                <input type="checkbox" className="mt-1 w-4 h-4 accent-stableTeal rounded border-slate-600 bg-slate-700" />
                <div>
                  <p className="text-sm font-medium text-white">Escalate to Critical Care</p>
                  <p className="text-xs text-slate-400">Contact Intensive Care Outreach Team</p>
                </div>
              </label>
            </div>
            
            <button className="w-full mt-6 bg-stableTeal hover:bg-teal-500 text-white font-medium py-2 rounded-lg transition-colors flex items-center justify-center space-x-2">
              <FileText className="w-4 h-4" />
              <span>Acknowledge Alert</span>
            </button>
          </div>

        </div>
      </div>
    </div>
  );
}
