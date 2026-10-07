"""Tools that read the legacy system itself (outside the build DAG, design §2.0 principle 2).

They run in the legacy system's own environment (the backend venv) and talk to the
build only through files; no stage or KG module imports them.
"""
