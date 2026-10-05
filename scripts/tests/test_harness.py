"""The suite's own harness (run.sh, conftest.py)."""

import os


def test_scripts_are_importable():
    import backfill_head_events  # noqa: F401  (top-level script import, cwd-independent)


def test_suite_never_contacts_the_hf_hub():
    # process_bible tests load the BGE-M3 tokenizer: online that is a hub HEAD
    # request per file, on a cold cache a ~20 MB download over a ~50 KB/s link.
    # run.sh exports both switches; run the suite through it.
    assert os.environ.get("HF_HUB_OFFLINE") == "1"
    assert os.environ.get("TRANSFORMERS_OFFLINE") == "1"
