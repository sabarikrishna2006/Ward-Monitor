import { Outlet, Link, useLocation } from 'react-router-dom';
import { LayoutDashboard, Users, FileText, Settings, LogOut, PlusSquare } from 'lucide-react';

export default function MainLayout() {
  const location = useLocation();
  
  const navItems = [
    { name: 'WARD VIEW', path: '/ward', icon: LayoutDashboard },
    { name: 'STAFF', path: '/staff', icon: Users },
    { name: 'REPORTS', path: '/reports', icon: FileText },
    { name: 'SETTINGS', path: '/settings', icon: Settings },
  ];

  return (
    <div className="flex h-screen bg-obsidian text-slate-200 overflow-hidden font-sans">
      {/* Sidebar */}
      <aside className="w-24 bg-[#141b2d] border-r border-slate-800 flex flex-col items-center py-6 shadow-2xl z-20">
        
        {/* Logo */}
        <div className="mb-12">
          <PlusSquare className="w-10 h-10 text-stableTeal fill-stableTeal/20" />
        </div>
        
        {/* Navigation */}
        <nav className="flex-1 w-full space-y-2">
          {navItems.map((item) => {
            const isActive = location.pathname.startsWith(item.path);
            const Icon = item.icon;
            return (
              <Link
                key={item.name}
                to={item.path}
                className={`flex flex-col items-center justify-center w-full py-4 transition-all duration-200 relative ${
                  isActive 
                    ? 'bg-slate-800/60 text-white' 
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/30'
                }`}
              >
                {isActive && (
                  <div className="absolute left-0 top-0 bottom-0 w-1 bg-stableTeal"></div>
                )}
                <Icon className={`w-6 h-6 mb-2 ${isActive ? 'text-stableTeal' : 'text-slate-500'}`} />
                <span className="text-[10px] font-semibold tracking-widest">{item.name}</span>
              </Link>
            );
          })}
        </nav>
        
        {/* Logout */}
        <div className="w-full mt-auto">
          <Link
            to="/login"
            className="flex flex-col items-center justify-center w-full py-4 text-slate-500 hover:text-white hover:bg-slate-800/30 transition-all duration-200"
          >
            <LogOut className="w-6 h-6 mb-2" />
            <span className="text-[10px] font-semibold tracking-widest">LOGOUT</span>
          </Link>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col h-screen overflow-hidden bg-[#0a0f1c]">
        <Outlet />
      </main>
    </div>
  );
}
