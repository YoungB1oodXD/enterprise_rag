import { useState, useEffect, useRef, useCallback } from 'react';
import api from '../api/client';
import { useChat } from '../hooks/useChat';
import { useToast } from '../store/toast';
import type { KnowledgeBase, Conversation, ConversationDetail, ChatMessage, ConversationListResponse } from '../types';
import {
  ChatBubbleLeftRightIcon,
  PlusIcon,
} from '@heroicons/react/24/outline';
import ChatSidebar from '../components/ChatSidebar';
import MessageList from '../components/MessageList';
import ChatInput from '../components/ChatInput';

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
  const selectConvIdRef = useRef<number | null>(null);

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
  }, [selectedKbId, fetchConversations]);

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

  // 3. 选中会话时加载消息（带 stale 保护）
  const handleSelectConversation = useCallback(async (convId: number) => {
    selectConvIdRef.current = convId;
    setActiveConvId(convId);
    try {
      const res = await api.get<ConversationDetail>(`/v1/conversation/${convId}`);
      if (selectConvIdRef.current !== convId) return;
      const msgs: ChatMessage[] = (res.data.messages || []).map((m) => ({
        role: m.role as 'user' | 'assistant',
        content: m.content,
        sources: m.sources,
      }));
      loadConversation(msgs);
    } catch {
      if (selectConvIdRef.current !== convId) return;
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
  const [input, setInput] = useState('');
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

  // ----- 内部状态 -----
  const [expandedSources, setExpandedSources] = useState<Record<number, boolean>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);

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
        <ChatSidebar
          conversations={conversations}
          convLoading={convLoading}
          convSearch={convSearch}
          convPage={convPage}
          totalPages={totalPages}
          selectedKbId={selectedKbId}
          activeConvId={activeConvId}
          editingConvId={editingConvId}
          editingTitle={editingTitle}
          onSearchChange={handleSearchChange}
          onSelectConversation={handleSelectConversation}
          onDeleteConversation={handleDeleteConversation}
          onStartEditTitle={handleStartEditTitle}
          onSaveTitle={handleSaveTitle}
          onCancelEditTitle={handleCancelEditTitle}
          onPageChange={handlePageChange}
          setEditingTitle={setEditingTitle}
        />

        {/* 右侧：聊天区 */}
        <main className="flex-1 flex flex-col bg-slate-50/50 min-h-0">
          {!selectedKbId ? (
            <div className="flex-1 flex items-center justify-center text-slate-400">
              <div className="text-center">
                <ChatBubbleLeftRightIcon className="w-14 h-14 mx-auto mb-4 text-slate-300" />
                <p className="text-sm">请选择一个知识库开始对话</p>
              </div>
            </div>
          ) : (
            <div className="flex-1 flex flex-col min-h-0">
              {/* 消息列表 */}
              <div className="flex-1 overflow-auto p-6 min-h-0">
                <MessageList
                  messages={messages}
                  streamingContent={streamingContent}
                  streamingSources={sources}
                  error={error}
                  expandedSources={expandedSources}
                  activeConvId={activeConvId}
                  onToggleSource={toggleSource}
                  onRetry={retryLastMessage}
                />
                <div ref={messagesEndRef} />
              </div>

              {/* 输入区 */}
              <ChatInput
                input={input}
                loading={loading}
                disabled={!activeConvId}
                onInputChange={handleTextAreaChange}
                onSend={handleSend}
                onStopStreaming={stopStreaming}
                onKeyDown={handleKeyDown}
              />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
