"""Task specs: the task-graph compiler and everything that drives it.

A spec is a SIBLING artifact to a sketch's task.json, never an extension of it.
The two describe different things and hash differently: a profile_hash groups a
sketch's historical runs in Analytics, and adding anything to task.json to make a
graph authorable would split every sketch's past runs from its future ones with
nothing able to recompute the old hashes. See docs/tasks.md §4.1.
"""
