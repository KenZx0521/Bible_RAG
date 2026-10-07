"""KG stages (design §5): K0 names, K1 events, K4 routing contract.

These modules read stored layers and the registries in ``config/registries/``
only; they never import a database driver or ``scripts.*`` (G-IMPORT) and never
write ``config/``. The tools that do write registries (``convert events``,
``freeze route``) run outside the build DAG and are named as such.
"""
