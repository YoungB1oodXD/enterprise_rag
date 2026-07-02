import { useState } from 'react';
import { useNavigate, Navigate } from 'react-router-dom';
import { useAuth } from '../store/auth';
import api from '../api/client';
import { CubeIcon } from '@heroicons/react/24/outline';

export default function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [isRegister, setIsRegister] = useState(false);
  const { login, isAuthenticated, setAuth } = useAuth();
  const navigate = useNavigate();

  if (isAuthenticated) {
    return <Navigate to="/knowledge-bases" replace />;
  }

  const handleLogin = async () => {
    await login(username, password);
    navigate('/knowledge-bases', { replace: true });
  };

  const handleRegister = async () => {
    const res = await api.post('/auth/register', { username, password });
    setAuth(res.data.access_token, res.data.username);
    navigate('/knowledge-bases', { replace: true });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!username.trim() || !password.trim()) {
      setError('请填写用户名和密码');
      return;
    }

    if (isRegister && password !== confirmPassword) {
      setError('两次密码输入不一致');
      return;
    }

    setLoading(true);
    try {
      if (isRegister) {
        await handleRegister();
      } else {
        await handleLogin();
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || (isRegister ? '注册失败' : '用户名或密码错误'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 to-blue-50">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-8">
          <div className="w-14 h-14 bg-blue-900 rounded-full flex items-center justify-center mb-4 shadow-md">
            <CubeIcon className="w-8 h-8 text-white" />
          </div>
          <h1 className="text-2xl font-bold text-slate-900">RAG Enterprise</h1>
          <p className="text-sm text-slate-500 mt-1.5">企业级智能知识库问答系统</p>
        </div>
        <form onSubmit={handleSubmit} className="bg-white p-8 rounded-xl shadow-lg border border-slate-200 space-y-5">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">用户名</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full px-3.5 py-2.5 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-shadow"
              placeholder="请输入用户名"
              required
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1.5">密码</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3.5 py-2.5 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-shadow"
              placeholder={isRegister ? '至少 6 位密码' : '请输入密码'}
              required
            />
          </div>
          {isRegister && (
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1.5">确认密码</label>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="w-full px-3.5 py-2.5 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-shadow"
                placeholder="再次输入密码"
                required
              />
            </div>
          )}
          {error && <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 px-4 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {loading ? '处理中...' : (isRegister ? '注册' : '登录')}
          </button>
          <div className="text-center">
            <button
              type="button"
              onClick={() => { setIsRegister(!isRegister); setError(''); setConfirmPassword(''); }}
              className="text-sm text-blue-600 hover:text-blue-800 transition-colors"
            >
              {isRegister ? '已有账号？去登录' : '没有账号？注册'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
