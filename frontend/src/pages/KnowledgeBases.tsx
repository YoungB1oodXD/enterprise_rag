import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../api/client';
import { useToast } from '../store/toast';
import type { KnowledgeBase, KnowledgeBaseCreateRequest } from '../types';
import { PlusIcon, TrashIcon, FolderOpenIcon } from '@heroicons/react/24/outline';

const CATEGORY_STYLES: Record<string, string> = {
  '法规': 'bg-blue-50 text-blue-700',
  '政策': 'bg-emerald-50 text-emerald-700',
  '通知': 'bg-amber-50 text-amber-700',
  '制度': 'bg-purple-50 text-purple-700',
  '其他': 'bg-slate-50 text-slate-600',
};

export default function KnowledgeBases() {
  const { showToast } = useToast();
  const [kbList, setKbList] = useState<KnowledgeBase[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [title, setTitle] = useState('');
  const [category, setCategory] = useState('法规');
  const navigate = useNavigate();

  const fetchList = useCallback(async () => {
    try {
      setLoading(true);
      const res = await api.get<KnowledgeBase[]>('/v1/knowledge_base/list');
      if (Array.isArray(res.data)) {
        setKbList(res.data);
      }
    } catch (err: any) {
      showToast(err.response?.data?.detail || '获取知识库列表失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchList();
  }, [fetchList]);

  const handleCreate = async () => {
    if (!title.trim()) return;
    try {
      const payload: KnowledgeBaseCreateRequest = {
        title: title.trim(),
        category,
      };
      const res = await api.post('/v1/knowledge_base', payload);
      if (res.data.knowledge_id) {
        setKbList((prev) => [
          ...prev,
          {
            knowledge_id: res.data.knowledge_id,
            title: title.trim(),
            category,
          },
        ]);
      }
      setShowCreate(false);
      setTitle('');
    } catch (err: any) {
      showToast(err.response?.data?.detail || '创建失败');
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('确定要删除这个知识库吗？')) return;
    try {
      await api.delete(`/v1/knowledge_base/${id}`);
      setKbList((prev) => prev.filter((kb) => kb.knowledge_id !== id));
    } catch (err: any) {
      showToast(err.response?.data?.detail || '删除失败');
    }
  };

  if (loading) {
    return (
      <div className="p-8 max-w-4xl mx-auto">
        <div className="animate-pulse space-y-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-20 bg-slate-100 rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">知识库</h1>
          <p className="text-sm text-slate-500 mt-1">管理你的知识库和文档</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
        >
          <PlusIcon className="w-4 h-4" />
          新建知识库
        </button>
      </div>

      {showCreate && (
        <div className="mb-6 p-5 bg-white rounded-xl border border-slate-200 shadow-sm">
          <div className="flex gap-3">
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="知识库名称"
              className="flex-1 px-3.5 py-2.5 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-shadow"
              autoFocus
            />
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="px-3.5 py-2.5 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="法规">法规</option>
              <option value="政策">政策</option>
              <option value="通知">通知</option>
              <option value="制度">制度</option>
              <option value="其他">其他</option>
            </select>
            <button
              onClick={handleCreate}
              className="px-5 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
            >
              创建
            </button>
            <button
              onClick={() => setShowCreate(false)}
              className="px-4 py-2.5 text-sm text-slate-600 hover:text-slate-900 transition-colors"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {kbList.length === 0 && !loading ? (
        <div className="text-center py-16 text-slate-400">
          <FolderOpenIcon className="w-14 h-14 mx-auto mb-4 text-slate-300" />
          <p className="text-sm">暂无知识库，点击上方按钮创建</p>
        </div>
      ) : (
        <div className="grid gap-3">
          {kbList.map((kb) => (
            <div
              key={kb.knowledge_id}
              className="flex items-center justify-between p-4 bg-white rounded-xl border border-slate-200 hover:border-blue-200 hover:shadow-md cursor-pointer transition-all duration-150"
              onClick={() => navigate(`/knowledge-bases/${kb.knowledge_id}`)}
            >
              <div className="flex items-center gap-3.5">
                <div className="w-10 h-10 bg-blue-50 rounded-lg flex items-center justify-center">
                  <FolderOpenIcon className="w-5 h-5 text-blue-600" />
                </div>
                <div>
                  <p className="text-sm font-medium text-slate-900">{kb.title}</p>
                  <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium mt-1 ${CATEGORY_STYLES[kb.category] || 'bg-slate-50 text-slate-600'}`}>
                    {kb.category}
                  </span>
                </div>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handleDelete(kb.knowledge_id);
                }}
                className="p-2 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
              >
                <TrashIcon className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
