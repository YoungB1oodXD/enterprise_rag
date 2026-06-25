import { useState, useEffect, useRef, useCallback } from 'react';
import api from '../api/client';
import { useChat } from '../hooks/useChat';
import { useToast } from '../store/toast';
import type { KnowledgeBase, Conversation, ConversationDetail, ChatMessage, ConversationListResponse } from '../types';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import {
  ChatBubbleLeftRightIcon,
  PlusIcon,
  TrashIcon,
  PaperAirplaneIcon,
  StopIcon,
  ChevronDownIcon,
  ChevronUpIcon,
} from '@heroicons/react/24/outline';

export default function Chat() {
  const { showToast } = useToast();
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedKbId, setSelectedKbId] = useState<number | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<number | null>(null);
  const [convLoading, setConvLoading] = useState(false);
  const [kbLoading, setKbLoading] = useState(true);
  const [convPage, setConvPage] = useState(1);
  const [convTotal, setConvTotal] = useState(0);
  const [convSearch, setConvSearch] = useState('');
  const pageSize = 20;
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { messages, streamingContent, sources, loading, error, sendMessage, stopStreaming, loadConversation, retryLastMessage } = useChat({
    knowledgeId: selectedKbId ?? 0,
    conversationId: activeConvId,
  });

  // 1. 加载知识库列表
  useEffect(() => {
    const fetch = async () => {
      try {
        setKbLoading(true);
        const res = await api.get<KnowledgeBase[]>('/v1/knowledge_base/list');
        if (Array.isArray(res.data)) {
          setKnowledgeBases(res.data);
          if (res.data.length > 0 && selectedKbId === null) {
            setSelectedKbId(res.data[0].knowledge_id);
          }
        }
      } catch (err: any) {
        showToast(err.response?.data?.detail || '获取知识库列表失败');
      } finally {
        setKbLoading(false);
      }
    };
    fetch();
  }, []);

  // 2. 加载会话列表（支持搜索与分页）
  const fetchConversations = useCallback(async (kbId: number, keyword: string, pageNum: number) => {
    setConvLoading(true);
    try {
      const res = await api.get<ConversationListResponse>('/v1/conversation/list', {
        params: { knowledge_id: kbId, search: keyword, page: pageNum, page_size: pageSize },
      });
      if (res.data.items) {
        setConversations(res.data.items);
        setConvTotal(res.data.total);
      }
    } catch {
      showToast('获取会话列表失败');
    } finally {
      setConvLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!selectedKbId) return;
    setActiveConvId(null);
    loadConversation([]);
    setConvPage(1);
    setConvSearch('');
    fetchConversations(selectedKbId, '', 1);
  }, [selectedKbId]);

  // 搜索防抖
  const handleSearchChange = (value: string) => {
    setConvSearch(value);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    searchTimerRef.current = setTimeout(() => {
      if (selectedKbId) {
        setConvPage(1);
        fetchConversations(selectedKbId, value, 1);
      }
    }, 300);
  };

  const handlePageChange = (newPage: number) => {
    if (!selectedKbId || newPage < 1) return;
    setConvPage(newPage);
    fetchConversations(selectedKbId, convSearch, newPage);
  };

  // 3. 选中会话时加载消息
  const handleSelectConversation = useCallback(async (convId: number) => {
    setActiveConvId(convId);
    try {
      const res = await api.get<ConversationDetail>(`/v1/conversation/${convId}`);
      const msgs: ChatMessage[] = (res.data.messages || []).map((m) => ({
        role: m.role as 'user' | 'assistant',
        content: m.content,
      }));
      loadConversation(msgs);
    } catch {
      showToast('获取会话详情失败');
      loadConversation([]);
    }
  }, [loadConversation, showToast]);

  // 4. 创建新会话
  const handleNewConversation = useCallback(async () => {
    if (!selectedKbId) return;
    try {
      const res = await api.post('/v1/conversation', { knowledge_id: selectedKbId });
      const conv: Conversation = res.data;
      setActiveConvId(conv.conversation_id);
      loadConversation([]);
      setConvPage(1);
      setConvSearch('');
      fetchConversations(selectedKbId, '', 1);
    } catch {
      showToast('创建会话失败');
    }
  }, [selectedKbId, loadConversation, fetchConversations, showToast]);

  // 5. 删除会话
  const handleDeleteConversation = useCallback(async (convId: number, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('确定要删除这个对话吗？')) return;
    try {
      await api.delete(`/v1/conversation/${convId}`);
      setConversations((prev) => prev.filter((c) => c.conversation_id !== convId));
      if (activeConvId === convId) {
        setActiveConvId(null);
        loadConversation([]);
      }
    } catch {
      showToast('删除会话失败');
    }
  }, [activeConvId, loadConversation, showToast]);

  // 6. 发送消息
  const handleSend = () => {
    if (!input.trim() || loading) return;
    sendMessage(input.trim(), activeConvId ?? undefined);
    setInput('');
  };

  // ----- 会话标题编辑 -----
  const [editingConvId, setEditingConvId] = useState<number | null>(null);
  const [editingTitle, setEditingTitle] = useState('');

  const handleStartEditTitle = (convId: number, currentTitle: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingConvId(convId);
    setEditingTitle(currentTitle);
  };

  const handleSaveTitle = async () => {
    if (editingConvId === null) return;
    const trimmed = editingTitle.trim();
    if (!trimmed) return;
    try {
      await api.put(`/v1/conversation/${editingConvId}`, { title: trimmed });
      setConversations((prev) =>
        prev.map((c) => (c.conversation_id === editingConvId ? { ...c, title: trimmed } : c))
      );
    } catch {
      showToast('重命名失败');
    } finally {
      setEditingConvId(null);
      setEditingTitle('');
    }
  };

  const handleCancelEditTitle = () => {
    setEditingConvId(null);
    setEditingTitle('');
  };

  // ----- ChatTab 内部状态 -----
  const [input, setInput] = useState('');
  const [expandedSources, setExpandedSources] = useState<Record<number, boolean>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textAreaRef = useRef<HTMLTextAreaElement>(null);

  const handleTextAreaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    const el = e.target;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  };

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const toggleSource = (idx: number) => {
    setExpandedSources((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  const totalPages = Math.ceil(convTotal / pageSize);

  return (
    <div className="h-full flex flex-col">
      {/* ── 顶部：知识库选择器 + 新对话按钮 ── */}
      <div className="flex items-center gap-3 px-6 h-14 border-b border-slate-200 bg-white shrink-0">
        <ChatBubbleLeftRightIcon className="w-5 h-5 text-blue-600" />
        <span className="font-semibold text-slate-900">智能问答</span>
        <div className="ml-auto flex items-center gap-3">
          <select
            value={selectedKbId ?? ''}
            onChange={(e) => setSelectedKbId(Number(e.target.value) || null)}
            className="px-3 py-1.5 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white transition-shadow"
          >
            {kbLoading ? (
              <option value="">加载中...</option>
            ) : knowledgeBases.length === 0 ? (
              <option value="">暂无知识库</option>
            ) : (
              knowledgeBases.map((kb) => (
                <option key={kb.knowledge_id} value={kb.knowledge_id}>
                  {kb.title}
                </option>
              ))
            )}
          </select>
          <button
            onClick={handleNewConversation}
            disabled={!selectedKbId}
            className="flex items-center gap-1.5 px-3.5 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            <PlusIcon className="w-4 h-4" />
            新对话
          </button>
        </div>
      </div>

      {/* ── 主内容区：会话列表 + 聊天区 ── */}
      <div className="flex-1 flex overflow-hidden">
        {/* 左侧：会话列表 */}
        <aside className="w-64 border-r border-slate-200 bg-white flex flex-col shrink-0">
          <div className="px-4 py-3 border-b border-slate-100 space-y-2">
            <h2 className="text-xs font-semibold text-slate-400">对话历史</h2>
            {selectedKbId && (
              <input
                type="text"
                value={convSearch}
                onChange={(e) => handleSearchChange(e.target.value)}
                placeholder="搜索对话..."
                className="w-full px-2.5 py-1.5 border border-slate-300 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-blue-500 transition-shadow"
              />
            )}
          </div>
          <div className="flex-1 overflow-auto">
            {convLoading ? (
              <div className="p-4 space-y-3">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-12 bg-slate-100 rounded-lg animate-pulse" />
                ))}
              </div>
            ) : conversations.length === 0 ? (
              <div className="p-6 text-center text-slate-400 text-sm">
                <p>{convSearch ? '未找到匹配的对话' : (selectedKbId ? '暂无对话' : '请先选择知识库')}</p>
              </div>
            ) : (
              <div className="py-1">
                {conversations.map((conv) => (
                  <div
                    key={conv.conversation_id}
                    onClick={() => handleSelectConversation(conv.conversation_id)}
                    className={`group flex items-center gap-2 px-4 py-3 cursor-pointer text-sm border-l-[3px] transition-all duration-150 ${
                      activeConvId === conv.conversation_id
                        ? 'border-l-blue-600 bg-blue-50 text-blue-700'
                        : 'border-l-transparent text-slate-700 hover:bg-slate-50 hover:border-l-slate-300'
                    }`}
                  >
                    {editingConvId === conv.conversation_id ? (
                      <input
                        value={editingTitle}
                        onChange={(e) => setEditingTitle(e.target.value)}
                        onBlur={handleSaveTitle}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleSaveTitle();
                          if (e.key === 'Escape') handleCancelEditTitle();
                        }}
                        onClick={(e) => e.stopPropagation()}
                        autoFocus
                        className="flex-1 px-2 py-0.5 border border-blue-300 rounded text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                      />
                    ) : (
                      <span
                        className="flex-1 truncate"
                        onDoubleClick={(e) => handleStartEditTitle(conv.conversation_id, conv.title, e)}
                      >
                        {conv.title}
                      </span>
                    )}
                    <span className="text-xs text-slate-400 shrink-0">{conv.message_count}</span>
                    <button
                      onClick={(e) => handleDeleteConversation(conv.conversation_id, e)}
                      className="p-1 text-slate-300 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-all"
                    >
                      <TrashIcon className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
            {/* 分页控件 */}
            {!convLoading && totalPages > 1 && (
              <div className="flex items-center justify-between px-4 py-2.5 border-t border-slate-100 text-xs text-slate-500">
                <button
                  onClick={() => handlePageChange(convPage - 1)}
                  disabled={convPage <= 1}
                  className="px-2 py-1 rounded hover:bg-slate-100 disabled:opacity-30 transition-colors"
                >
                  上一页
                </button>
                <span className="text-slate-400">第 {convPage} / {totalPages} 页</span>
                <button
                  onClick={() => handlePageChange(convPage + 1)}
                  disabled={convPage >= totalPages}
                  className="px-2 py-1 rounded hover:bg-slate-100 disabled:opacity-30 transition-colors"
                >
                  下一页
                </button>
              </div>
            )}
          </div>
        </aside>

        {/* 右侧：聊天区 */}
        <main className="flex-1 flex flex-col bg-slate-50/50">
          {!selectedKbId ? (
            <div className="flex-1 flex items-center justify-center text-slate-400">
              <div className="text-center">
                <ChatBubbleLeftRightIcon className="w-14 h-14 mx-auto mb-4 text-slate-300" />
                <p className="text-sm">请选择一个知识库开始对话</p>
              </div>
            </div>
          ) : (
            <div className="flex-1 flex flex-col">
              {/* 消息列表 */}
              <div className="flex-1 overflow-auto p-6">
                <div className="max-w-3xl mx-auto space-y-5">
                  {messages.length === 0 && !streamingContent && !error && (
                    <div className="text-center py-16 text-slate-400">
                      <p className="text-sm">
                        {activeConvId ? '继续对话，输入你的问题' : '选择一个对话或点击"新对话"开始'}
                      </p>
                    </div>
                  )}

                  {error && (
                    <div className="flex justify-center">
                      <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-4 py-3 text-sm max-w-[75%] flex items-center gap-3 shadow-sm">
                        <span>{error}</span>
                        <button
                          onClick={retryLastMessage}
                          className="shrink-0 px-3 py-1 bg-red-600 text-white text-xs rounded-lg hover:bg-red-700 transition-colors"
                        >
                          重试
                        </button>
                      </div>
                    </div>
                  )}

                  {messages.map((msg, i) => (
                    <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                      <div
                        className={`max-w-[70%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
                          msg.role === 'user'
                            ? 'bg-blue-600 text-white shadow-sm'
                            : 'bg-white border border-slate-200 text-slate-800 shadow-sm prose prose-sm max-w-none'
                        }`}
                      >
                        {msg.role === 'user' ? (
                          msg.content
                        ) : (
                          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                            {msg.content}
                          </ReactMarkdown>
                        )}
                      </div>
                    </div>
                  ))}

                  {streamingContent && (
                    <div className="flex justify-start">
                      <div className="max-w-[70%] rounded-2xl px-4 py-3 bg-white border border-slate-200 shadow-sm text-sm leading-relaxed text-slate-800 prose prose-sm max-w-none">
                        <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
                          {streamingContent}
                        </ReactMarkdown>
                        <span className="inline-block w-2 h-4 bg-blue-600 ml-0.5 animate-pulse rounded-sm" />
                      </div>
                    </div>
                  )}

                  {sources.length > 0 && (
                    <div className="bg-white border border-slate-200 rounded-xl p-4 text-sm shadow-sm">
                      <p className="text-xs font-medium text-slate-500 mb-2">参考来源</p>
                      {sources.map((src, i) => (
                        <div key={i} className="mb-1.5 last:mb-0">
                          <button
                            onClick={() => toggleSource(i)}
                            className="flex items-center gap-1 text-blue-600 hover:text-blue-800 text-xs transition-colors"
                          >
                            {expandedSources[i] ? <ChevronUpIcon className="w-3 h-3" /> : <ChevronDownIcon className="w-3 h-3" />}
                            [{i + 1}] {src.document_name} · 第{src.page_number}页 · {src.chunk_content?.slice(0, 50)}{src.chunk_content?.length > 50 ? '...' : ''}
                          </button>
                          {expandedSources[i] && (
                            <p className="mt-1.5 text-xs text-slate-600 bg-slate-50 rounded-lg p-3 border border-slate-100 whitespace-pre-wrap leading-relaxed">
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

              {/* 输入区 */}
              <div className="border-t border-slate-200 bg-white p-4 shrink-0">
                <div className="max-w-3xl mx-auto flex gap-2">
                  <textarea
                    ref={textAreaRef}
                    value={input}
                    onChange={handleTextAreaChange}
                    onKeyDown={handleKeyDown}
                    placeholder={activeConvId ? '输入你的问题...' : '请先创建或选择一个对话'}
                    rows={1}
                    disabled={!activeConvId}
                    className="flex-1 px-4 py-2.5 border border-slate-300 rounded-lg text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-slate-50 disabled:text-slate-400 overflow-hidden transition-shadow"
                  />
                  {loading ? (
                    <button
                      onClick={stopStreaming}
                      className="px-4 py-2.5 bg-red-500 text-white rounded-lg hover:bg-red-600 transition-colors"
                    >
                      <StopIcon className="w-5 h-5" />
                    </button>
                  ) : (
                    <button
                      onClick={handleSend}
                      disabled={!input.trim() || !activeConvId}
                      className="px-4 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
                    >
                      <PaperAirplaneIcon className="w-5 h-5" />
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
