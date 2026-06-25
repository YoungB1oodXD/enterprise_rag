import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../api/client';
import { useToast } from '../store/toast';
import type { Document } from '../types';
import {
  ArrowLeftIcon,
  DocumentTextIcon,
  TrashIcon,
  EyeIcon,
  XMarkIcon,
} from '@heroicons/react/24/outline';

export default function KnowledgeBaseDetail() {
  const { id } = useParams<{ id: string }>();
  const knowledgeId = Number(id);
  const navigate = useNavigate();
  const [kbTitle, setKbTitle] = useState('');

  return (
    <div className="h-full flex flex-col">
      <header className="flex items-center gap-3 px-6 h-14 border-b border-slate-200 bg-white shrink-0">
        <button onClick={() => navigate('/knowledge-bases')} className="p-1 text-slate-400 hover:text-slate-600 transition-colors">
          <ArrowLeftIcon className="w-5 h-5" />
        </button>
        <h1 className="text-base font-semibold text-slate-900">{kbTitle || '知识库'}</h1>
      </header>

      <div className="flex-1 overflow-auto">
        <DocumentsTab knowledgeId={knowledgeId} onTitleChange={setKbTitle} />
      </div>
    </div>
  );
}

const STATUS_MAP: Record<string, string> = {
  completed: 'bg-emerald-50 text-emerald-700',
  processing: 'bg-amber-50 text-amber-700',
  pending: 'bg-slate-50 text-slate-500',
  failed: 'bg-red-50 text-red-700',
};

const STATUS_LABELS: Record<string, string> = {
  completed: '已完成',
  processing: '解析中',
  pending: '等待中',
  failed: '失败',
};

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${STATUS_MAP[status] || 'bg-slate-100 text-slate-500'}`}>
      {STATUS_LABELS[status] || status}
    </span>
  );
}

function DocumentsTab({ knowledgeId, onTitleChange }: { knowledgeId: number; onTitleChange: (t: string) => void }) {
  const { showToast } = useToast();
  const [docs, setDocs] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [previewDocId, setPreviewDocId] = useState<number | null>(null);
  const [previewTitle, setPreviewTitle] = useState('');
  const [previewFileType, setPreviewFileType] = useState('');
  const [previewTextContent, setPreviewTextContent] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
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

  useEffect(() => {
    onTitleChange(`知识库 #${knowledgeId}`);
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
      showToast(err.response?.data?.detail || '上传失败');
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
      showToast(err.response?.data?.detail || '删除失败');
    }
  };

  const handlePreview = (docId: number, title: string, fileType: string) => {
    setPreviewDocId(docId);
    setPreviewTitle(title);
    setPreviewFileType(fileType);

    const textTypes = ['text/plain', 'text/markdown', 'application/json', 'text/csv', 'application/csv'];
    if (textTypes.includes(fileType)) {
      setPreviewLoading(true);
      setPreviewTextContent(null);
      api.get(`/v1/document/${docId}/file`, { responseType: 'text' }).then((res) => {
        setPreviewTextContent(res.data);
      }).catch(() => {
        setPreviewTextContent('加载文件内容失败');
      }).finally(() => {
        setPreviewLoading(false);
      });
    } else {
      setPreviewTextContent(null);
    }
  };

  const isPdf = previewFileType === 'application/pdf' || previewFileType.includes('pdf');

  const renderPreviewContent = () => {
    if (previewLoading) {
      return (
        <div className="flex items-center justify-center h-full text-slate-400">
          <p className="text-sm">加载中...</p>
        </div>
      );
    }

    if (previewTextContent !== null) {
      const isCsv = previewFileType === 'text/csv' || previewFileType === 'application/csv';
      if (isCsv) {
        const lines = previewTextContent.split('\n').filter(Boolean);
        const rows = lines.map((l) => l.split(','));
        return (
          <div className="overflow-auto h-full p-4">
            <table className="w-full text-xs border-collapse">
              <tbody>
                {rows.map((cols, ri) => (
                  <tr key={ri} className={ri === 0 ? 'bg-slate-50 font-medium' : ''}>
                    {cols.map((c, ci) => <td key={ci} className="border border-slate-200 px-3 py-1.5 whitespace-nowrap">{c}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      }
      return (
        <div className="overflow-auto h-full p-4">
          <pre className="text-xs text-slate-800 leading-relaxed whitespace-pre-wrap font-mono">{previewTextContent}</pre>
        </div>
      );
    }

    // PDF
    if (isPdf) {
      const token = localStorage.getItem('token') || '';
      return (
        <iframe
          src={`/v1/document/${previewDocId}/file?token=${token}`}
          className="w-full h-full"
          title={previewTitle}
        />
      );
    }

    // 不支持预览的格式
    return (
      <div className="flex flex-col items-center justify-center h-full text-slate-400">
        <DocumentTextIcon className="w-14 h-14 mb-3 text-slate-300" />
        <p className="text-sm mb-4">该格式暂不支持在线预览</p>
        <a
          href={`/v1/document/${previewDocId}/file`}
          download
          className="px-5 py-2.5 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 transition-colors"
        >
          下载文件
        </a>
      </div>
    );
  };

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-5">
        <p className="text-sm text-slate-500">共 {docs.length} 个文档</p>
        <div>
          <input type="file" ref={fileRef} onChange={handleUpload} accept=".pdf,.docx,.doc" className="hidden" />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            className="flex items-center gap-1.5 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            <DocumentTextIcon className="w-4 h-4" />
            {uploading ? '上传中...' : '上传文档'}
          </button>
        </div>
      </div>

      {loading ? (
        <div className="animate-pulse space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-16 bg-slate-100 rounded-xl" />
          ))}
        </div>
      ) : docs.length === 0 ? (
        <div className="text-center py-16 text-slate-400">
          <DocumentTextIcon className="w-14 h-14 mx-auto mb-4 text-slate-300" />
          <p className="text-sm">暂无文档，点击右上角上传</p>
        </div>
      ) : (
        <div className="space-y-2">
          {docs.map((doc) => (
            <div
              key={doc.document_id}
              className="flex items-center justify-between p-4 bg-white rounded-xl border border-slate-200 hover:border-slate-300 transition-colors"
            >
              <div className="flex items-center gap-3.5 min-w-0">
                <div className="w-9 h-9 bg-slate-50 rounded-lg flex items-center justify-center shrink-0">
                  <DocumentTextIcon className="w-4.5 h-4.5 text-slate-400" />
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-slate-900 truncate">{doc.title}</p>
                  <p className="text-xs text-slate-400 mt-0.5">{doc.file_type}</p>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <StatusBadge status={doc.process_status} />
                {doc.process_status === 'completed' && (
                  <button
                    onClick={() => handlePreview(doc.document_id, doc.title, doc.file_type)}
                    className="p-1.5 text-slate-400 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
                    title="预览"
                  >
                    <EyeIcon className="w-4 h-4" />
                  </button>
                )}
                <button
                  onClick={() => handleDelete(doc.document_id)}
                  className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                >
                  <TrashIcon className="w-4 h-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 文档预览弹窗 */}
      {previewDocId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={() => setPreviewDocId(null)}>
          <div className="bg-white rounded-2xl shadow-xl w-[90vw] h-[85vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 shrink-0">
              <h3 className="text-sm font-medium text-slate-900 truncate">{previewTitle}</h3>
              <button onClick={() => setPreviewDocId(null)} className="p-1 text-slate-400 hover:text-slate-600 transition-colors">
                <XMarkIcon className="w-5 h-5" />
              </button>
            </div>
            <div className="flex-1 min-h-0">
              {renderPreviewContent()}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
