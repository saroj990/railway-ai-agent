from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Session:
    id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    last_train_number: str | None = None
    pending: dict[str, Any] | None = None
    updated_at: float = field(default_factory=time.time)


class SessionStore:
    """Small in-memory session store. Restarting the server clears conversations."""

    def __init__(self, max_sessions: int = 500, history_limit: int = 24) -> None:
        self.max_sessions = max_sessions
        self.history_limit = history_limit
        self._sessions: OrderedDict[str, Session] = OrderedDict()

    def get(self, session_id: str | None) -> Session:
        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            self._sessions.move_to_end(session_id)
            session.updated_at = time.time()
            return session

        new_id = session_id or f"s_{uuid.uuid4().hex[:16]}"
        session = Session(id=new_id)
        self._sessions[new_id] = session
        self._evict()
        return session

    def _evict(self) -> None:
        while len(self._sessions) > self.max_sessions:
            self._sessions.popitem(last=False)

    def trim(self, session: Session) -> None:
        if len(session.messages) <= self.history_limit:
            return
        session.messages = session.messages[-self.history_limit :]
        # Never start the history with a dangling tool result or tool-call turn.
        while session.messages and (
            session.messages[0].get("role") == "tool"
            or (
                session.messages[0].get("role") == "assistant"
                and session.messages[0].get("tool_calls")
            )
        ):
            session.messages.pop(0)
