import { ChevronUpIcon, ChevronDownIcon } from '@heroicons/react/24/outline';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import type { ChatMessage, RAGSource } from '../types';

interface MessageListProps {
  messages: ChatMessage[];
  streamingContent: string;
  streamingSources: RAGSource[];
  error: string | null;
  expandedSources: Record<number, boolean>;
  activeConvId: number | null;
  onToggleSource: (idx: number) => void;
  onRetry: () => void;
}

export default function MessageList({
  messages,
  streamingContent,
  streamingSources,
  error,
  expandedSources,
  activeConvId,
  onToggleSource,
  onRetry,
}: MessageListProps) {
  return (
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
              onClick={onRetry}
              className="shrink-0 px-3 py-1 bg-red-600 text-white text-xs rounded-lg hover:bg-red-700 transition-colors"
            >
              重试
            </button>
          </div>
        </div>
      )}

      {messages.map((msg, i) => (
        <div key={i}>
          <div className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
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
          {msg.role === 'assistant' && msg.sources && msg.sources.length > 0 && (
            <SourcePanel
              sources={msg.sources}
              baseIdx={i * 1000}
              expandedSources={expandedSources}
              onToggleSource={onToggleSource}
            />
          )}
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

      {streamingContent && streamingSources.length > 0 && (
        <SourcePanel
          sources={streamingSources}
          baseIdx={0}
          expandedSources={expandedSources}
          onToggleSource={onToggleSource}
        />
      )}
    </div>
  );
}

function SourcePanel({
  sources,
  baseIdx,
  expandedSources,
  onToggleSource,
}: {
  sources: RAGSource[];
  baseIdx: number;
  expandedSources: Record<number, boolean>;
  onToggleSource: (idx: number) => void;
}) {
  return (
    <div className="flex justify-start mt-2">
      <div className="max-w-[70%] bg-white border border-slate-200 rounded-xl p-4 text-sm shadow-sm">
        <p className="text-xs font-medium text-slate-500 mb-2">参考来源</p>
        {sources.map((src, i) => {
          const idx = baseIdx + i;
          return (
            <div key={i} className="mb-1.5 last:mb-0">
              <button
                onClick={() => onToggleSource(idx)}
                className="flex items-center gap-1 text-blue-600 hover:text-blue-800 text-xs transition-colors"
              >
                {expandedSources[idx] ? <ChevronUpIcon className="w-3 h-3" /> : <ChevronDownIcon className="w-3 h-3" />}
                [{i + 1}] {src.document_name} · 第{src.page_number}页 · {src.chunk_content?.slice(0, 50)}{src.chunk_content?.length > 50 ? '...' : ''}
              </button>
              {expandedSources[idx] && (
                <p className="mt-1.5 text-xs text-slate-600 bg-slate-50 rounded-lg p-3 border border-slate-100 whitespace-pre-wrap leading-relaxed">
                  {src.chunk_content}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
