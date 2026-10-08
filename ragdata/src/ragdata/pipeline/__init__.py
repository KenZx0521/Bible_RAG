"""``ragdata pipeline run``: every layer from the PDFs, the release, load and verify.

``steps`` builds and gates one layer; ``derived`` checks the committed files made from
the text and struct layers; ``run`` puts them in order and stops at the first red gate;
``cli`` wires the repository's inputs.
"""
