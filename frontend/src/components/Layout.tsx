import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../store/auth';
import { CubeIcon, ChatBubbleLeftRightIcon, ArrowRightStartOnRectangleIcon } from '@heroicons/react/24/outline';

export default function Layout({ children }: { children: React.ReactNode }) {
  const { username, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const initial = username ? username[0].toUpperCase() : '?';

  return (
    <div className="flex h-screen bg-slate-50">
      <aside className="w-60 bg-white border-r border-slate-200 flex flex-col shrink-0">
        {/* 品牌区：深蓝渐变 */}
        <div className="h-14 flex items-center gap-2.5 px-5 bg-gradient-to-br from-blue-900 to-blue-800 shrink-0">
          <CubeIcon className="w-6 h-6 text-white" />
          <span className="font-semibold text-white tracking-wide">RAG Enterprise</span>
        </div>

        {/* 导航 */}
        <nav className="flex-1 p-3 space-y-0.5">
          <NavLink
            to="/knowledge-bases"
            className={({ isActive }) =>
              `flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150 ${
                isActive
                  ? 'bg-blue-50 text-blue-700 shadow-sm'
                  : 'text-slate-600 hover:bg-slate-50 hover:text-slate-800'
              }`
            }
          >
            <CubeIcon className="w-5 h-5 shrink-0" />
            知识库管理
          </NavLink>
          <NavLink
            to="/chat"
            className={({ isActive }) =>
              `flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150 ${
                isActive
                  ? 'bg-blue-50 text-blue-700 shadow-sm'
                  : 'text-slate-600 hover:bg-slate-50 hover:text-slate-800'
              }`
            }
          >
            <ChatBubbleLeftRightIcon className="w-5 h-5 shrink-0" />
            智能问答
          </NavLink>
        </nav>

        {/* 底部用户 */}
        <div className="p-4 border-t border-slate-200">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="w-8 h-8 rounded-full bg-blue-100 text-blue-700 text-sm font-medium flex items-center justify-center shrink-0">
                {initial}
              </div>
              <span className="text-sm text-slate-600 truncate">{username}</span>
            </div>
            <button
              onClick={handleLogout}
              className="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
              title="退出登录"
            >
              <ArrowRightStartOnRectangleIcon className="w-4 h-4" />
            </button>
          </div>
        </div>
      </aside>
      <main className="flex-1 overflow-auto">{children}</main>
    </div>
  );
}
