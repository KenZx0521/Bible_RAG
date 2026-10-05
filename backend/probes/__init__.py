"""Measurement probes, run as their own process (python -m probes.<name>).

They swap module state (the Neo4j driver, Postgres lookups) for the length of
the run, so the app must never import them. Named probes rather than tools so
they cannot be confused with scripts/tools, which the image also carries.
"""
