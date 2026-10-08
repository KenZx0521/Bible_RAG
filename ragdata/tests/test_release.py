"""S12: ``release.assemble`` pins the layer versions, their dependency closure and the contract
files, and names the release ``b{date}_{sha8}`` without reading the clock."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace

import pytest
import yaml

import mini_release
from ragcommon import ids
from ragdata.release import assemble as rel
from ragdata.release import gating
from ragdata.release.contracts import CONTRACT_FILES
from ragdata.store import DEPENDS_ON, encode_jsonl, read_layer, write_layer

DATE = "20261008"


@pytest.fixture(scope="module")
def mini(tmp_path_factory):
    return mini_release.build(tmp_path_factory.mktemp("release"))


@pytest.fixture(scope="module")
def release(mini):
    return rel.assemble(mini.store, mini.top, DATE, mini.checks)


def test_the_release_names_every_layer_and_derives_the_rest_from_depends_on(mini, release):
    doc = release.doc
    assert {k: v for k, v in doc["layers"].items() if v} == {
        name: layer.version for name, layer in mini.layers.items()}
    assert doc["layers"]["src"] is None and doc["layers"]["identity"] is None
    assert doc["depends_on"]["emb"] == {"struct": mini.layers["struct"].version,
                                        "text": mini.layers["text"].version}
    assert doc["kg_enabled"] is False and doc["template_id"] == "v1c"
    assert set(doc["contracts"]) == set(CONTRACT_FILES)
    assert doc["counts"]["embedding_records"] == 22 and doc["counts"]["verse_units"] == 14


def test_build_id_is_the_date_and_the_release_sha(release):
    assert release.build_id == ids.build_id(DATE, release.release_sha)
    assert release.doc["build_id"] == release.build_id
    body = {k: v for k, v in release.doc.items() if k not in rel.NAMING}
    assert rel.sha256_bytes(rel.encode(body)) == release.release_sha


def test_assembling_again_gives_the_same_bytes(mini, release):
    again = rel.assemble(mini.store, list(reversed(mini.top)), DATE, mini.checks)
    assert again.data == release.data
    later = rel.assemble(mini.store, mini.top, "20261009", mini.checks)
    assert later.release_sha == release.release_sha


def test_naming_lower_layers_too_is_the_same_release(mini, release):
    named = [layer.version for layer in mini.layers.values()]
    assert rel.assemble(mini.store, named, DATE, mini.checks).data == release.data


def test_a_layer_built_on_another_version_breaks_the_closure(mini, tmp_path):
    struct = read_layer(mini.layers["struct"].path)
    other_text = write_layer(mini.store, "text", {"books.jsonl": b"{}\n"})
    files = {n: (struct.path / n).read_bytes() for n in struct.file_shas if n != "depends_on.json"}
    other_struct = write_layer(mini.store, "struct", files,
                               depends_on={"text": other_text.version})
    versions = [*mini.top, other_struct.version]
    with pytest.raises(rel.ReleaseError, match="was built on .*but the release has text"):
        rel.assemble(mini.store, versions, DATE, mini.checks)


@pytest.mark.parametrize("versions, match", [
    (["emb@000000000000"], "no layer"),
    (["kg0@" + "0" * 12, "kg0@" + "1" * 12], "twice"),
    (["nonsense"], "not a layer version"),
])
def test_bad_layer_lists_are_refused(mini, versions, match):
    with pytest.raises(rel.ReleaseError, match=match):
        rel.assemble(mini.store, versions, DATE, mini.checks)


def test_a_release_without_every_core_layer_is_refused(mini):
    with pytest.raises(rel.ReleaseError, match="route"):
        rel.assemble(mini.store, mini.top[:3], DATE, mini.checks)


def test_a_bad_date_is_refused(mini):
    with pytest.raises(rel.ReleaseError, match="date"):
        rel.assemble(mini.store, mini.top, "2026-10-08", mini.checks)


def _red_counts(mini, tmp_path):
    """The mini expectations with one more heading than the mini text layer holds."""
    counts = yaml.safe_load(mini_release.MINI_COUNTS.read_text(encoding="utf-8"))
    counts["text"]["headings"]["value"] += 1
    path = tmp_path / "counts.yaml"
    path.write_text(yaml.safe_dump(counts, allow_unicode=True), encoding="utf-8")
    return replace(mini.checks, counts_path=path)


def test_a_text_layer_the_current_counts_turn_red_is_not_released(mini, tmp_path):
    """The text→struct chain under every layer: G-COUNT red on text refuses the release."""
    text = mini.layers["text"].version
    with pytest.raises(rel.ReleaseError, match=f"{text} G-COUNT: .*headings"):
        rel.assemble(mini.store, mini.top, DATE, _red_counts(mini, tmp_path))


def _stored_copy(mini, layer, name, mutate):
    """A copy of the mini ``layer`` in the same store, ``name``'s rows mutated."""
    built = read_layer(mini.layers[layer].path)
    rows = [json.loads(json.dumps(r)) for r in built.rows[name]]
    mutate(rows)
    files = {n: (built.path / n).read_bytes() for n in built.file_shas if n != DEPENDS_ON}
    return write_layer(mini.store, layer, {**files, name: encode_jsonl(rows)},
                       depends_on=built.depends_on)


