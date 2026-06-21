import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../api/client';
import { useChat } from '../hooks/useChat';
import type { Document } from '../types';
import {
  ArrowLeftIcon,
  DocumentTextIcon,
  TrashIcon,
  PaperAirplaneIcon,
  StopIcon,
  ChevronDownIcon,
  ChevronUpIcon,
} from '@heroicons/react/24/outline';

type Tab = 'documents' | 'chat';

export default function KnowledgeBaseDetail() {
  const { id } = useParams<{ id: string }>();
  const knowledgeId = Number(id);
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>('documents');
  const [kbTitle, setKbTitle] = useState('');

  return (
    <div className="h-full flex flex-col">
      <header className="flex items-center gap-3 px-6 h-14 border-b border-gray-200 bg-white shrink-0">
        <button onClick={() => navigate('/knowledge-bases')} className="p-1 text-gray-400 hover:text-gray-600">
          <ArrowLeftIcon className="w-5 h-5" />
        </button>
        <h1 className="text-base font-semibold text-gray-900">{kbTitle || '知识库'}</h1>
      </header>

      <div className="flex gap-0 border-b border-gray-200 px-6 bg-white shrink-0">
        <button
          onClick={() => setTab('documents')}
          className={`px-4 py-3 text-sm font-medium border-b-2 -mb-px ${
            tab === 'documents' ? 'border-indigo-600 text-indigo-600' : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          文档管理
        </button>
        <button
          onClick={() => setTab('chat')}
          className={`px-4 py-3 text-sm font-medium border-b-2 -mb-px ${
            tab === 'chat' ? 'border-indigo-600 text-indigo-600' : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          智能问答
        </button>
      </div>

      <div className="flex-1 overflow-auto">
        {tab === 'documents' ? (
          <DocumentsTab knowledgeId={knowledgeId} onTitleChange={setKbTitle} />
        ) : (
          <ChatTab knowledgeId={knowledgeId} />
        )}
      </div>
    </div>
  );
}

function DocumentsTab({ knowledgeId, onTitleChange }: { knowledgeId: number; onTitleChange: (t: string) => void }) {
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
    } catch {
      // ignore
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

function ChatTab({ knowledgeId }: { knowledgeId: number }) {
  const { messages, streamingContent, sources, loading, sendMessage, stopStreaming } = useChat({ knowledgeId });
  const [input, setInput] = useState('');
  const [expandedSources, setExpandedSources] = useState<Record<number, boolean>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  const handleSend = () => {
    if (!input.trim() || loading) return;
    sendMessage(input.trim());
    setInput('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const toggleSource = (idx: number) => {
    setExpandedSources((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  return (
    <div className="h-full flex flex-col">
      <div className="flex-1 overflow-auto p-6">
        <div className="max-w-3xl mx-auto space-y-4">
          {messages.length === 0 && !streamingContent && (
            <div className="text-center py-16 text-gray-400">
              <p className="text-sm">向知识库提问，获取基于文档的智能回答</p>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[75%] rounded-xl px-4 py-3 text-sm leading-relaxed ${
                  msg.role === 'user'
                    ? 'bg-indigo-600 text-white'
                    : 'bg-white border border-gray-200 text-gray-800'
                }`}
              >
                {msg.content}
              </div>
            </div>
          ))}

          {streamingContent && (
            <div className="flex justify-start">
              <div className="max-w-[75%] rounded-xl px-4 py-3 bg-white border border-gray-200 text-sm leading-relaxed text-gray-800">
                {streamingContent}
                <span className="inline-block w-2 h-4 bg-indigo-600 ml-0.5 animate-pulse" />
              </div>
            </div>
          )}

          {sources.length > 0 && (
            <div className="bg-gray-50 rounded-xl p-4 text-sm">
              <p className="text-xs font-medium text-gray-500 mb-2">参考来源</p>
              {sources.map((src, i) => (
                <div key={i} className="mb-1 last:mb-0">
                  <button
                    onClick={() => toggleSource(i)}
                    className="flex items-center gap-1 text-indigo-600 hover:text-indigo-800 text-xs"
                  >
                    {expandedSources[i] ? <ChevronUpIcon className="w-3 h-3" /> : <ChevronDownIcon className="w-3 h-3" />}
                    [{i + 1}] {src.document_name} · 第{src.page_number}页 · {src.document_name}
                  </button>
                  {expandedSources[i] && (
                    <p className="mt-1 text-xs text-gray-500 bg-white rounded-lg p-2 border border-gray-100 whitespace-pre-wrap">
                      {src.chunk_content}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      <div className="border-t border-gray-200 bg-white p-4 shrink-0">
        <div className="max-w-3xl mx-auto flex gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入你的问题..."
            rows={1}
            className="flex-1 px-4 py-2.5 border border-gray-300 rounded-lg text-sm resize-none focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
          />
          {loading ? (
            <button
              onClick={stopStreaming}
              className="px-4 py-2.5 bg-red-500 text-white rounded-lg hover:bg-red-600"
            >
              <StopIcon className="w-5 h-5" />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              className="px-4 py-2.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50"
            >
              <PaperAirplaneIcon className="w-5 h-5" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
