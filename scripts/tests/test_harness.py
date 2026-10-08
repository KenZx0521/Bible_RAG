"""The suite's own harness (run.sh, conftest.py)."""

import os


def test_scripts_are_importable():
    import derive_ragcommon_data  # noqa: F401  (top-level script import, cwd-independent)


def test_suite_never_contacts_the_hf_hub():
    # The scripts venv carries transformers; a hub request or a cold-cache
    # download over the ~50 KB/s link must never come from a test run.
    # run.sh exports both switches; run the suite through it.
    assert os.environ.get("HF_HUB_OFFLINE") == "1"
    assert os.environ.get("TRANSFORMERS_OFFLINE") == "1"
