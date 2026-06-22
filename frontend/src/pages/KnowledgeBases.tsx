import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../api/client';
import { useToast } from '../store/toast';
import type { KnowledgeBase, KnowledgeBaseCreateRequest } from '../types';
import { PlusIcon, TrashIcon, FolderOpenIcon } from '@heroicons/react/24/outline';

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
      alert(err.response?.data?.detail || '创建失败');
    }
  };

  const handleDelete = async (id: number) => {
    if (!confirm('确定要删除这个知识库吗？')) return;
    try {
      await api.delete(`/v1/knowledge_base/${id}`);
      setKbList((prev) => prev.filter((kb) => kb.knowledge_id !== id));
    } catch (err: any) {
      alert(err.response?.data?.detail || '删除失败');
    }
  };

  if (loading) {
    return (
      <div className="p-8">
        <div className="animate-pulse space-y-4">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-20 bg-gray-100 rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">知识库</h1>
          <p className="text-sm text-gray-500 mt-1">管理你的知识库和文档</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700"
        >
          <PlusIcon className="w-4 h-4" />
          新建知识库
        </button>
      </div>

      {showCreate && (
        <div className="mb-6 p-4 bg-white rounded-xl border border-gray-200 shadow-sm">
          <div className="flex gap-3">
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="知识库名称"
              className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              autoFocus
            />
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="法规">法规</option>
              <option value="政策">政策</option>
              <option value="通知">通知</option>
              <option value="制度">制度</option>
              <option value="其他">其他</option>
            </select>
            <button
              onClick={handleCreate}
              className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700"
            >
              创建
            </button>
            <button
              onClick={() => setShowCreate(false)}
              className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {kbList.length === 0 && !loading ? (
        <div className="text-center py-16 text-gray-400">
          <FolderOpenIcon className="w-12 h-12 mx-auto mb-3" />
          <p className="text-sm">暂无知识库，点击上方按钮创建</p>
        </div>
      ) : (
        <div className="grid gap-3">
          {kbList.map((kb) => (
            <div
              key={kb.knowledge_id}
              className="flex items-center justify-between p-4 bg-white rounded-xl border border-gray-200 hover:border-indigo-200 cursor-pointer transition-colors"
              onClick={() => navigate(`/knowledge-bases/${kb.knowledge_id}`)}
            >
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-indigo-50 rounded-lg flex items-center justify-center">
                  <FolderOpenIcon className="w-5 h-5 text-indigo-600" />
                </div>
                <div>
                  <p className="text-sm font-medium text-gray-900">{kb.title}</p>
                  <p className="text-xs text-gray-500">{kb.category}</p>
                </div>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  handleDelete(kb.knowledge_id);
                }}
                className="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg"
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
