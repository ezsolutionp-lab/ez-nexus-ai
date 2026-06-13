"""EZ-NEXUS AI — Abstract BaseAgent"""

from __future__ import annotations
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional


class BaseAgent(ABC):
    """All EZ-NEXUS AI agents inherit from this class."""

    name: str = "BaseAgent"
    description: str = ""
    category: str = "general"
    status: str = "active"   # active | coming_soon | maintenance
    icon: str = "🤖"

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def run(self, task_type: str, payload: dict[str, Any], db: Any = None) -> dict[str, Any]:
        """Entry point. Records timing and delegates to handle()."""
        started_at = datetime.utcnow()
        try:
            result = await self.handle(task_type, payload, db)
            return {
                "agent": self.name,
                "task_type": task_type,
                "status": "success",
                "result": result,
                "duration_ms": int((datetime.utcnow() - started_at).total_seconds() * 1000),
            }
        except Exception as exc:
            return {
                "agent": self.name,
                "task_type": task_type,
                "status": "error",
                "error": str(exc),
                "duration_ms": int((datetime.utcnow() - started_at).total_seconds() * 1000),
            }

    @abstractmethod
    async def handle(self, task_type: str, payload: dict[str, Any], db: Any = None) -> dict[str, Any]:
        """Override in each specialized agent."""
        ...

    def to_dict(self) -> dict:
        return {
            "name":        self.name,
            "description": self.description,
            "category":    self.category,
            "status":      self.status,
            "icon":        self.icon,
        }
