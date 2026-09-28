"""
MO NEXUS OMEGA — Architecture planner.

Scores a small set of real architecture candidates against the project's own
signals — module count, integration count, security level, deployment target —
and returns a recommendation with alternatives and tradeoffs. It does not
default to microservices: for the module counts MO projects actually produce,
a modular monolith almost always scores highest, and the scoring says why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .requirements import ProjectSpec

# Each candidate is scored 0-10 on five axes. Weighted sum picks the winner;
# all candidates and their scores are returned so the choice is inspectable.
_AXES = ("complexity_fit", "cost", "security", "maintainability", "time_to_ship")

_CANDIDATES: dict[str, dict[str, Any]] = {
    "modular_monolith": {
        "description": "Single deployable FastAPI service with clearly separated modules "
                       "(one router + service + models package per domain module).",
        "infrastructure": {"compute": "1 web service", "database": "PostgreSQL",
                           "cache": "Redis (sessions, rate limits)", "queue": "none"},
    },
    "microservices": {
        "description": "One deployable service per domain module, communicating over the "
                       "event fabric and internal APIs.",
        "infrastructure": {"compute": "N web services", "database": "PostgreSQL per service",
                           "cache": "Redis", "queue": "message broker"},
    },
    "serverless": {
        "description": "Function-per-endpoint deployment behind an API gateway.",
        "infrastructure": {"compute": "FaaS", "database": "managed PostgreSQL",
                           "cache": "managed Redis", "queue": "managed queue"},
    },
    "event_driven": {
        "description": "Modular monolith core with an event bus for cross-module workflows "
                       "(booking → dispatch → notification).",
        "infrastructure": {"compute": "1-2 web services + workers", "database": "PostgreSQL",
                           "cache": "Redis", "queue": "event fabric (existing)"},
    },
}


@dataclass
class ArchitectureRecommendation:
    recommended: str
    rationale: str
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    tradeoffs: list[dict[str, Any]] = field(default_factory=list)
    scores: dict[str, dict[str, float]] = field(default_factory=dict)
    infrastructure: dict[str, Any] = field(default_factory=dict)
    complexity: str = "MEDIUM"

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommended": self.recommended, "rationale": self.rationale,
            "alternatives": self.alternatives, "tradeoffs": self.tradeoffs,
            "scores": self.scores, "infrastructure": self.infrastructure,
            "complexity": self.complexity,
        }


class ArchitecturePlanner:
    def plan(self, spec: ProjectSpec) -> ArchitectureRecommendation:
        module_count = len(spec.modules)
        integration_count = len(spec.integrations)
        agent_count = len(spec.agents)
        workflow_count = len(spec.workflows)
        elevated_security = spec.intent.security_level in ("ELEVATED", "REGULATED")
        going_to_prod = spec.intent.deployment_target == "production"

        scores: dict[str, dict[str, float]] = {}

        for name in _CANDIDATES:
            scores[name] = self._score(
                name, module_count, integration_count, agent_count,
                workflow_count, elevated_security, going_to_prod,
            )

        ranked = sorted(scores.items(), key=lambda kv: sum(kv[1].values()), reverse=True)
        winner_name, winner_scores = ranked[0]
        winner = _CANDIDATES[winner_name]

        rationale = self._rationale(
            winner_name, module_count, integration_count, workflow_count, going_to_prod,
        )

        alternatives = [
            {
                "name": name,
                "description": _CANDIDATES[name]["description"],
                "total_score": round(sum(s.values()), 1),
                "why_not_chosen": self._why_not(winner_name, name),
            }
            for name, s in ranked[1:]
        ]

        tradeoffs = [
            {"axis": "time_to_ship",
             "note": f"{winner_name.replace('_', ' ')} ships fastest at this module count "
                     f"({module_count} modules); revisit if the project splits ownership across teams."},
            {"axis": "scale",
             "note": "If any single module's load pattern diverges sharply from the rest "
                     "(e.g. the voice pipeline needs independent scaling), extract it as a "
                     "service later rather than starting distributed."},
        ]

        complexity = "LOW" if module_count <= 4 else "MEDIUM" if module_count <= 10 else "HIGH"

        return ArchitectureRecommendation(
            recommended=winner_name, rationale=rationale, alternatives=alternatives,
            tradeoffs=tradeoffs, scores=scores, infrastructure=winner["infrastructure"],
            complexity=complexity,
        )

    def _score(
        self, name: str, modules: int, integrations: int, agents: int,
        workflows: int, elevated_security: bool, going_to_prod: bool,
    ) -> dict[str, float]:
        if name == "modular_monolith":
            return {
                "complexity_fit": 9.0 if modules <= 12 else 5.0,
                "cost": 9.0,
                "security": 7.5 if not elevated_security else 6.5,
                "maintainability": 8.0 if modules <= 15 else 5.0,
                "time_to_ship": 9.0,
            }
        if name == "microservices":
            return {
                "complexity_fit": 3.0 if modules <= 12 else 7.0,
                "cost": 3.0,
                "security": 8.0 if elevated_security else 6.0,
                "maintainability": 4.0 if modules <= 12 else 7.5,
                "time_to_ship": 2.5,
            }
        if name == "serverless":
            return {
                "complexity_fit": 5.0,
                "cost": 7.0 if not going_to_prod else 5.5,
                "security": 6.5,
                "maintainability": 5.5,
                "time_to_ship": 6.0,
            }
        if name == "event_driven":
            return {
                "complexity_fit": 8.0 if workflows >= 1 else 5.5,
                "cost": 7.5,
                "security": 7.0,
                "maintainability": 7.5,
                "time_to_ship": 7.0 if workflows >= 1 else 6.0,
            }
        return {axis: 5.0 for axis in _AXES}

    def _rationale(self, winner: str, modules: int, integrations: int, workflows: int, going_to_prod: bool) -> str:
        if winner == "modular_monolith":
            return (
                f"With {modules} modules and {integrations} external integrations, a modular "
                "monolith ships faster, costs less to run, and keeps transactions (e.g. booking "
                "→ invoice) simple, without giving up module boundaries — each module still gets "
                "its own router, service layer and data models, so extracting a service later is "
                "a refactor, not a rewrite."
            )
        if winner == "event_driven":
            return (
                f"With {workflows} cross-module workflow(s) (e.g. booking confirmation fanning out "
                "to notification and dispatch), an event-driven core on top of the monolith avoids "
                "tight coupling between those modules while still deploying as one service."
            )
        if winner == "microservices":
            return (
                f"At {modules} modules with {integrations} integrations, module boundaries are wide "
                "enough that independent deployment and scaling outweigh the operational cost."
            )
        return "Serverless fits an API-shaped workload with spiky, infrequent traffic."

    def _why_not(self, winner: str, candidate: str) -> str:
        reasons = {
            ("modular_monolith", "microservices"):
                "Splitting services now adds deployment and network overhead the module "
                "count does not yet justify.",
            ("modular_monolith", "serverless"):
                "Stateful workflows (booking, dispatch) fit a long-running service better "
                "than short-lived functions.",
            ("modular_monolith", "event_driven"):
                "Fewer cross-module workflows than would justify a dedicated event core; "
                "the existing MO Event Fabric already covers what's needed.",
            ("event_driven", "modular_monolith"):
                "A plain monolith would couple booking, dispatch and notification directly, "
                "making each harder to change independently.",
        }
        return reasons.get((winner, candidate), "Scored lower on this project's specific signals — see scores.")
