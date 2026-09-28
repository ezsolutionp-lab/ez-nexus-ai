"""
MO NEXUS OMEGA — Project graph.

The dependency graph between pages, APIs, data models, agents, tools, workflows
and integrations. Built once per project generation and used for: code
generation order, impact analysis (what breaks if a model changes), and the
visual builder's canvas.

Cycle detection runs on every build — a self-referential dependency chain is a
FAILED build, not a silently broken one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .requirements import ProjectSpec


@dataclass
class GraphNode:
    key: str                    # e.g. "model:Booking", "api:POST /api/bookings"
    node_type: str               # page|api|model|agent|tool|workflow|integration
    label: str
    attributes: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key, "type": self.node_type, "label": self.label,
            "attributes": self.attributes, "depends_on": self.depends_on,
        }


class ProjectGraph:
    def __init__(self) -> None:
        self.nodes: dict[str, GraphNode] = {}

    def add(self, node: GraphNode) -> None:
        self.nodes[node.key] = node

    def edge(self, from_key: str, to_key: str) -> None:
        if from_key in self.nodes and to_key not in self.nodes[from_key].depends_on:
            self.nodes[from_key].depends_on.append(to_key)

    def to_dict(self) -> dict[str, Any]:
        return {"nodes": [n.to_dict() for n in self.nodes.values()]}

    def find_cycle(self) -> list[str] | None:
        """DFS cycle detection. Returns the cycle path, or None if acyclic."""
        WHITE, GREY, BLACK = 0, 1, 2
        color = {k: WHITE for k in self.nodes}
        path: list[str] = []

        def visit(key: str) -> list[str] | None:
            color[key] = GREY
            path.append(key)
            for dep in self.nodes.get(key, GraphNode(key, "", "")).depends_on:
                if dep not in self.nodes:
                    continue
                if color[dep] == GREY:
                    return path[path.index(dep):] + [dep]
                if color[dep] == WHITE:
                    found = visit(dep)
                    if found:
                        return found
            path.pop()
            color[key] = BLACK
            return None

        for key in list(self.nodes):
            if color[key] == WHITE:
                cycle = visit(key)
                if cycle:
                    return cycle
        return None

    def topological_order(self) -> list[str]:
        """Dependency-first order. Raises if the graph has a cycle."""
        cycle = self.find_cycle()
        if cycle:
            raise ValueError(f"Project graph has a cycle: {' -> '.join(cycle)}")
        visited: set[str] = set()
        order: list[str] = []

        def visit(key: str) -> None:
            if key in visited or key not in self.nodes:
                return
            visited.add(key)
            for dep in self.nodes[key].depends_on:
                visit(dep)
            order.append(key)

        for key in self.nodes:
            visit(key)
        return order

    def impacted_by(self, key: str) -> list[str]:
        """Every node that (transitively) depends on `key`. For impact analysis."""
        impacted: set[str] = set()
        changed = True
        while changed:
            changed = False
            for node in self.nodes.values():
                if node.key in impacted:
                    continue
                if any(d == key or d in impacted for d in node.depends_on):
                    impacted.add(node.key)
                    changed = True
        return sorted(impacted)


def build_graph(spec: ProjectSpec) -> ProjectGraph:
    """Compile a ProjectSpec into a ProjectGraph. Deterministic given the spec."""
    graph = ProjectGraph()

    for model in spec.models:
        graph.add(GraphNode(f"model:{model.name}", "model", model.name,
                            {"table": model.table, "field_count": len(model.fields)}))
    for model in spec.models:
        for rel in model.relations:
            target_table = rel.get("references")
            target = next((m for m in spec.models if m.table == target_table), None)
            if target:
                graph.edge(f"model:{model.name}", f"model:{target.name}")

    for page in spec.pages:
        node_key = f"page:{page.route}"
        graph.add(GraphNode(node_key, "page", page.name,
                            {"route": page.route, "requires_auth": page.requires_auth}))
        for model in spec.models:
            if model.table.rstrip("s") in page.route or model.name.lower() in page.name.lower():
                graph.edge(node_key, f"model:{model.name}")

    for model in spec.models:
        base = model.table.rstrip("s")
        for op, method in (("list", "GET"), ("create", "POST"), ("read", "GET"),
                          ("update", "PUT"), ("delete", "DELETE")):
            path = f"/api/{model.table}" if op in ("list", "create") else f"/api/{model.table}/{{id}}"
            node_key = f"api:{method} {path}:{op}"
            graph.add(GraphNode(node_key, "api", f"{op} {model.name}",
                                {"method": method, "path": path, "operation": op,
                                 "model": model.name}))
            graph.edge(node_key, f"model:{model.name}")

    for agent in spec.agents:
        node_key = f"agent:{agent.name}"
        graph.add(GraphNode(node_key, "agent", agent.name,
                            {"role": agent.role, "capability": agent.capability}))
        for tool in agent.tools:
            tool_key = f"tool:{tool}"
            graph.add(GraphNode(tool_key, "tool", tool, {}))
            graph.edge(node_key, tool_key)

    for workflow in spec.workflows:
        node_key = f"workflow:{workflow.name}"
        graph.add(GraphNode(node_key, "workflow", workflow.name,
                            {"trigger_type": workflow.trigger_type, "node_count": len(workflow.nodes)}))
        for wf_node in workflow.nodes:
            if wf_node.get("type") == "Tool" and wf_node.get("tool"):
                tool_key = f"tool:{wf_node['tool']}"
                graph.add(GraphNode(tool_key, "tool", wf_node["tool"], {}))
                graph.edge(node_key, tool_key)
            if wf_node.get("type") == "Event" and wf_node.get("topic"):
                event_key = f"event:{wf_node['topic']}"
                graph.add(GraphNode(event_key, "event", wf_node["topic"], {}))
                graph.edge(node_key, event_key)

    for integ in spec.integrations:
        graph.add(GraphNode(f"integration:{integ.provider}:{integ.capability}", "integration",
                            f"{integ.provider} {integ.capability}",
                            {"auth_kind": integ.auth_kind, "credential_env_var": integ.credential_env_var}))

    return graph
