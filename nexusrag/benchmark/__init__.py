"""NexusRAG public retrieval + generation benchmark (Plan E, Phase 4).

`scoring` holds the pure, dependency-free metric functions (safe to import
anywhere). `runner` (added with the harness) holds the orchestration that
touches the DB, retrieval, and the LLM, and is imported lazily so importing
this package stays cheap.
"""
