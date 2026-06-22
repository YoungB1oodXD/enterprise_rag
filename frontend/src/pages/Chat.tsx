import { useState, useEffect, useRef, useCallback } from 'react';
import api from '../api/client';
import { useChat } from '../hooks/useChat';
import { useToast } from '../store/toast';
import type { KnowledgeBase, Conversation, ConversationDetail, ChatMessage } from '../types';
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

  const { messages, streamingContent, sources, loading, error, sendMessage, stopStreaming, loadConversation } = useChat({
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

  // 2. 切换知识库时加载会话列表
  useEffect(() => {
    if (!selectedKbId) return;
    setActiveConvId(null);
    loadConversation([]);
    setConvLoading(true);

    api.get<Conversation[]>('/v1/conversation/list', { params: { knowledge_id: selectedKbId } })
      .then((res) => {
        if (Array.isArray(res.data)) {
          setConversations(res.data);
        }
      })
      .catch(() => showToast('获取会话列表失败'))
      .finally(() => setConvLoading(false));
  }, [selectedKbId]);

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
      setConversations((prev) => [conv, ...prev]);
      setActiveConvId(conv.conversation_id);
      loadConversation([]);
    } catch {
      showToast('创建会话失败');
    }
  }, [selectedKbId, loadConversation, showToast]);

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

  // ----- ChatTab 内部状态 (移自旧 ChatTab) -----
  const [input, setInput] = useState('');
  const [expandedSources, setExpandedSources] = useState<Record<number, boolean>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);

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

  return (
    <div className="h-full flex flex-col">
      {/* ── 顶部：知识库选择器 + 新对话按钮 ── */}
      <div className="flex items-center gap-3 px-6 h-14 border-b border-gray-200 bg-white shrink-0">
        <ChatBubbleLeftRightIcon className="w-5 h-5 text-indigo-600" />
        <span className="font-semibold text-gray-900">智能问答</span>
        <div className="ml-auto flex items-center gap-3">
          <select
            value={selectedKbId ?? ''}
            onChange={(e) => setSelectedKbId(Number(e.target.value) || null)}
            className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"
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
            className="flex items-center gap-1 px-3 py-1.5 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-50"
          >
            <PlusIcon className="w-4 h-4" />
            新对话
          </button>
        </div>
      </div>

      {/* ── 主内容区：会话列表 + 聊天区 ── */}
      <div className="flex-1 flex overflow-hidden">
        {/* 左侧：会话列表 */}
        <aside className="w-64 border-r border-gray-200 bg-white flex flex-col shrink-0">
          <div className="px-4 py-3 border-b border-gray-100">
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wider">对话历史</h2>
          </div>
          <div className="flex-1 overflow-auto">
            {convLoading ? (
              <div className="p-4 space-y-3">
                {[1, 2, 3].map((i) => (
                  <div key={i} className="h-12 bg-gray-100 rounded-lg animate-pulse" />
                ))}
              </div>
            ) : conversations.length === 0 ? (
              <div className="p-6 text-center text-gray-400 text-sm">
                <p>{selectedKbId ? '暂无对话' : '请先选择知识库'}</p>
              </div>
            ) : (
              <div className="py-1">
                {conversations.map((conv) => (
                  <div
                    key={conv.conversation_id}
                    onClick={() => handleSelectConversation(conv.conversation_id)}
                    className={`group flex items-center gap-2 px-4 py-3 cursor-pointer text-sm border-l-2 ${
                      activeConvId === conv.conversation_id
                        ? 'border-indigo-600 bg-indigo-50 text-indigo-700'
                        : 'border-transparent text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    <span className="flex-1 truncate">{conv.title}</span>
                    <span className="text-xs text-gray-400 shrink-0">{conv.message_count}</span>
                    <button
                      onClick={(e) => handleDeleteConversation(conv.conversation_id, e)}
                      className="p-1 text-gray-300 hover:text-red-500 opacity-0 group-hover:opacity-100"
                    >
                      <TrashIcon className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>

        {/* 右侧：聊天区 */}
        <main className="flex-1 flex flex-col bg-gray-50">
          {!selectedKbId ? (
            <div className="flex-1 flex items-center justify-center text-gray-400">
              <div className="text-center">
                <ChatBubbleLeftRightIcon className="w-12 h-12 mx-auto mb-3" />
                <p className="text-sm">请选择一个知识库开始对话</p>
              </div>
            </div>
          ) : (
            <div className="flex-1 flex flex-col">
              {/* 消息列表 */}
              <div className="flex-1 overflow-auto p-6">
                <div className="max-w-3xl mx-auto space-y-4">
                  {messages.length === 0 && !streamingContent && !error && (
                    <div className="text-center py-16 text-gray-400">
                      <p className="text-sm">
                        {activeConvId ? '继续对话，输入你的问题' : '选择一个对话或点击"新对话"开始'}
                      </p>
                    </div>
                  )}

                  {error && (
                    <div className="flex justify-center">
                      <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-4 py-3 text-sm max-w-[75%]">
                        {error}
                      </div>
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
                            [{i + 1}] {src.document_name} · 第{src.page_number}页 · {src.chunk_content?.slice(0, 50)}{src.chunk_content?.length > 50 ? '...' : ''}
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

              {/* 输入区 */}
              <div className="border-t border-gray-200 bg-white p-4 shrink-0">
                <div className="max-w-3xl mx-auto flex gap-2">
                  <textarea
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder={activeConvId ? '输入你的问题...' : '请先创建或选择一个对话'}
                    rows={1}
                    disabled={!activeConvId}
                    className="flex-1 px-4 py-2.5 border border-gray-300 rounded-lg text-sm resize-none focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 disabled:bg-gray-50 disabled:text-gray-400"
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
                      disabled={!input.trim() || !activeConvId}
                      className="px-4 py-2.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50"
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
