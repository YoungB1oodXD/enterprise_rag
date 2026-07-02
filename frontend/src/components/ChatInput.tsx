import { useRef, useEffect } from 'react';
import { PaperAirplaneIcon, StopIcon } from '@heroicons/react/24/outline';

interface ChatInputProps {
  input: string;
  loading: boolean;
  disabled: boolean;
  onInputChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => void;
  onSend: () => void;
  onStopStreaming: () => void;
  onKeyDown: (e: React.KeyboardEvent) => void;
}

export default function ChatInput({
  input,
  loading,
  disabled,
  onInputChange,
  onSend,
  onStopStreaming,
  onKeyDown,
}: ChatInputProps) {
  const textAreaRef = useRef<HTMLTextAreaElement>(null);

  // 当 activeConvId 变化（新建对话/切换对话）时自动聚焦输入框
  useEffect(() => {
    if (!disabled) {
      textAreaRef.current?.focus();
    }
  }, [disabled]);

  return (
    <div className="border-t border-slate-200 bg-white p-4 shrink-0">
      <div className="max-w-3xl mx-auto flex gap-2">
        <textarea
          ref={textAreaRef}
          value={input}
          onChange={onInputChange}
          onKeyDown={onKeyDown}
          placeholder={disabled ? '请先创建或选择一个对话' : '输入你的问题...'}
          rows={1}
          disabled={disabled}
          className="flex-1 px-4 py-2.5 border border-slate-300 rounded-lg text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:bg-slate-50 disabled:text-slate-400 overflow-hidden transition-shadow"
        />
        {loading ? (
          <button
            onClick={onStopStreaming}
            className="px-4 py-2.5 bg-red-500 text-white rounded-lg hover:bg-red-600 transition-colors"
          >
            <StopIcon className="w-5 h-5" />
          </button>
        ) : (
          <button
            onClick={onSend}
            disabled={!input.trim() || disabled}
            className="px-4 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            <PaperAirplaneIcon className="w-5 h-5" />
          </button>
        )}
      </div>
    </div>
  );
}
