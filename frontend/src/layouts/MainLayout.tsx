import React, { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { Settings } from 'lucide-react';
import { setApiBaseUrl } from '../api/config';

export const MainLayout: React.FC = () => {
  const [baseUrl, setBaseUrl] = useState(import.meta.env.VITE_API_BASE_URL || 'http://localhost:8080/api');
  const [showSettings, setShowSettings] = useState(false);

  const handleSaveBaseUrl = () => {
    setApiBaseUrl(baseUrl);
    setShowSettings(false);
    alert('백엔드 Base URL이 업데이트되었습니다.');
  };

  const navItems = [
    { name: '대시보드', path: '/' },
    { name: '지도', path: '/map' },
    { name: '알림 등록', path: '/alerts' },
    { name: '화재 세부 조회', path: '/fires' },
  ];

  return (
    <div className="flex h-screen bg-slate-50 text-slate-800 font-sans">
      {/* Sidebar */}
      <aside className="w-64 bg-slate-700 text-slate-300 flex flex-col shadow-xl z-20">
        <nav className="flex-1 py-6 px-4 space-y-2">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                `flex items-center px-4 py-3 rounded-lg transition-colors duration-200 ${
                  isActive
                    ? 'bg-blue-600/90 text-white font-medium shadow-md'
                    : 'hover:bg-slate-600 hover:text-white'
                }`
              }
            >
              <span>{item.name}</span>
            </NavLink>
          ))}
        </nav>

        <div className="p-4 border-t border-slate-600">
          <button
            onClick={() => setShowSettings(!showSettings)}
            className="flex items-center gap-3 px-4 py-3 w-full rounded-lg hover:bg-slate-600 transition-colors text-left"
          >
            <Settings size={20} />
            <span>설정</span>
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col overflow-hidden relative">
        {/* Settings Modal/Overlay */}
        {showSettings && (
          <div className="absolute top-4 right-4 bg-white p-4 rounded-lg shadow-xl border border-slate-200 z-50 w-80">
            <h3 className="text-lg font-semibold mb-3 text-slate-800">API 설정</h3>
            <div className="mb-4">
              <label className="block text-sm font-medium text-slate-600 mb-1">
                백엔드 Base URL
              </label>
              <input
                type="text"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                className="w-full px-3 py-2 border border-slate-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="http://localhost:8080/api"
              />
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setShowSettings(false)}
                className="px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-100 rounded-md"
              >
                취소
              </button>
              <button
                onClick={handleSaveBaseUrl}
                className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700"
              >
                저장
              </button>
            </div>
          </div>
        )}

        <div className="flex-1 overflow-y-auto p-6 md:p-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
};
