"""Offline golden-fixture checks for the additive B1 analysis contract."""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.analysis_evidence_v1 import AnalysisEvidenceV1


CONTRACTS = Path(__file__).resolve().parents[2] / "docs" / "contracts"


def fixture(name: str) -> dict:
    return json.loads((CONTRACTS / f"analysis-evidence-v1.{name}.json").read_text())


def test_complete_fixture_keeps_global_time_and_cross_window_asr():
    result = AnalysisEvidenceV1.model_validate(fixture("valid"))

    assert result.executionStatus == "SUCCESS"
    assert result.reviewStatus == "READY"
    assert result.windows[0].endMs == result.windows[1].startMs
    assert [a.transcriptRefs for a in result.windowAnalyses] == [["asr_001"], ["asr_001"]]
    assert result.transcripts[0].startMs == 55000


def test_partial_fixture_preserves_success_and_requires_review():
    result = AnalysisEvidenceV1.model_validate(fixture("needs-review"))

    assert result.analysisOutcome == "PARTIAL"
    assert result.reviewStatus == "NEEDS_REVIEW"
    assert result.coverage.failedWindowIds == ["window_002"]
    assert result.frameObservations[0].frameId == "frame_w001_001"
    assert result.windowAnalyses[1].transcriptRefs == ["asr_001"]


def test_no_speech_fixture_is_complete_without_invented_transcript():
    result = AnalysisEvidenceV1.model_validate(fixture("no-speech"))

    assert result.analysisOutcome == "COMPLETE"
    assert result.reviewStatus == "READY"
    assert result.provenance["asr"].mode == "NO_SPEECH"
    assert result.transcripts == []
    assert all(a.coverage.audioComplete and a.coverage.asrOverlapMs == 0 for a in result.windowAnalyses)


def test_mixed_fixture_requires_review_despite_full_time_coverage():
    result = AnalysisEvidenceV1.model_validate(fixture("mixed"))

    assert result.analysisOutcome == "COMPLETE"
    assert result.reviewStatus == "NEEDS_REVIEW"
    assert result.coverage.completeWindows == 2
    assert result.provenance["vlm"].mode == "MIXED"


def test_complete_audio_without_transcript_must_record_no_speech():
    data = fixture("no-speech")
    data["windowAnalyses"][0]["provenance"]["asr"]["mode"] = "REAL"

    with pytest.raises(ValidationError):
        AnalysisEvidenceV1.model_validate(data)


def test_model_supplied_free_time_is_rejected():
    with pytest.raises(ValidationError) as exc:
        AnalysisEvidenceV1.model_validate(fixture("invalid-extra-time"))
    assert any(error["type"] == "extra_forbidden" for error in exc.value.errors())


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["frameObservations"][0].update(timestampMs=130000),
        lambda d: d["frameObservations"][0].update(timestampMs=20000.5),
        lambda d: d["profile"].update(effectiveType="VLOG_DOCUMENTARY"),
        lambda d: d["profile"].update(configVersion="2.0"),
        lambda d: d["windows"][1].update(startMs=61000),
        lambda d: d["windowAnalyses"][0].update(frameObservationRefs=["frame_w002_001"]),
        lambda d: d["windowAnalyses"][0]["coverage"].update(asrOverlapMs=15000),
        lambda d: d["frameObservations"][1].update(frameId="frame_w001_001"),
    ],
)
def test_invalid_time_identity_and_coverage_are_rejected(change):
    data = copy.deepcopy(fixture("valid"))
    change(data)
    with pytest.raises(ValidationError):
        AnalysisEvidenceV1.model_validate(data)


def test_partial_evidence_cannot_be_ready():
    data = fixture("needs-review")
    data["reviewStatus"] = "READY"
    with pytest.raises(ValidationError):
        AnalysisEvidenceV1.model_validate(data)


def test_mixed_evidence_cannot_be_ready():
    data = fixture("mixed")
    data["reviewStatus"] = "READY"
    with pytest.raises(ValidationError):
        AnalysisEvidenceV1.model_validate(data)


def test_schema_file_matches_python_model():
    actual = json.loads((CONTRACTS / "analysis-evidence-v1.schema.json").read_text())
    expected = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:agentcut:analysis-evidence:v1",
        **AnalysisEvidenceV1.model_json_schema(),
    }
    assert actual == expected
