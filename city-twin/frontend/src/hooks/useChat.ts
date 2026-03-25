import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE } from "./useGridStream";
import type { ChatThread, ChatMessage } from "../types/grid";

export function useChat() {
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const initRef = useRef(false);

  const fetchThreads = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/chat/threads`);
      const data: ChatThread[] = await r.json();
      setThreads(data);
      return data;
    } catch {
      return [];
    }
  }, []);

  const fetchMessages = useCallback(async (threadId: string) => {
    try {
      const r = await fetch(`${API_BASE}/chat/threads/${threadId}/messages`);
      const data = await r.json();
      if (Array.isArray(data)) {
        const msgs = data.map((m: ChatMessage) => ({
          ...m,
          timestamp: m.timestamp ?? new Date().toISOString(),
        }));
        setMessages(msgs);
      }
    } catch {
      /* ignore */
    }
  }, []);

  const createThread = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/chat/threads`, { method: "POST" });
      const data = await r.json();
      const threadId = data.id as string;
      await fetchThreads();
      setActiveThreadId(threadId);
      setMessages([]);
      return threadId;
    } catch {
      return null;
    }
  }, [fetchThreads]);

  const selectThread = useCallback(
    async (threadId: string) => {
      setActiveThreadId(threadId);
      await fetchMessages(threadId);
    },
    [fetchMessages],
  );

  const deleteThread = useCallback(
    async (threadId: string) => {
      try {
        await fetch(`${API_BASE}/chat/threads/${threadId}`, {
          method: "DELETE",
        });
        const remaining = await fetchThreads();
        if (threadId === activeThreadId) {
          if (remaining.length > 0) {
            await selectThread(remaining[0].id);
          } else {
            setActiveThreadId(null);
            setMessages([]);
          }
        }
      } catch {
        /* ignore */
      }
    },
    [activeThreadId, fetchThreads, selectThread],
  );

  const sendMessage = useCallback(
    async (content: string) => {
      let tid = activeThreadId;
      if (!tid) {
        tid = await createThread();
        if (!tid) return;
      }

      const userMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "user",
        content,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setLoading(true);

      try {
        const r = await fetch(`${API_BASE}/chat/threads/${tid}/messages`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content }),
        });
        const data = await r.json();
        if (data.error || !data.content) {
          throw new Error(data.error ?? "Empty response");
        }
        const assistantMsg: ChatMessage = {
          ...data,
          timestamp: data.timestamp ?? new Date().toISOString(),
        };
        setMessages((prev) => [...prev, assistantMsg]);
        fetchThreads();
      } catch {
        setMessages((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            role: "assistant",
            content: "Sorry, something went wrong. Please try again.",
            timestamp: new Date().toISOString(),
          },
        ]);
      } finally {
        setLoading(false);
      }
    },
    [activeThreadId, createThread, fetchThreads],
  );

  useEffect(() => {
    if (initRef.current) return;
    initRef.current = true;
    (async () => {
      const list = await fetchThreads();
      if (list.length > 0) {
        setActiveThreadId(list[0].id);
        await fetchMessages(list[0].id);
      }
    })();
  }, [fetchThreads, fetchMessages]);

  return {
    threads,
    activeThreadId,
    messages,
    loading,
    createThread,
    selectThread,
    deleteThread,
    sendMessage,
  };
}
