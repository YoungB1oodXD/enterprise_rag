import { useState, useRef, useCallback } from 'react';
import type { ChatMessage, RAGSource } from '../types';

interface UseChatOptions {
  knowledgeId: number;
}

export function useChat({ knowledgeId }: UseChatOptions) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streamingContent, setStreamingContent] = useState('');
  const [loading, setLoading] = useState(false);
  const [sources, setSources] = useState<RAGSource[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  const sendMessage = useCallback(async (content: string) => {
    if (!content.trim() || loading) return;

    const userMessage: ChatMessage = { role: 'user', content };
    setMessages((prev) => [...prev, userMessage]);
    setStreamingContent('');
    setSources([]);
    setLoading(true);

    const history = [...messages, userMessage];
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const token = localStorage.getItem('token');
      const res = await fetch('/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ knowledge_id: knowledgeId, messages: history }),
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
              console.error('SSE error:', parsed.error);
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
        console.error('Chat error:', err);
      }
    } finally {
      setLoading(false);
      abortRef.current = null;
    }
  }, [knowledgeId, messages, loading]);

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { messages, streamingContent, sources, loading, sendMessage, stopStreaming };
}
