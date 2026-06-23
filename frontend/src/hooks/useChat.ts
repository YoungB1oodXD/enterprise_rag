import { useState, useRef, useCallback } from 'react';
import type { ChatMessage, RAGSource } from '../types';

interface UseChatOptions {
  knowledgeId: number;
  conversationId?: number | null;
}

export function useChat({ knowledgeId, conversationId }: UseChatOptions) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streamingContent, setStreamingContent] = useState('');
  const [loading, setLoading] = useState(false);
  const [sources, setSources] = useState<RAGSource[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [lastFailedContent, setLastFailedContent] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // 用 ref 镜像 messages，避免闭包捕获过期值
  const messagesRef = useRef<ChatMessage[]>([]);
  messagesRef.current = messages;

  const loadConversation = useCallback((msgs: ChatMessage[]) => {
    setMessages(msgs);
    setStreamingContent('');
    setSources([]);
    setError(null);
  }, []);

  const sendMessage = useCallback(async (content: string, convId?: number | null) => {
    if (!content.trim() || loading) return;

    const userMessage: ChatMessage = { role: 'user', content };
    setMessages((prev) => [...prev, userMessage]);
    setStreamingContent('');
    setSources([]);
    setError(null);
    setLoading(true);

    const history = [...messagesRef.current, userMessage];
    const controller = new AbortController();
    abortRef.current = controller;

    const activeConvId = convId !== undefined ? convId : conversationId;

    try {
      const token = localStorage.getItem('token');
      const body: Record<string, unknown> = { knowledge_id: knowledgeId, messages: history };
      if (activeConvId) {
        body.conversation_id = activeConvId;
      }

      const res = await fetch('/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });

      const reader = res.body?.getReader();
      if (!reader) return;

      const decoder = new TextDecoder();
      let buffer = '';
      let fullContent = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const data = line.slice(6).trim();

          if (data === '[DONE]') continue;

          try {
            const parsed = JSON.parse(data);
            if (parsed.chunk) {
              fullContent += parsed.chunk;
              setStreamingContent(fullContent);
            }
            if (parsed.sources) {
              setSources(parsed.sources);
            }
            if (parsed.error) {
              setError(parsed.error);
            }
          } catch {
            // skip unparseable chunks
          }
        }
      }

      setMessages((prev) => [...prev, { role: 'assistant', content: fullContent }]);
      setStreamingContent('');
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        setError(err.message || '请求失败，请稍后重试');
        setLastFailedContent(content);
      }
    } finally {
      setLoading(false);
      abortRef.current = null;
    }
  }, [knowledgeId, conversationId, loading]);

  const retryLastMessage = useCallback(() => {
    if (!lastFailedContent) return;
    setError(null);
    setLastFailedContent(null);
    sendMessage(lastFailedContent);
  }, [lastFailedContent, sendMessage]);

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { messages, streamingContent, sources, loading, error, sendMessage, stopStreaming, loadConversation, lastFailedContent, retryLastMessage };
}
