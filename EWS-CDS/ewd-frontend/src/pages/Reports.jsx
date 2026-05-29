import React from 'react';
import { FileText, Download, BarChart2, TrendingUp } from 'lucide-react';

export default function Reports() {
  const reports = [
    { title: "Weekly Deterioration Summary", date: "May 24, 2026", type: "PDF", size: "2.4 MB" },
    { title: "Ward 4B Patient Acuity Trends", date: "May 23, 2026", type: "CSV", size: "845 KB" },
    { title: "RRT Escalation Log - Q2", date: "May 15, 2026", type: "PDF", size: "1.1 MB" },
    { title: "Sepsis Protocol Adherence", date: "May 01, 2026", type: "Excel", size: "3.2 MB" },
  ];

  return (
    <div className="p-8 h-full bg-[#0b1120] text-slate-300 overflow-y-auto">
      <h1 className="text-2xl font-bold text-white mb-6 flex items-center">
        <BarChart2 className="mr-3 text-purple-400" /> Analytics & Reports
      </h1>
      
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
        <div className="bg-[#0f172a] border border-slate-700 p-5 rounded-xl">
          <div className="text-slate-400 text-sm font-bold uppercase tracking-wider mb-2">Critical Alerts (7d)</div>
          <div className="text-4xl font-black text-white">24</div>
          <div className="text-xs text-[#ef4444] flex items-center mt-2 font-bold">
            <TrendingUp className="w-3 h-3 mr-1" /> +12% from last week
          </div>
        </div>
        <div className="bg-[#0f172a] border border-slate-700 p-5 rounded-xl">
          <div className="text-slate-400 text-sm font-bold uppercase tracking-wider mb-2">Avg RRT Response</div>
          <div className="text-4xl font-black text-white">4.2<span className="text-xl text-slate-500 ml-1">min</span></div>
          <div className="text-xs text-[#84cc16] flex items-center mt-2 font-bold">
            <TrendingUp className="w-3 h-3 mr-1 transform rotate-180" /> -1.1 min from last week
          </div>
        </div>
        <div className="bg-[#0f172a] border border-slate-700 p-5 rounded-xl">
          <div className="text-slate-400 text-sm font-bold uppercase tracking-wider mb-2">False Positive Rate</div>
          <div className="text-4xl font-black text-white">8.5<span className="text-xl text-slate-500 ml-1">%</span></div>
          <div className="text-xs text-slate-400 flex items-center mt-2 font-bold">
            Stable across wards
          </div>
        </div>
      </div>

      <h2 className="text-lg font-bold text-white mb-4">Recent Exports</h2>
      <div className="bg-[#0f172a] border border-slate-700 rounded-xl overflow-hidden">
        {reports.map((report, i) => (
          <div key={i} className={`flex items-center justify-between p-4 hover:bg-slate-800/50 transition-colors ${i !== reports.length - 1 ? 'border-b border-slate-700' : ''}`}>
            <div className="flex items-center">
              <FileText className="w-5 h-5 text-blue-400 mr-4" />
              <div>
                <div className="font-bold text-slate-200">{report.title}</div>
                <div className="text-xs text-slate-500 mt-0.5">{report.date} • {report.type} • {report.size}</div>
              </div>
            </div>
            <button className="flex items-center px-3 py-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-600 rounded-lg text-xs font-bold text-white transition-colors">
              <Download className="w-3.5 h-3.5 mr-1.5" /> Download
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
