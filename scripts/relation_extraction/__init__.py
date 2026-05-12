"""Relation extraction pipeline (grounded, schema-bounded).

Layered after entity_extraction to populate Entity-Entity edges in Neo4j.
The LLM is constrained to choose a relation from the schema yaml or NONE.
"""