def test_a_stored_layer_the_gates_now_turn_red_is_not_released(mini):
    """Like kg0@3151851bc84f: in the store, its closure whole, red under the current gates."""
    bad = _stored_copy(mini, "route", "routing_terms.jsonl",
                       lambda rows: rows[0].update(provenance_class=None, source=None))
    with pytest.raises(rel.ReleaseError, match=f"{bad.version} G-PROV"):
        rel.assemble(mini.store, [*mini.top[:3], bad.version], DATE, mini.checks)


def test_the_release_gates_are_the_layer_gates_but_the_model_and_backend_ones():
    assert gating.release_gates("emb") == ("G-SCHEMA", "G-COUNT", "G-EMB")
    assert gating.release_gates("route") == ("G-SCHEMA", "G-COUNT", "G-PROV")
    assert gating.release_gates("text") == ("G-SCHEMA", "G-COUNT", "G-REFINT", "G-TEXT", "G-REF")


def test_by_default_the_release_gates_read_the_repository_expectations(tmp_path):
    checks = gating.default_checks(tmp_path / "tokenizer.json")
    assert checks.counts_path == gating.PDF_COUNTS_PATH and checks.inputs.encoder is None
    assert checks.inputs.tokenizer == tmp_path / "tokenizer.json"


def test_layers_that_cannot_be_gated_are_not_released(mini, tmp_path):
    inputs = replace(mini.checks.inputs, encoder=None, tokenizer=tmp_path / "missing.json")
    with pytest.raises(rel.ReleaseError, match="cannot be gated.*tokenizer"):
        rel.assemble(mini.store, mini.top, DATE, replace(mini.checks, inputs=inputs))


def test_reading_a_release_gates_its_layers_again(mini, release, tmp_path):
    path = rel.write_release(release, tmp_path)
    with pytest.raises(rel.ReleaseError, match="G-COUNT"):
        rel.read_release(path, mini.store, _red_counts(mini, tmp_path))


def test_write_is_immutable_and_idempotent(release, tmp_path):
    path = rel.write_release(release, tmp_path)
    assert path == tmp_path / f"{release.build_id}.json" and path.read_bytes() == release.data
    assert rel.write_release(release, tmp_path) == path
    path.chmod(0o644)
    path.write_bytes(release.data.replace(b'"v1c"', b'"v1d"'))
    with pytest.raises(rel.ReleaseError, match="differs"):
        rel.write_release(release, tmp_path)


def test_read_release_verifies_the_file_against_the_store(mini, release, tmp_path):
    path = rel.write_release(release, tmp_path)
    again = rel.read_release(path, mini.store, mini.checks)
    assert again.data == release.data and set(again.layers) == set(release.layers)
    doc = json.loads(release.data)
    doc["counts"]["verse_units"] = 13
    edited = tmp_path / "edited.json"
    edited.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(rel.ReleaseError, match="does not match"):
        rel.read_release(edited, mini.store, mini.checks)


def test_read_release_refuses_a_file_that_is_not_a_release(tmp_path, mini):
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    with pytest.raises(rel.ReleaseError, match="not a release"):
        rel.read_release(bad, mini.store, mini.checks)
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(rel.ReleaseError, match="unreadable"):
        rel.read_release(bad, mini.store, mini.checks)


def test_git_date_is_the_commit_date_in_utc(tmp_path):
    def git(*args, **env):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True,
                       env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), **env})
    git("init", "-q")
    stamp = {"GIT_COMMITTER_DATE": "2026-10-07T23:30:00-02:00",
             "GIT_AUTHOR_DATE": "2026-10-07T23:30:00-02:00"}
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x",
        **stamp)
    assert rel.git_date(tmp_path) == "20261008"
    with pytest.raises(rel.ReleaseError, match="git"):
        rel.git_date(tmp_path / "nowhere")


def test_cli_writes_the_release_and_reports_its_build_id(mini, release, tmp_path, capsys,
                                                        monkeypatch):
    from ragdata import cli
    monkeypatch.setattr(gating, "default_checks", lambda tokenizer: mini.checks)
    argv = ["release", *mini.top, "--store", str(mini.store), "--releases", str(tmp_path),
            "--date", DATE]
    assert cli.main(argv) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["build_id"] == release.build_id and out["existed"] is False
    assert (tmp_path / f"{release.build_id}.json").read_bytes() == release.data
    assert cli.main(argv) == 0 and json.loads(capsys.readouterr().out)["existed"] is True
    assert cli.main(["release", "kg0@" + "0" * 12, "--store", str(mini.store)]) == 2
    assert "no layer" in capsys.readouterr().err


def test_cli_dates_the_release_by_the_commit_without_date(mini, tmp_path, capsys, monkeypatch):
    from ragdata import cli
    monkeypatch.setattr(rel, "git_date", lambda repo: "20250101")
    monkeypatch.setattr(gating, "default_checks", lambda tokenizer: mini.checks)
    assert cli.main(["release", *mini.top, "--store", str(mini.store),
                     "--releases", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["build_id"].startswith("b20250101_")


def test_cli_refuses_layers_the_gates_turn_red(mini, tmp_path, capsys, monkeypatch):
    from ragdata import cli
    monkeypatch.setattr(gating, "default_checks", lambda tokenizer: _red_counts(mini, tmp_path))
    assert cli.main(["release", *mini.top, "--store", str(mini.store), "--releases",
                     str(tmp_path), "--date", DATE]) == 2
    assert "G-COUNT" in capsys.readouterr().err and not list(tmp_path.glob("b*.json"))
