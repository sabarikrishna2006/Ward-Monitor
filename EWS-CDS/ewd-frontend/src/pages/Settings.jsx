import React, { useState, useEffect } from 'react';
import { Settings as SettingsIcon, Moon, Sun, Shield, Bell, Database } from 'lucide-react';

export default function Settings() {
  const [isLightMode, setIsLightMode] = useState(false);

  useEffect(() => {
    // Check current state from document body filter
    if (document.body.style.filter.includes('invert')) {
      setIsLightMode(true);
    }
  }, []);

  const toggleTheme = () => {
    if (isLightMode) {
      document.body.style.filter = 'none';
      setIsLightMode(false);
    } else {
      // Safe light mode using CSS invert + hue-rotate to preserve UI exactly
      document.body.style.filter = 'invert(1) hue-rotate(180deg)';
      setIsLightMode(true);
    }
  };

  return (
    <div className="p-8 h-full bg-[#0b1120] text-slate-300 overflow-y-auto">
      <h1 className="text-2xl font-bold text-white mb-8 flex items-center">
        <SettingsIcon className="mr-3 text-slate-400" /> System Settings
      </h1>
      
      <div className="max-w-3xl space-y-6">
        
        {/* Appearance */}
        <div className="bg-[#0f172a] border border-slate-700 rounded-xl overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-800 bg-slate-900/50 flex items-center">
            <Sun className="w-4 h-4 mr-2 text-yellow-400" />
            <h2 className="font-bold text-white">Appearance</h2>
          </div>
          <div className="p-5 flex items-center justify-between">
            <div>
              <div className="font-bold text-slate-200">Theme Preference</div>
              <div className="text-xs text-slate-400 mt-1">Switch between dark and light viewing modes.</div>
            </div>
            <button 
              onClick={toggleTheme}
              className={`flex items-center px-4 py-2 rounded-lg font-bold text-sm transition-all ${
                isLightMode ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
              }`}
            >
              {isLightMode ? <Sun className="w-4 h-4 mr-2" /> : <Moon className="w-4 h-4 mr-2" />}
              {isLightMode ? 'Light Mode Active' : 'Dark Mode Active'}
            </button>
          </div>
        </div>

        {/* Notifications */}
        <div className="bg-[#0f172a] border border-slate-700 rounded-xl overflow-hidden">
          <div className="px-5 py-4 border-b border-slate-800 bg-slate-900/50 flex items-center">
            <Bell className="w-4 h-4 mr-2 text-pink-400" />
            <h2 className="font-bold text-white">Alert Configurations</h2>
          </div>
          <div className="p-5 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="font-bold text-slate-200">Critical Audio Alarms</div>
                <div className="text-xs text-slate-400 mt-1">Play sound for NEWS2 ≥ 7.</div>
              </div>
              <div className="w-12 h-6 bg-blue-600 rounded-full relative cursor-pointer">
                <div className="absolute right-1 top-1 bg-white w-4 h-4 rounded-full"></div>
              </div>
            </div>
            <div className="flex items-center justify-between pt-4 border-t border-slate-800">
              <div>
                <div className="font-bold text-slate-200">Auto-Escalate to RRT</div>
                <div className="text-xs text-slate-400 mt-1">Automatically page rapid response after 5 mins of unacknowledged critical alert.</div>
              </div>
              <div className="w-12 h-6 bg-slate-700 rounded-full relative cursor-pointer">
                <div className="absolute left-1 top-1 bg-slate-400 w-4 h-4 rounded-full"></div>
              </div>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
