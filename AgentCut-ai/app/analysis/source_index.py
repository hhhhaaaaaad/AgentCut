"""Complete source intervals, independent of frame selection and model budgets."""

import hashlib
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.script_contracts_v1 import (
    MAX_SAFE_INTEGER, AssetRef, Contract, Hash, Integer, Provenance, Range, Scene,
    Text,
)


def planning_hash(value: dict) -> str:
    """Python-local planning identity, separate from the frozen B1 hash payloads."""
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def stable_id(prefix: str, value: dict) -> str:
    return prefix + "_" + planning_hash(value).removeprefix("sha256:")


def seconds_to_ms(seconds) -> int:
    """The explicit legacy-seconds adapter: nearest ms, .5 rounds upward.

    Adjacent detector endpoints use the same conversion. A sub-ms scene that
    collapses after conversion is rejected by the index builder, never dropped.
    """
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float, Decimal)):
        raise ValueError("seconds must be a finite nonnegative number")
    try:
        value = Decimal(str(seconds))
        if not value.is_finite() or value < 0 or value * 1000 > MAX_SAFE_INTEGER:
            raise ValueError("seconds outside the safe millisecond range")
        return int((value * 1000).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except InvalidOperation as exc:
        raise ValueError("invalid seconds") from exc


class DetectorIdentity(Contract):
    name: Text
    version: Text
    settingsHash: Hash


class SourceScene(Scene):
    origin: Literal["DETECTED", "NO_CUT", "UNOBSERVED"]
    source: Provenance


def _scene_id(asset: AssetRef, detector: DetectorIdentity, scene: SourceScene | dict) -> str:
    data = scene.model_dump() if isinstance(scene, SourceScene) else scene
    return stable_id("scene", {
        "assetId": asset.assetId, "assetHash": asset.assetHash,
        "durationMs": asset.durationMs, "detector": detector.model_dump(),
        "sourceRange": data["sourceRange"], "origin": data["origin"],
        "mode": data["source"]["mode"],
    })


class SourceIndex(Contract):
    indexSchemaVersion: Literal["source-index-0.1"] = "source-index-0.1"
    indexId: Text
    assetRef: AssetRef
    detector: DetectorIdentity
    detectorSource: Provenance
    scenes: list[SourceScene] = Field(min_length=1)
    indexedCoverageMs: Integer
    observedCoverageMs: Integer
    detectionStatus: Literal["COMPLETE", "PARTIAL", "SIMULATED", "UNAVAILABLE"]

    def contract_scenes(self) -> list[Scene]:
        """Explicit projection into the frozen B1 source-scene contract."""
        return [Scene(sceneId=s.sceneId, sourceRange=s.sourceRange.model_copy()) for s in self.scenes]

    @model_validator(mode="after")
    def validate_index(self) -> "SourceIndex":
        cursor = 0
        ids = set()
        if self.detectorSource.mode not in {"REAL", "SIMULATED", "UNAVAILABLE"}:
            raise ValueError("detector source must be REAL, SIMULATED or UNAVAILABLE")
        for scene in self.scenes:
            r = scene.sourceRange
            if r.startMs != cursor or not r.startMs < r.endMs <= self.assetRef.durationMs:
                raise ValueError("source scenes must partition [0, durationMs) without gaps or overlaps")
            cursor = r.endMs
            if scene.sceneId in ids or scene.sceneId != _scene_id(self.assetRef, self.detector, scene):
                raise ValueError("invalid or duplicate stable sceneId")
            ids.add(scene.sceneId)
            if scene.origin == "UNOBSERVED":
                if scene.source.mode != "UNAVAILABLE":
                    raise ValueError("unobserved intervals must have UNAVAILABLE provenance")
            elif scene.source != self.detectorSource or scene.source.mode not in {"REAL", "SIMULATED"}:
                raise ValueError("detected intervals must retain detector provenance")
            if scene.origin == "NO_CUT" and len(self.scenes) != 1:
                raise ValueError("NO_CUT must cover the entire source")
        if cursor != self.assetRef.durationMs or self.indexedCoverageMs != cursor:
            raise ValueError("source index must cover the entire asset")
        observed = sum(s.sourceRange.endMs - s.sourceRange.startMs
                       for s in self.scenes if s.source.mode == "REAL")
        if self.observedCoverageMs != observed or self.detectionStatus != _status(self.scenes, cursor):
            raise ValueError("detection coverage/status mismatch")
        if self.indexId != _index_id(self.assetRef, self.detector, self.scenes):
            raise ValueError("source index identity mismatch")
        return self


def _status(scenes: list[SourceScene], duration: int) -> str:
    real = sum(s.sourceRange.endMs - s.sourceRange.startMs for s in scenes if s.source.mode == "REAL")
    if real == duration:
        return "COMPLETE"
    if real:
        return "PARTIAL"
    return "SIMULATED" if any(s.source.mode == "SIMULATED" for s in scenes) else "UNAVAILABLE"


def _index_id(asset: AssetRef, detector: DetectorIdentity, scenes: list[SourceScene]) -> str:
    return stable_id("source", {
        "schema": "source-index-0.1", "assetId": asset.assetId,
        "assetHash": asset.assetHash, "durationMs": asset.durationMs,
        "detector": detector.model_dump(), "sceneIds": [s.sceneId for s in scenes],
    })


def build_source_index(
    asset: AssetRef, ranges: list[Range], detector: DetectorIdentity,
    source: Provenance, *, no_cuts: bool = False,
) -> SourceIndex:
    """Preserve every supplied range. Fill detection gaps as UNOBSERVED.

    Ordered non-overlapping ranges are required; malformed detector output is
    rejected. An empty result is unknown unless successful no-cut detection is
    explicitly declared. No frame budget participates in source identity.
    """
    asset = AssetRef.model_validate(asset.model_dump())
    detector = DetectorIdentity.model_validate(detector.model_dump())
    source = Provenance.model_validate(source.model_dump())
    if source.mode not in {"REAL", "SIMULATED", "UNAVAILABLE"}:
        raise ValueError("unsupported detector provenance")
    if source.mode == "UNAVAILABLE" and (ranges or no_cuts):
        raise ValueError("unavailable detector cannot supply detected scenes")
    if type(no_cuts) is not bool or (no_cuts and ranges):
        raise ValueError("no_cuts requires an empty successful detector result")
    if no_cuts:
        ranges = [Range(startMs=0, endMs=asset.durationMs)]
    unknown = Provenance(mode="UNAVAILABLE", provider=detector.name, model=None,
                         reason="No detector observation for this source interval")
    scenes = []

    def append(start: int, end: int, origin: str, provenance: Provenance):
        data = {"sourceRange": {"startMs": start, "endMs": end},
                "origin": origin, "source": provenance.model_dump()}
        scenes.append(SourceScene(sceneId=_scene_id(asset, detector, data), **data))

    cursor = 0
    for candidate in ranges:
        r = Range.model_validate(candidate.model_dump())
        if not cursor <= r.startMs < r.endMs <= asset.durationMs:
            raise ValueError("detected ranges must be ordered, non-overlapping and within the asset")
        if cursor < r.startMs:
            append(cursor, r.startMs, "UNOBSERVED", unknown)
        append(r.startMs, r.endMs, "NO_CUT" if no_cuts else "DETECTED", source)
        cursor = r.endMs
    if cursor < asset.durationMs:
        append(cursor, asset.durationMs, "UNOBSERVED", unknown)
    return SourceIndex(
        indexId=_index_id(asset, detector, scenes), assetRef=asset, detector=detector,
        detectorSource=source, scenes=scenes, indexedCoverageMs=asset.durationMs,
        observedCoverageMs=sum(s.sourceRange.endMs - s.sourceRange.startMs
                               for s in scenes if s.source.mode == "REAL"),
        detectionStatus=_status(scenes, asset.durationMs),
    )
