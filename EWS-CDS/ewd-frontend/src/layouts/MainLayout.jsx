import { Outlet, Link, useLocation } from 'react-router-dom';
import { LayoutDashboard, Users, FileText, Settings, LogOut, Menu, X, Activity } from 'lucide-react';
import { useState, useEffect } from 'react';

export default function MainLayout() {
  const location = useLocation();
  const [isLightMode, setIsLightMode] = useState(() => document.documentElement.classList.contains('light'));
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [apiStatus, setApiStatus] = useState('checking'); // 'online' | 'offline' | 'checking'

  useEffect(() => {
    const observer = new MutationObserver(() => {
      setIsLightMode(document.documentElement.classList.contains('light'));
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  // System health ping
  useEffect(() => {
    const checkApi = () => {
      const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
      fetch(`${API_URL}/docs`, { method: 'HEAD', signal: AbortSignal.timeout(3000) })
        .then(() => setApiStatus('online'))
        .catch(() => setApiStatus('offline'));
    };
    checkApi();
    const interval = setInterval(checkApi, 30000);
    return () => clearInterval(interval);
  }, []);

  const navItems = [
    { name: 'WARD VIEW', path: '/ward', icon: LayoutDashboard },
    { name: 'STAFF', path: '/staff', icon: Users },
    { name: 'REPORTS', path: '/reports', icon: FileText },
    { name: 'SETTINGS', path: '/settings', icon: Settings },
  ];

  // In light mode: deep purple sidebar. In dark mode: near-black sidebar.
  const sidebarBg   = isLightMode ? '#5b0059' : '#141b2d';
  const sidebarBorder = isLightMode ? '#7b0077' : '#1e293b';

  const NavLink = ({ item, onClick }) => {
    const isActive = location.pathname.startsWith(item.path);
    const Icon = item.icon;

    const activeBg   = isLightMode ? 'rgba(255,255,255,0.20)' : 'rgba(128,0,128,0.25)';
    const hoverBg    = isLightMode ? 'rgba(255,255,255,0.12)' : 'rgba(128,0,128,0.15)';
    const activeIndicator = isLightMode ? '#fbbf24' : '#a855f7'; // gold accent in light, purple in dark

    return (
      <Link
        key={item.name}
        to={item.path}
        onClick={onClick}
        className="flex flex-col items-center justify-center w-full py-3.5 transition-all duration-200 relative group"
        style={{
          backgroundColor: isActive ? activeBg : 'transparent',
        }}
        onMouseEnter={e => {
          if (!isActive) e.currentTarget.style.backgroundColor = hoverBg;
        }}
        onMouseLeave={e => {
          if (!isActive) e.currentTarget.style.backgroundColor = 'transparent';
        }}
      >
        {/* Active indicator bar */}
        {isActive && (
          <div
            className="absolute left-0 top-2 bottom-2 w-[3px] rounded-r"
            style={{ backgroundColor: activeIndicator }}
          />
        )}
        <Icon
          className="w-5 h-5 mb-1"
          style={{
            color: isActive ? '#ffffff' : 'rgba(255,255,255,0.5)',
          }}
        />
        <span
          className="text-[9px] font-bold tracking-widest"
          style={{
            color: isActive ? '#ffffff' : 'rgba(255,255,255,0.45)',
          }}
        >
          {item.name}
        </span>
      </Link>
    );
  };

  return (
    <div className={`flex h-screen overflow-hidden font-sans ${isLightMode ? 'bg-white text-slate-800' : 'bg-[#0a0f1c] text-slate-200'}`}>

      {/* ── DESKTOP SIDEBAR ── */}
      <aside
        className="hidden md:flex w-[88px] flex-col items-center py-4 shadow-2xl z-20 border-r transition-colors duration-300 shrink-0"
        style={{ backgroundColor: sidebarBg, borderColor: sidebarBorder }}
      >
        {/* Brand Logo + Text */}
        <div className="flex flex-col items-center mb-5 px-2">
          <svg width="36" height="36" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" className="mb-2">
            <polygon points="0,0 100,0 0,100" fill="#000000" />
            <polygon points="0,100 100,100 100,0" fill="#800080" opacity="0.9" />
            <polygon points="0,80 20,100 0,100" fill="#000000" />
          </svg>
          <div className="text-center">
            <div className="text-white text-[12px] font-black leading-none tracking-tight">
              foqal <span className="font-light" style={{ color: isLightMode ? '#f5d0f5' : '#d8b4fe' }}>analytics</span>
            </div>
            <div className="text-[7px] font-bold tracking-wider uppercase mt-0.5 leading-tight text-center"
              style={{ color: isLightMode ? 'rgba(255,255,255,0.65)' : '#a8249c' }}>
              EWS · Early<br />Warning System
            </div>
          </div>
        </div>

        {/* Divider */}
        <div
          className="w-10 h-px mb-3"
          style={{ backgroundColor: isLightMode ? 'rgba(255,255,255,0.2)' : 'rgba(128,0,128,0.2)' }}
        />

        {/* Navigation */}
        <nav className="flex-1 w-full space-y-0.5">
          {navItems.map((item) => (
            <NavLink key={item.name} item={item} />
          ))}
        </nav>

        {/* System Health Indicator */}
        <div className="w-full px-3 py-2 mb-1">
          <div
            className="flex flex-col items-center rounded-lg py-2 px-1 gap-1"
            style={{
              backgroundColor: isLightMode ? 'rgba(0,0,0,0.15)' : 'rgba(255,255,255,0.04)',
              border: `1px solid ${isLightMode ? 'rgba(255,255,255,0.1)' : 'rgba(255,255,255,0.05)'}`,
            }}
            title={`System ${apiStatus === 'online' ? 'healthy · API connected' : apiStatus === 'offline' ? 'offline · Check API server' : 'checking...'}`}
          >
            <Activity
              className="w-4 h-4"
              style={{
                color: apiStatus === 'online' ? '#10b981' : apiStatus === 'offline' ? '#ef4444' : '#f59e0b',
              }}
            />
            <div className="flex items-center gap-1">
              <div
                className="w-1.5 h-1.5 rounded-full"
                style={{
                  backgroundColor: apiStatus === 'online' ? '#10b981' : apiStatus === 'offline' ? '#ef4444' : '#f59e0b',
                  boxShadow: apiStatus === 'online'
                    ? '0 0 4px #10b981'
                    : apiStatus === 'offline'
                    ? '0 0 4px #ef4444'
                    : '0 0 4px #f59e0b',
                  animation: apiStatus === 'online' ? 'none' : 'pulse 2s infinite',
                }}
              />
              <span
                className="text-[8px] font-bold uppercase tracking-wider"
                style={{
                  color: apiStatus === 'online' ? '#10b981' : apiStatus === 'offline' ? '#ef4444' : '#f59e0b',
                }}
              >
                {apiStatus === 'online' ? 'LIVE' : apiStatus === 'offline' ? 'DOWN' : '...'}
              </span>
            </div>
          </div>
        </div>

        {/* Logout */}
        <div className="w-full">
          <Link
            to="/login"
            className="flex flex-col items-center justify-center w-full py-3.5 transition-all duration-200"
            style={{ color: 'rgba(255,255,255,0.4)' }}
            onMouseEnter={e => {
              e.currentTarget.style.backgroundColor = isLightMode ? 'rgba(255,255,255,0.12)' : 'rgba(128,0,128,0.15)';
              e.currentTarget.style.color = '#ffffff';
            }}
            onMouseLeave={e => {
              e.currentTarget.style.backgroundColor = 'transparent';
              e.currentTarget.style.color = 'rgba(255,255,255,0.4)';
            }}
          >
            <LogOut className="w-5 h-5 mb-1" style={{ color: 'inherit' }} />
            <span className="text-[9px] font-bold tracking-widest text-inherit">LOGOUT</span>
          </Link>
        </div>
      </aside>

      {/* ── MOBILE HEADER BAR ── */}
      <div
        className="md:hidden fixed top-0 left-0 right-0 z-30 flex items-center justify-between px-4 h-12 border-b"
        style={{ backgroundColor: sidebarBg, borderColor: sidebarBorder }}
      >
        <div className="flex items-center space-x-2">
          <svg width="24" height="24" viewBox="0 0 100 100">
            <polygon points="0,0 100,0 0,100" fill="#000" />
            <polygon points="0,100 100,100 100,0" fill="#800080" />
            <polygon points="0,80 20,100 0,100" fill="#000" />
          </svg>
          <span className="text-white text-sm font-bold">foqal <span className="text-[#d8b4fe] font-light">analytics</span></span>
        </div>

        <div className="flex items-center gap-3">
          {/* Mobile system health */}
          <div
            className="w-2 h-2 rounded-full"
            style={{
              backgroundColor: apiStatus === 'online' ? '#10b981' : '#ef4444',
              boxShadow: `0 0 4px ${apiStatus === 'online' ? '#10b981' : '#ef4444'}`,
            }}
          />
          <button
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
          >
            {mobileMenuOpen ? <X className="w-5 h-5 text-white" /> : <Menu className="w-5 h-5 text-white" />}
          </button>
        </div>
      </div>

      {/* ── MOBILE SLIDE-DOWN MENU ── */}
      {mobileMenuOpen && (
        <div
          className="md:hidden fixed top-12 left-0 right-0 z-20 border-b"
          style={{ backgroundColor: sidebarBg, borderColor: sidebarBorder }}
        >
          {navItems.map((item) => {
            const isActive = location.pathname.startsWith(item.path);
            const Icon = item.icon;
            return (
              <Link
                key={item.name}
                to={item.path}
                onClick={() => setMobileMenuOpen(false)}
                className="flex items-center space-x-3 px-5 py-3 border-b transition-colors"
                style={{
                  borderColor: sidebarBorder,
                  backgroundColor: isActive ? 'rgba(255,255,255,0.15)' : 'transparent',
                  color: '#ffffff',
                }}
              >
                <Icon className="w-5 h-5" style={{ color: isActive ? '#f5d0f5' : 'rgba(255,255,255,0.6)' }} />
                <span className="text-sm font-semibold">{item.name}</span>
              </Link>
            );
          })}
          <Link
            to="/login"
            onClick={() => setMobileMenuOpen(false)}
            className="flex items-center space-x-3 px-5 py-3 transition-colors"
            style={{ color: 'rgba(255,255,255,0.5)' }}
          >
            <LogOut className="w-5 h-5" />
            <span className="text-sm font-semibold">Logout</span>
          </Link>
        </div>
      )}

      {/* ── MAIN CONTENT ── */}
      <main className={`flex-1 flex flex-col h-screen overflow-hidden md:pt-0 pt-12 ${isLightMode ? 'bg-white' : 'bg-[#0a0f1c]'}`}>
        <Outlet />
      </main>
    </div>
  );
}
