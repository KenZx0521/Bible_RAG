"""config/curated/entity_overrides.yaml is the one source of an entity's final type.

D9 keeps group:yehehua's id but types it Person. Step 10.2
(cleanup_noise_entities --actions yehehua) relabels the live stores from this
file, and the offline Step 6.05 types entities.jsonl rows through
final_type() before domain/range, so both see the graph as 10.2 leaves it.
Batch 1D extends the file and points H7's allowlist at it.
"""

import sys
from types import SimpleNamespace

import pytest

import cleanup_noise_entities
from entity_extraction import entity_overrides
from entity_extraction.entity_overrides import final_type, load_overrides

YEHEHUA = "group:yehehua"


def _write(tmp_path, text):
    path = tmp_path / "entity_overrides.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_shipped_overrides_relabel_only_yehehua_to_person():
    assert load_overrides(entity_overrides.OVERRIDES_PATH) == {YEHEHUA: {"label": "Person"}}


@pytest.mark.parametrize("body, message", [
    ("  group:yehehua: {label: Persn}\n", "Persn"),
    ("  group:yehehua: {label: Person, merge_into: person:yehehua}\n", "merge_into"),
    ("  group:yehehua: {reason: no label}\n", "label"),
    ("  group:yehehua: {label: Person}\n  group:yehehua: {label: Theme}\n", "group:yehehua"),
])
def test_loader_rejects_unknown_label_field_or_duplicate(tmp_path, body, message):
    with pytest.raises(ValueError, match=message):
        load_overrides(_write(tmp_path, "version: 1\noverrides:\n" + body))


@pytest.mark.parametrize("text, message", [
    ("version: 2\noverrides: {}\n", "version"),
    ("version: 1\noverrides: {}\nmerges: {}\n", "merges"),
    ("version: 1\noverrides: [group:yehehua]\n", "overrides"),
])
def test_loader_rejects_a_malformed_file(tmp_path, text, message):
    with pytest.raises(ValueError, match=message):
        load_overrides(_write(tmp_path, text))


def test_final_type_applies_overrides():
    overrides = {YEHEHUA: {"label": "Person"}}
    assert final_type(YEHEHUA, "Group", overrides) == "Person"
    assert final_type("group:yisilie", "Group", overrides) == "Group"
    assert final_type(YEHEHUA, "Group", {}) == "Group"


class _Recorder:
    """Neo4j driver/session, PG connection/cursor and Qdrant client in one.

    group:yehehua starts with `labels` (typed Group unless a test says otherwise);
    every statement and payload is recorded.
    """

    def __init__(self):
        self.cypher, self.sql, self.payloads = [], [], []
        self.rowcount = 1
        self.labels = ["Entity", "Group"]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def session(self):
        return self

    def cursor(self):
        return self

    def run(self, cypher, **params):
        self.cypher.append(cypher)
        return SimpleNamespace(single=lambda: {"labels": list(self.labels)})

    def execute(self, sql, params=None):
        self.sql.append(sql)

    def set_payload(self, collection_name, payload, points, wait=True):
        self.payloads.append(payload)

    def close(self):
        pass

    commit = rollback = close


@pytest.fixture
def recorder(monkeypatch):
    """Production target: the stores are fakes, connected without a preflight."""
    monkeypatch.delenv("KG_TARGET", raising=False)
    fake = _Recorder()
    monkeypatch.setattr(cleanup_noise_entities, "get_neo4j", lambda: fake)
    monkeypatch.setattr(cleanup_noise_entities, "get_postgres", lambda strict=False: fake)
    monkeypatch.setattr(cleanup_noise_entities, "get_qdrant", lambda strict=False: fake)
    monkeypatch.setattr(sys, "argv", ["cleanup_noise_entities.py", "--actions", "yehehua"])
    return fake


def test_cleanup_yehehua_takes_the_label_from_the_file(recorder, tmp_path, monkeypatch):
    path = _write(tmp_path, "version: 1\noverrides:\n  group:yehehua: {label: Theme}\n")
    monkeypatch.setattr(cleanup_noise_entities, "OVERRIDES_PATH", path)

    assert cleanup_noise_entities.main() == 0

    assert recorder.cypher[-1] == "MATCH (e:Entity {entity_id: 'group:yehehua'}) REMOVE e:Group SET e:Theme"
    assert recorder.sql == ["UPDATE entities SET type = 'Theme' WHERE entity_id = 'group:yehehua'"]
    assert recorder.payloads == [{"type": "Theme"}]


@pytest.mark.parametrize("labels, remove", [
    (["Entity", "Place"], "Place"),             # the stale type is read from the node, not assumed
    (["Entity", "Group", "Place"], "Group:Place"),
])
def test_cleanup_yehehua_removes_the_type_labels_the_node_has(recorder, tmp_path, monkeypatch,
                                                              labels, remove):
    recorder.labels = labels
    path = _write(tmp_path, "version: 1\noverrides:\n  group:yehehua: {label: Person}\n")
    monkeypatch.setattr(cleanup_noise_entities, "OVERRIDES_PATH", path)

    assert cleanup_noise_entities.main() == 0

    assert recorder.cypher[-1] == (
        f"MATCH (e:Entity {{entity_id: 'group:yehehua'}}) REMOVE e:{remove} SET e:Person")
    assert recorder.payloads == [{"type": "Person"}]


# The default actions run dan and generic-events before yehehua: the file is
# read before either of them can write.
@pytest.mark.parametrize("actions", [["--actions", "yehehua"], []], ids=["yehehua", "default"])
def test_cleanup_yehehua_rejects_an_invalid_label_before_any_write(recorder, tmp_path, monkeypatch,
                                                                   actions):
    monkeypatch.setattr(sys, "argv", ["cleanup_noise_entities.py", *actions])
    path = _write(tmp_path, "version: 1\noverrides:\n  group:yehehua: {label: \"Person SET e.x = 1\"}\n")
    monkeypatch.setattr(cleanup_noise_entities, "OVERRIDES_PATH", path)

    with pytest.raises(SystemExit, match="Person SET e.x = 1"):
        cleanup_noise_entities.main()
    # The action guards its own interpolation too.
    with pytest.raises(ValueError, match="Person SET e.x = 1"):
        cleanup_noise_entities.action_yehehua(recorder, False, "Person SET e.x = 1")

    assert (recorder.cypher, recorder.sql, recorder.payloads) == ([], [], [])


def test_cleanup_yehehua_stops_on_a_missing_overrides_file_before_any_write(recorder, tmp_path,
                                                                           monkeypatch):
    # The script's usual '  ✗ ...' exit, not a FileNotFoundError traceback.
    absent = tmp_path / "absent.yaml"
    monkeypatch.setattr(cleanup_noise_entities, "OVERRIDES_PATH", absent)

    with pytest.raises(SystemExit) as exc:
        cleanup_noise_entities.main()

    assert str(exc.value.code).startswith("  ✗") and str(absent) in str(exc.value.code)
    assert (recorder.cypher, recorder.sql, recorder.payloads) == ([], [], [])


def test_cleanup_yehehua_without_an_override_writes_nothing(recorder, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cleanup_noise_entities, "OVERRIDES_PATH",
                        _write(tmp_path, "version: 1\noverrides: {}\n"))

    assert cleanup_noise_entities.main() == 0

    assert "no override" in capsys.readouterr().out
    assert (recorder.cypher, recorder.sql, recorder.payloads) == ([], [], [])
