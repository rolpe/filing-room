"""Agent mode: the model drives retrieval through three read-only tools in a loop (see PLAN_AGENT.md).

Nothing here imports langgraph at module load; filingroom/agent/graph.py is the only file that does, and it is
imported lazily, so pipeline mode never loads the framework.
"""
