"""In-memory chat store with thread and message management."""

from __future__ import annotations

import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

MAX_THREADS = 20
MAX_MESSAGES_PER_THREAD = 50


class ChatMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: Literal["user", "assistant"]
    content: str
    structured: Optional[dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ChatThread(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str = "New conversation"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    messages: list[ChatMessage] = Field(default_factory=list)


class ChatStore:
    """Thread-based in-memory chat storage."""

    def __init__(self) -> None:
        self._threads: OrderedDict[str, ChatThread] = OrderedDict()

    def create_thread(self) -> ChatThread:
        thread = ChatThread()
        if len(self._threads) >= MAX_THREADS:
            self._threads.popitem(last=False)
        self._threads[thread.id] = thread
        return thread

    def list_threads(self) -> list[dict]:
        result = []
        for t in reversed(self._threads.values()):
            result.append({
                "id": t.id,
                "title": t.title,
                "created_at": t.created_at.isoformat(),
                "message_count": len(t.messages),
            })
        return result

    def get_thread(self, thread_id: str) -> ChatThread | None:
        return self._threads.get(thread_id)

    def add_message(self, thread_id: str, message: ChatMessage) -> bool:
        thread = self._threads.get(thread_id)
        if thread is None:
            return False
        if len(thread.messages) >= MAX_MESSAGES_PER_THREAD:
            thread.messages = thread.messages[-(MAX_MESSAGES_PER_THREAD - 1):]
        thread.messages.append(message)
        if message.role == "user" and len(thread.messages) == 1:
            thread.title = message.content[:60].strip() or "New conversation"
        return True

    def delete_thread(self, thread_id: str) -> bool:
        if thread_id in self._threads:
            del self._threads[thread_id]
            return True
        return False

    def get_messages(self, thread_id: str) -> list[ChatMessage] | None:
        thread = self._threads.get(thread_id)
        if thread is None:
            return None
        return thread.messages
