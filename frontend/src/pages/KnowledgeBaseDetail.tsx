import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../api/client';
import { useToast } from '../store/toast';
import type { Document } from '../types';
import {
  ArrowLeftIcon,
  DocumentTextIcon,
  TrashIcon,
} from '@heroicons/react/24/outline';

export default function KnowledgeBaseDetail() {
  const { id } = useParams<{ id: string }>();
  const knowledgeId = Number(id);
  const navigate = useNavigate();
  const [kbTitle, setKbTitle] = useState('');

  return (
    <div className="h-full flex flex-col">
      <header className="flex items-center gap-3 px-6 h-14 border-b border-gray-200 bg-white shrink-0">
        <button onClick={() => navigate('/knowledge-bases')} className="p-1 text-gray-400 hover:text-gray-600">
          <ArrowLeftIcon className="w-5 h-5" />
        </button>
        <h1 className="text-base font-semibold text-gray-900">{kbTitle || '知识库'}</h1>
      </header>

      <div className="flex-1 overflow-auto">
        <DocumentsTab knowledgeId={knowledgeId} onTitleChange={setKbTitle} />
      </div>
    </div>
  );
}

function DocumentsTab({ knowledgeId, onTitleChange }: { knowledgeId: number; onTitleChange: (t: string) => void }) {
  const { showToast } = useToast();
  const [docs, setDocs] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const fetchDocs = useCallback(async () => {
    try {
      setLoading(true);
      const res = await api.get<Document[]>(`/v1/knowledge_base/${knowledgeId}/documents`);
      if (Array.isArray(res.data)) {
        setDocs(res.data);
      }
    } catch (err: any) {
      showToast(err.response?.data?.detail || '获取文档列表失败');
    } finally {
      setLoading(false);
    }
  }, [knowledgeId]);

  useEffect(() => {
    fetchDocs();
  }, [fetchDocs]);

  // Set KB title from first doc's knowledge_id
  useEffect(() => {
    if (docs.length > 0) {
      // We'll set a default title based on the KB
      onTitleChange(`知识库 #${knowledgeId}`);
    } else {
      onTitleChange(`知识库 #${knowledgeId}`);
    }
  }, [docs, knowledgeId, onTitleChange]);

  // Poll for doc status updates
  useEffect(() => {
    const hasProcessing = docs.some((d) => d.process_status === 'pending' || d.process_status === 'processing');
    if (!hasProcessing) return;
    const timer = setInterval(fetchDocs, 3000);
    return () => clearInterval(timer);
  }, [docs, fetchDocs]);

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setUploading(true);
    const formData = new FormData();
    formData.append('knowledge_id', String(knowledgeId));
    formData.append('title', file.name.replace(/\.[^/.]+$/, ''));
    formData.append('category', 'default');
    formData.append('file', file);

    try {
      await api.post('/v1/document', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      fetchDocs();
    } catch (err: any) {
      alert(err.response?.data?.detail || '上传失败');
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const handleDelete = async (docId: number) => {
    if (!confirm('确定要删除这个文档吗？')) return;
    try {
      await api.delete(`/v1/document/${docId}`);
      setDocs((prev) => prev.filter((d) => d.document_id !== docId));
    } catch (err: any) {
      alert(err.response?.data?.detail || '删除失败');
    }
  };

  const statusBadge = (status: string) => {
    const map: Record<string, string> = {
      completed: 'bg-green-100 text-green-700',
      processing: 'bg-yellow-100 text-yellow-700',
      pending: 'bg-gray-100 text-gray-500',
      failed: 'bg-red-100 text-red-700',
    };
    const labels: Record<string, string> = {
      completed: '已完成',
      processing: '解析中',
      pending: '等待中',
      failed: '失败',
    };
    return (
      <span className={`px-2 py-0.5 rounded text-xs font-medium ${map[status] || 'bg-gray-100 text-gray-500'}`}>
        {labels[status] || status}
      </span>
    );
  };

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-gray-500">共 {docs.length} 个文档</p>
        <div>
          <input type="file" ref={fileRef} onChange={handleUpload} accept=".pdf,.docx,.doc" className="hidden" />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            className="flex items-center gap-1.5 px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50"
          >
            <DocumentTextIcon className="w-4 h-4" />
            {uploading ? '上传中...' : '上传文档'}
          </button>
        </div>
      </div>

      {loading ? (
        <div className="animate-pulse space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-16 bg-gray-100 rounded-xl" />
          ))}
        </div>
      ) : docs.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          <DocumentTextIcon className="w-12 h-12 mx-auto mb-3" />
          <p className="text-sm">暂无文档，点击右上角上传</p>
        </div>
      ) : (
        <div className="space-y-2">
          {docs.map((doc) => (
            <div key={doc.document_id} className="flex items-center justify-between p-4 bg-white rounded-xl border border-gray-200">
              <div className="flex items-center gap-3 min-w-0">
                <DocumentTextIcon className="w-5 h-5 text-gray-400 shrink-0" />
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-900 truncate">{doc.title}</p>
                  <p className="text-xs text-gray-400">{doc.file_type}</p>
                </div>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                {statusBadge(doc.process_status)}
                <button
                  onClick={() => handleDelete(doc.document_id)}
                  className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg"
                >
                  <TrashIcon className="w-4 h-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

