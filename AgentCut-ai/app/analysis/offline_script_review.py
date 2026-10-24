"""Save/replay semantic QA artifacts. CLI replays SIMULATED replies only."""

import argparse
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from app.agents.script_review_agent import ScriptReviewAgent, ScriptReviewPolicy, ScriptReviewRun, review_rank
from app.analysis.offline_id_director import OfflineDirectorArtifact
from app.analysis.script_review import publish_review, review_candidate
from app.schemas.script_contracts_v1 import Contract, Provenance, ScriptContractBundleV1, require


class ScriptReviewArtifact(Contract):
    artifactVersion: Literal["offline-script-review-0.1"] = "offline-script-review-0.1"
    initialArtifact: OfflineDirectorArtifact
    review: ScriptReviewRun

    def contract_bundle(self):
        decision = (self.review.rounds[self.review.selectedRound - 1].decision
                    if self.review.selectedRound is not None else None)
        return ScriptContractBundleV1(materialIndex=self.initialArtifact.materialBuild.materialIndex,
            decision=decision, script=self.review.script, submission=self.initialArtifact.submission, events=[])

    @model_validator(mode="after")
    def replay(self):
        run, initial = self.review, self.initialArtifact
        if initial.run.script is None:
            require(run.status == "NO_CANDIDATE" and run.script is None and run.selectedRound is None
                    and not run.rounds and not run.revisions, "no candidate cannot acquire a reviewed script")
            return self
        require(1 <= len(run.rounds) <= run.policy.maxRounds and len(run.revisions) < run.policy.maxRounds,
                "review/revision budget exceeded")
        require([r.number for r in run.rounds] == list(range(1, len(run.rounds) + 1)), "review rounds out of order")
        require([a.number for a in run.revisions] == list(range(1, len(run.revisions) + 1)), "revision attempts out of order")
        require(all(1 <= a.afterRound <= len(run.rounds) for a in run.revisions), "revision refers to unknown round")
        require([a.afterRound for a in run.revisions if a.outcome == "VALIDATED"] == list(range(1, len(run.rounds))),
                "revision history does not connect reviewed candidates")
        first = run.rounds[0]
        require(first.decision == initial.run.decision and first.selectionMode == initial.run.selectedMode
                and first.selectionSource == initial.run.modelSource, "initial selection changed")
        index, submission = initial.materialBuild.materialIndex, initial.submission
        replayed = []
        for round_ in run.rounds:
            if round_.number > 1:
                require(round_.selectionMode == "MODEL_SELECTION" and round_.selectionSource == run.reviserSource,
                        "revision attribution changed")
            expected = review_candidate(index, round_.decision, submission, mode=round_.selectionMode,
                source=round_.selectionSource, revision=round_.number)
            require(round_.candidate == expected, "reviewed candidate differs from deterministic compiler")
            if round_.assessment is None:
                require(round_.publication is None and round_.outcome != "REVIEWED", "unavailable QA acquired a grade")
                published = expected
            else:
                require(round_.outcome == "REVIEWED" and run.reviewerSource is not None, "assessment source/outcome missing")
                published, binding = publish_review(expected, round_.assessment, index, round_.decision,
                    reviewer_source=run.reviewerSource, threshold=run.policy.qualityThreshold,
                    selection_mode=round_.selectionMode, selection_source=round_.selectionSource)
                require(round_.publication == binding, "review publication binding mismatch")
            replayed.append(published)
        selected = max(range(len(run.rounds)), key=lambda i: review_rank(run.rounds[i].assessment, run.policy.qualityThreshold))
        require(run.selectedRound == selected + 1 and run.script == replayed[selected]
                and run.status == run.script.reviewStatus, "selected review/candidate mismatch")
        self.contract_bundle()
        return self


def review_offline(initial, agent=None):
    initial = OfflineDirectorArtifact.model_validate(initial.model_dump())
    return ScriptReviewArtifact(initialArtifact=initial, review=(agent or ScriptReviewAgent()).run(initial))


class RecordedReplies(Contract):
    source: Provenance
    responses: list[dict] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def simulated_only(self):
        require(self.source.mode == "SIMULATED", "CLI replay must be explicitly SIMULATED")
        return self


class ReviewReplay(Contract):
    reviewer: RecordedReplies
    reviser: RecordedReplies | None = None
    policy: ScriptReviewPolicy = Field(default_factory=ScriptReviewPolicy)


class _ReplayAdapter:
    def __init__(self, replies):
        self.replies = list(replies)

    def invoke(self, _prompt):
        require(bool(self.replies), "recorded replies exhausted")
        return json.dumps(self.replies.pop(0), ensure_ascii=False, allow_nan=False)


def agent_from_replay(replay: ReviewReplay):
    replay = ReviewReplay.model_validate(replay.model_dump())
    return ScriptReviewAgent(_ReplayAdapter(replay.reviewer.responses), reviewer_source=replay.reviewer.source,
        reviser=_ReplayAdapter(replay.reviser.responses) if replay.reviser else None,
        reviser_source=replay.reviser.source if replay.reviser else None, policy=replay.policy)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="OfflineDirectorArtifact JSON")
    parser.add_argument("--replies", type=Path, help="Explicitly SIMULATED recorded replies, never a live model config")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bundle-output", type=Path)
    args = parser.parse_args()
    initial = OfflineDirectorArtifact.model_validate_json(args.input.read_text(encoding="utf-8"))
    agent = (agent_from_replay(ReviewReplay.model_validate_json(args.replies.read_text(encoding="utf-8")))
             if args.replies else ScriptReviewAgent())
    artifact = review_offline(initial, agent)
    encoded = artifact.model_dump_json(indent=2)
    ScriptReviewArtifact.model_validate_json(encoded)
    args.output.write_text(encoded + "\n", encoding="utf-8")
    if args.bundle_output:
        args.bundle_output.write_text(artifact.contract_bundle().model_dump_json(indent=2) + "\n", encoding="utf-8")
    run = artifact.review
    print(json.dumps({"status": run.status, "selectedRound": run.selectedRound, "rounds": len(run.rounds),
        "revisions": len(run.revisions), "stopReason": run.stopReason,
        "durationMs": run.script.estimatedDurationMs if run.script else 0,
        "scriptHash": run.script.scriptHash if run.script else None}, ensure_ascii=False))


if __name__ == "__main__":
    main()
