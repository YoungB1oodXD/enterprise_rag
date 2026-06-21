import { NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../store/auth';
import { CubeIcon, ArrowRightStartOnRectangleIcon } from '@heroicons/react/24/outline';

export default function Layout({ children }: { children: React.ReactNode }) {
  const { username, logout } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="flex h-screen bg-gray-50">
      <aside className="w-60 bg-white border-r border-gray-200 flex flex-col shrink-0">
        <div className="h-14 flex items-center gap-2 px-5 border-b border-gray-200">
          <CubeIcon className="w-6 h-6 text-indigo-600" />
          <span className="font-semibold text-gray-900">RAG Enterprise</span>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          <NavLink
            to="/knowledge-bases"
            className={({ isActive }) =>
              `block px-3 py-2 rounded-lg text-sm font-medium ${isActive ? 'bg-indigo-50 text-indigo-700' : 'text-gray-600 hover:bg-gray-100'}`
            }
          >
            知识库
          </NavLink>
        </nav>
        <div className="p-3 border-t border-gray-200">
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-500">{username}</span>
            <button onClick={handleLogout} className="text-gray-400 hover:text-gray-600">
              <ArrowRightStartOnRectangleIcon className="w-5 h-5" />
            </button>
          </div>
        </div>
      </aside>
      <main className="flex-1 overflow-auto">{children}</main>
    </div>
  );
}
