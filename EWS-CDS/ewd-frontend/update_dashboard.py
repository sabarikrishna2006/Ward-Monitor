import re

def update_dashboard():
    with open('e:/IP_EarlyWarning/ews-cds/ewd-frontend/src/pages/Dashboard.jsx', 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Imports
    content = content.replace(
        "import { Search, ChevronDown, ChevronUp, Bell, User, X, Activity, AlertTriangle, Lightbulb, CheckSquare, Heart, Droplets, PhoneForwarded } from 'lucide-react';",
        "import { Search, ChevronDown, ChevronUp, Bell, User, X, Activity, AlertTriangle, Lightbulb, CheckSquare, Heart, Droplets, PhoneForwarded, PlayCircle, UserPlus, Plus, Shield } from 'lucide-react';"
    )

    # 2. State and fetchData
    state_str = """  const [expandedAlertId, setExpandedAlertId] = useState(null); // which alert card is expanded
  const [selectedWard, setSelectedWard] = useState('All');
  const [isReplay, setIsReplay] = useState(false);
  const [showAddPatient, setShowAddPatient] = useState(false);
  const [newPatient, setNewPatient] = useState({ name: '', age: 60, sex: 'M', ward: 'Ward 4B - Acute Care', room: '1', bed: '1', complaint: '', hr: 80, rr: 16, spo2: 98, sbp: 120, dbp: 80, temp: 37.0 });"""
    
    content = content.replace(
        "  const [expandedAlertId, setExpandedAlertId] = useState(null); // which alert card is expanded",
        state_str
    )

    fetch_old = """  const fetchData = useCallback(() => {
    fetch('http://localhost:8000/api/ward-data')
      .then(res => res.json())
      .then(data => setPatients(data.patients))
      .catch(err => console.error('Error fetching patient data:', err));
  }, []);"""

    fetch_new = """  const fetchData = useCallback(() => {
    fetch(`http://localhost:8000/api/ward-data?ward=${selectedWard}&replay=${isReplay}`)
      .then(res => res.json())
      .then(data => setPatients(data.patients))
      .catch(err => console.error('Error fetching patient data:', err));
  }, [selectedWard, isReplay]);"""

    content = content.replace(fetch_old, fetch_new)

    # 3. Ward Dropdown
    ward_old = """          <h2 className="text-slate-400 font-semibold tracking-wider text-xs flex items-center uppercase">
            Ward 4B — Acute Care / ICU
            <ChevronDown className="ml-1 w-3 h-3" />
          </h2>"""
          
    ward_new = """          <div className="flex items-center">
            <select 
              value={selectedWard}
              onChange={(e) => setSelectedWard(e.target.value)}
              className="bg-transparent text-slate-400 font-semibold tracking-wider text-xs uppercase focus:outline-none appearance-none cursor-pointer hover:text-white transition-colors"
            >
              <option value="All">All Wards</option>
              <option value="Ward 4B - Acute Care">Ward 4B — Acute Care / ICU</option>
              <option value="Ward 7A - Step Down">Ward 7A — Step Down</option>
            </select>
            <ChevronDown className="ml-1 w-3 h-3 text-slate-400 pointer-events-none" />
          </div>"""
    
    content = content.replace(ward_old, ward_new)

    # 4. Buttons in top bar
    buttons_old = """          <span className="text-slate-400 text-xs hidden lg:block pr-5 border-r border-slate-700">
            Time: {timeStr}
          </span>

          <div className="relative">"""
          
    buttons_new = """          <span className="text-slate-400 text-xs hidden lg:block pr-5 border-r border-slate-700">
            Time: {timeStr}
          </span>
          
          <button 
            onClick={() => setIsReplay(!isReplay)} 
            className={`flex items-center space-x-1 px-3 py-1.5 rounded-full text-xs font-bold transition-colors mr-2 border ${isReplay ? 'bg-blue-600/20 text-blue-400 border-blue-500/50' : 'bg-slate-800/50 text-slate-400 border-slate-700 hover:text-white'}`}
          >
            <PlayCircle className={`w-3.5 h-3.5 ${isReplay ? 'animate-pulse' : ''}`} />
            <span>{isReplay ? 'Replaying' : 'Mock Replay'}</span>
          </button>
          
          <button 
            onClick={() => setShowAddPatient(true)} 
            className="flex items-center space-x-1 px-3 py-1.5 rounded-full bg-slate-800/50 border border-slate-700 text-slate-400 text-xs font-bold hover:text-white transition-colors mr-2"
          >
            <UserPlus className="w-3.5 h-3.5" />
            <span>Admit</span>
          </button>

          <div className="relative">"""
          
    content = content.replace(buttons_old, buttons_new)

    # 5. Alert Details
    alert_old = """                        {/* Immediate Action */}
                        <div className="bg-slate-800 rounded-lg p-3 border border-slate-700">"""
    
    alert_new = """                        {/* Drug-Lab Interaction Alerts */}
                        {patient.drugLabAlerts && patient.drugLabAlerts.length > 0 && (
                          <div className="bg-[#ef4444]/10 rounded-lg p-3 border border-[#ef4444]/30 mb-3">
                            <p className="text-[10px] font-bold text-[#ef4444] uppercase tracking-wider mb-1 flex items-center">
                              <Shield className="w-3 h-3 mr-1" /> Medication Alert
                            </p>
                            {patient.drugLabAlerts.map((alert, idx) => (
                              <div key={idx} className="mb-2 last:mb-0">
                                <p className="text-xs text-white font-bold">{alert.rule_name}</p>
                                <p className="text-[11px] text-slate-300 leading-snug mt-0.5">{alert.message}</p>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Immediate Action */}
                        <div className="bg-slate-800 rounded-lg p-3 border border-slate-700">"""
    content = content.replace(alert_old, alert_new)

    # 6. Add Patient Modal
    modal = """        {/* ══════════════════════════════════════════════════════
            ADD PATIENT MODAL
        ══════════════════════════════════════════════════════ */}
        {showAddPatient && (
          <div className="fixed inset-0 bg-black/60 z-[100] flex items-center justify-center p-4">
            <div className="bg-[#0f172a] border border-slate-700 rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden flex flex-col max-h-full">
              <div className="p-4 border-b border-slate-800 flex justify-between items-center bg-[#0b1120]">
                <h2 className="text-lg font-bold text-white flex items-center"><UserPlus className="w-5 h-5 mr-2 text-blue-400" /> Admit New Patient</h2>
                <button onClick={() => setShowAddPatient(false)} className="text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
              </div>
              <div className="p-6 overflow-y-auto space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-bold text-slate-400 uppercase mb-1">Name</label>
                    <input type="text" value={newPatient.name} onChange={e => setNewPatient({...newPatient, name: e.target.value})} className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm" placeholder="e.g. John Doe" />
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-slate-400 uppercase mb-1">Chief Complaint</label>
                    <input type="text" value={newPatient.complaint} onChange={e => setNewPatient({...newPatient, complaint: e.target.value})} className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm" placeholder="e.g. Sepsis" />
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <label className="block text-xs font-bold text-slate-400 uppercase mb-1">Age</label>
                    <input type="number" value={newPatient.age} onChange={e => setNewPatient({...newPatient, age: parseInt(e.target.value)})} className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm" />
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-slate-400 uppercase mb-1">Sex</label>
                    <select value={newPatient.sex} onChange={e => setNewPatient({...newPatient, sex: e.target.value})} className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm">
                      <option>M</option><option>F</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-slate-400 uppercase mb-1">Ward</label>
                    <select value={newPatient.ward} onChange={e => setNewPatient({...newPatient, ward: e.target.value})} className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm">
                      <option>Ward 4B - Acute Care</option><option>Ward 7A - Step Down</option>
                    </select>
                  </div>
                </div>
                
                <h3 className="text-sm font-bold text-slate-300 border-b border-slate-800 pb-2 mt-6 mb-4">Initial Vitals</h3>
                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <label className="block text-xs font-bold text-slate-400 uppercase mb-1">Heart Rate</label>
                    <input type="number" value={newPatient.hr} onChange={e => setNewPatient({...newPatient, hr: parseFloat(e.target.value)})} className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm" />
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-slate-400 uppercase mb-1">Resp Rate</label>
                    <input type="number" value={newPatient.rr} onChange={e => setNewPatient({...newPatient, rr: parseFloat(e.target.value)})} className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm" />
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-slate-400 uppercase mb-1">SpO2 (%)</label>
                    <input type="number" value={newPatient.spo2} onChange={e => setNewPatient({...newPatient, spo2: parseFloat(e.target.value)})} className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm" />
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-slate-400 uppercase mb-1">Systolic BP</label>
                    <input type="number" value={newPatient.sbp} onChange={e => setNewPatient({...newPatient, sbp: parseFloat(e.target.value)})} className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm" />
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-slate-400 uppercase mb-1">Diastolic BP</label>
                    <input type="number" value={newPatient.dbp} onChange={e => setNewPatient({...newPatient, dbp: parseFloat(e.target.value)})} className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm" />
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-slate-400 uppercase mb-1">Temp (°C)</label>
                    <input type="number" step="0.1" value={newPatient.temp} onChange={e => setNewPatient({...newPatient, temp: parseFloat(e.target.value)})} className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm" />
                  </div>
                </div>
              </div>
              <div className="p-4 border-t border-slate-800 bg-[#0b1120] flex justify-end space-x-3">
                <button onClick={() => setShowAddPatient(false)} className="px-4 py-2 rounded-lg text-sm font-bold text-slate-400 hover:text-white transition-colors">Cancel</button>
                <button 
                  onClick={() => {
                    fetch('http://localhost:8000/api/patients', {
                      method: 'POST', headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify(newPatient)
                    }).then(() => { setShowAddPatient(false); fetchData(); });
                  }} 
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-sm font-bold text-white transition-colors flex items-center"
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
}"""
    
    # insert modal right before the final `</div>\n    </div>\n  );\n}`
    content = content.replace("      </div>\n    </div>\n  );\n}", modal)

    with open('e:/IP_EarlyWarning/ews-cds/ewd-frontend/src/pages/Dashboard.jsx', 'w', encoding='utf-8') as f:
        f.write(content)

if __name__ == '__main__':
    update_dashboard()
