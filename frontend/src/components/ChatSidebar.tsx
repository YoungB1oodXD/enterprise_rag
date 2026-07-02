import { TrashIcon } from '@heroicons/react/24/outline';
import type { Conversation } from '../types';

interface ChatSidebarProps {
  conversations: Conversation[];
  convLoading: boolean;
  convSearch: string;
  convPage: number;
  totalPages: number;
  selectedKbId: number | null;
  activeConvId: number | null;
  editingConvId: number | null;
  editingTitle: string;
  onSearchChange: (value: string) => void;
  onSelectConversation: (convId: number) => void;
  onDeleteConversation: (convId: number, e: React.MouseEvent) => void;
  onStartEditTitle: (convId: number, currentTitle: string, e: React.MouseEvent) => void;
  onSaveTitle: () => void;
  onCancelEditTitle: () => void;
  onPageChange: (page: number) => void;
  setEditingTitle: (title: string) => void;
}

export default function ChatSidebar({
  conversations,
  convLoading,
  convSearch,
  convPage,
  totalPages,
  selectedKbId,
  activeConvId,
  editingConvId,
  editingTitle,
  onSearchChange,
  onSelectConversation,
  onDeleteConversation,
  onStartEditTitle,
  onSaveTitle,
  onCancelEditTitle,
  onPageChange,
  setEditingTitle,
}: ChatSidebarProps) {
  return (
    <aside className="w-64 border-r border-slate-200 bg-white flex flex-col shrink-0">
      <div className="px-4 py-3 border-b border-slate-100 space-y-2">
        <h2 className="text-xs font-semibold text-slate-400">对话历史</h2>
        {selectedKbId && (
          <input
            type="text"
            value={convSearch}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="搜索对话..."
            className="w-full px-2.5 py-1.5 border border-slate-300 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-blue-500 transition-shadow"
          />
        )}
      </div>
      <div className="flex-1 overflow-auto min-h-0">
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
                onClick={() => onSelectConversation(conv.conversation_id)}
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
                    onBlur={onSaveTitle}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') onSaveTitle();
                      if (e.key === 'Escape') onCancelEditTitle();
                    }}
                    onClick={(e) => e.stopPropagation()}
                    autoFocus
                    className="flex-1 px-2 py-0.5 border border-blue-300 rounded text-sm focus:outline-none focus:ring-1 focus:ring-blue-500"
                  />
                ) : (
                  <span
                    className="flex-1 truncate"
                    onDoubleClick={(e) => onStartEditTitle(conv.conversation_id, conv.title, e)}
                  >
                    {conv.title}
                  </span>
                )}
                <span className="text-xs text-slate-400 shrink-0">{conv.message_count}</span>
                <button
                  onClick={(e) => onDeleteConversation(conv.conversation_id, e)}
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
              onClick={() => onPageChange(convPage - 1)}
              disabled={convPage <= 1}
              className="px-2 py-1 rounded hover:bg-slate-100 disabled:opacity-30 transition-colors"
            >
              上一页
            </button>
            <span className="text-slate-400">第 {convPage} / {totalPages} 页</span>
            <button
              onClick={() => onPageChange(convPage + 1)}
              disabled={convPage >= totalPages}
              className="px-2 py-1 rounded hover:bg-slate-100 disabled:opacity-30 transition-colors"
            >
              下一页
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
