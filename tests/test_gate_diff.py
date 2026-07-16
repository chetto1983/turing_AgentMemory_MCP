from __future__ import annotations

import json
from pathlib import Path

from scripts.gate_diff import (
    corrected_checks,
    is_stub_provider,
    verify_corpus,
)

BASELINE_ROOT = Path(__file__).resolve().parents[1] / "baseline"
TURINGDB_E2E = BASELINE_ROOT / "03-turingdb" / "e2e-results.json"
ARCADEDB_E2E = BASELINE_ROOT / "04-arcadedb" / "e2e-results.json"

EXPECTED_NON_PASSING_NAMES = {
    "document_ingest_text_writes_chunks",
    "document_search_retrieves_exact_top1_with_citation_and_neighbor_context",
    "document_search_hybrid_exact_code_match_explains_lexical_score",
    "document_ingest_text_is_idempotent_for_same_payload",
    "document_reindex_text_replaces_old_chunks_and_metadata",
}


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_corrected_checks_yields_14_pass_5_non_pass_over_committed_baseline() -> None:
    raw = _load_json(TURINGDB_E2E)
    corrected = corrected_checks(raw["checks"])

    passing = [row for row in corrected if row["ok"]]
    non_passing = [row for row in corrected if not row["ok"]]

    assert len(corrected) == 19
    assert len(passing) == 14
    assert len(non_passing) == 5
    assert {row["name"] for row in non_passing} == EXPECTED_NON_PASSING_NAMES


def test_corrected_checks_forces_ok_false_when_error_key_present_regardless_of_other_fields() -> None:
    raw_checks = [
        {"name": "x", "ok": True, "detail": True, "error": {"type": "Boom", "message": "m"}},
    ]

    corrected = corrected_checks(raw_checks)

    assert corrected[0]["ok"] is False


def test_corrected_checks_detail_truthy_is_ok_true_falsy_is_ok_false() -> None:
    raw_checks = [
        {"name": "truthy-dict", "ok": False, "detail": {"a": 1}},
        {"name": "truthy-bool", "ok": False, "detail": True},
        {"name": "falsy-bool", "ok": True, "detail": False},
        {"name": "falsy-none", "ok": True, "detail": None},
    ]

    corrected = corrected_checks(raw_checks)
    by_name = {row["name"]: row["ok"] for row in corrected}

    assert by_name["truthy-dict"] is True
    assert by_name["truthy-bool"] is True
    assert by_name["falsy-bool"] is False
    assert by_name["falsy-none"] is False


def test_verify_corpus_ok_true_on_byte_identical_stand_in_files(tmp_path: Path) -> None:
    from scripts.real_document_benchmark_scoring import file_digest

    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir()
    doc_a = corpus_root / "alpha.txt"
    doc_b = corpus_root / "beta.txt"
    doc_a.write_bytes(b"alpha stand-in content")
    doc_b.write_bytes(b"beta stand-in content")

    _, sha_a = file_digest(doc_a)
    _, sha_b = file_digest(doc_b)

    manifest_path = tmp_path / "corpus-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "documents": [
                    {"filename": "alpha.txt", "bytes": doc_a.stat().st_size, "sha256": sha_a},
                    {"filename": "beta.txt", "bytes": doc_b.stat().st_size, "sha256": sha_b},
                ]
            }
        ),
        encoding="utf-8",
    )

    result = verify_corpus(corpus_root, manifest_path)

    assert result["ok"] is True
    assert result["mismatches"] == []


def test_verify_corpus_fails_closed_on_tampered_file(tmp_path: Path) -> None:
    from scripts.real_document_benchmark_scoring import file_digest

    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir()
    doc_a = corpus_root / "alpha.txt"
    doc_a.write_bytes(b"alpha stand-in content")
    _, sha_a = file_digest(doc_a)

    manifest_path = tmp_path / "corpus-manifest.json"
    manifest_path.write_text(
        json.dumps({"documents": [{"filename": "alpha.txt", "bytes": 999, "sha256": sha_a}]}),
        encoding="utf-8",
    )

    # tamper after manifest was written
    doc_a.write_bytes(b"TAMPERED content, different bytes")

    result = verify_corpus(corpus_root, manifest_path)

    assert result["ok"] is False
    assert any(m["filename"] == "alpha.txt" for m in result["mismatches"])


def test_verify_corpus_fails_closed_on_missing_file(tmp_path: Path) -> None:
    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir()

    manifest_path = tmp_path / "corpus-manifest.json"
    manifest_path.write_text(
        json.dumps({"documents": [{"filename": "ghost.txt", "bytes": 1, "sha256": "deadbeef"}]}),
        encoding="utf-8",
    )

    result = verify_corpus(corpus_root, manifest_path)

    assert result["ok"] is False
    assert any(m["filename"] == "ghost.txt" for m in result["mismatches"])


def test_is_stub_provider_true_for_arcadedb_stub_capture() -> None:
    e2e_json = _load_json(ARCADEDB_E2E)

    assert is_stub_provider(e2e_json) is True


def test_is_stub_provider_false_for_turingdb_real_sidecar_capture() -> None:
    e2e_json = _load_json(TURINGDB_E2E)

    assert is_stub_provider(e2e_json) is False
