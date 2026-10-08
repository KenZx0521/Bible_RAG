"""KG stages (design §5): K0 names, K1 events, K4 routing contract.

These modules read stored layers, the registries in ``config/registries/`` and
the store's reference copies only; they never import a database driver or
``scripts.*`` (G-IMPORT) and never write ``config/``. The tools that do write
registries or references (``convert events``, ``freeze route``, ``freeze probe``)
run outside the build DAG and are named as such.
"""
