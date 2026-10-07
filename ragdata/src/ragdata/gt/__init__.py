"""GT v2: ground_truth.json aligned to a frozen text layer (design §11.3, G-GT in §8).

``build`` derives ``ground_truth.v2.json`` and its change log from the v1 file,
the text layer and ``config/gold/gt_v2_curated.yaml``; ``gate`` runs G-GT on the
result. Question text never changes; only answer fields and the added
structured references do.
"""
