import React from 'react';
import { Users, Mail, Phone, Calendar } from 'lucide-react';

export default function Staff() {
  const staffList = [
    { name: "Dr. Sarah Jenkins", role: "Attending Physician", dept: "Cardiology", status: "On Call" },
    { name: "Dr. Michael Chen", role: "Resident", dept: "Internal Medicine", status: "Active" },
    { name: "Nurse Emily Davis", role: "Charge Nurse", dept: "Ward 4B", status: "Active" },
    { name: "Nurse Robert Smith", role: "Staff Nurse", dept: "Ward 4B", status: "Off Duty" },
  ];

  return (
    <div className="p-8 h-full bg-[#0b1120] text-slate-300 overflow-y-auto">
      <h1 className="text-2xl font-bold text-white mb-6 flex items-center">
        <Users className="mr-3 text-blue-400" /> Staff Directory
      </h1>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {staffList.map((staff, i) => (
          <div key={i} className="bg-[#0f172a] border border-slate-700 p-5 rounded-xl flex flex-col hover:border-slate-500 transition-colors">
            <div className="flex justify-between items-start mb-4">
              <div className="w-12 h-12 rounded-full bg-blue-900/40 border border-blue-500/30 flex items-center justify-center text-blue-300 font-bold text-lg">
                {staff.name.charAt(0)}{staff.name.split(' ').pop().charAt(0)}
              </div>
              <span className={`text-[10px] font-bold uppercase px-2 py-1 rounded-full ${
                staff.status === 'Active' ? 'bg-green-900/50 text-green-400 border border-green-700/50' : 
                staff.status === 'On Call' ? 'bg-yellow-900/50 text-yellow-400 border border-yellow-700/50' : 
                'bg-slate-800 text-slate-400 border border-slate-600'
              }`}>
                {staff.status}
              </span>
            </div>
            <h2 className="text-lg font-bold text-white">{staff.name}</h2>
            <p className="text-sm text-blue-400 font-medium mb-1">{staff.role}</p>
            <p className="text-xs text-slate-400 mb-4">{staff.dept}</p>
            
            <div className="mt-auto space-y-2 border-t border-slate-800 pt-4">
              <div className="flex items-center text-xs text-slate-400">
                <Phone className="w-3.5 h-3.5 mr-2" /> Ext. {3000 + i}
              </div>
              <div className="flex items-center text-xs text-slate-400">
                <Mail className="w-3.5 h-3.5 mr-2" /> {staff.name.split(' ')[1].toLowerCase()}@hospital.org
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
