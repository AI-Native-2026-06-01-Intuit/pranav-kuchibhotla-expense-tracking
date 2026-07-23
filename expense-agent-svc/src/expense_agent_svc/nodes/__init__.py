"""LangGraph node implementations for the three-agent supervisor.

Each node is an ``async def`` returning a partial ``AgentState`` mapping.
The deadline decorator (:mod:`expense_agent_svc.nodes._deadline`) is
applied as the *outer* wrapper on every node, so a slow node still
returns a sentinel partial update within its allotted budget.
"""
