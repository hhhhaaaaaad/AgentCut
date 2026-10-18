"""VLM 局部分批、全局索引合并和失败降级测试。"""

import json
import re
import time

import pytest

from app import config
from app.schemas.plan import TimeRange
from app.tools import vlm_understand


def _scenes(count: int) -> list[TimeRange]:
    return [
        TimeRange(start=float(index), end=float(index + 1))
        for index in range(count)
    ]


def _frames(count: int) -> list[str]:
    return [
        f"work/scene_{index:04d}_{index + 0.5:.3f}.jpg"
        for index in range(count)
    ]


def _prompt_indices(prompt: str) -> list[int]:
    return [int(value) for value in re.findall(r"sceneIndex=(\d+)", prompt)]


def _reply(indices: list[int], *, reverse: bool = False) -> str:
    ordered = list(reversed(indices)) if reverse else indices
    return json.dumps(
        {
            "batchSummary": f"batch {indices[0]}",
            "scenes": [
                {
                    "sceneIndex": index,
                    "description": f"description-{index}",
                    "tags": [f"tag-{index}"],
                    "importance": index / 100,
                }
                for index in ordered
            ],
        }
    )


@pytest.fixture(autouse=True)
def _real_vlm_config(monkeypatch):
    monkeypatch.setattr(config, "SIMULATE_FORCED", False)
    monkeypatch.setattr(config, "VLM_API_KEY", "test-key")
    monkeypatch.setattr(config, "VLM_MAX_IMAGES_PER_BATCH", 6)
    monkeypatch.setattr(config, "VLM_CONCURRENCY", 2)
    monkeypatch.setattr(config, "VLM_IMAGE_DETAIL", "low")
    monkeypatch.setattr(config, "VLM_BATCH_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(config, "VLM_BATCH_MAX_RETRIES", 1)
    monkeypatch.setattr(config, "VLM_FALLBACK_IMAGES_PER_BATCH", 3)
    monkeypatch.setattr(config, "VLM_BATCH_MAX_TOKENS", 1024)
    monkeypatch.setattr(vlm_understand, "_HAS_OPENAI", True)


def test_batches_merge_by_global_index_when_completion_is_out_of_order(monkeypatch):
    monkeypatch.setattr(config, "VLM_MAX_IMAGES_PER_BATCH", 3)
    monkeypatch.setattr(config, "VLM_CONCURRENCY", 3)
    calls: list[list[int]] = []

    def fake_understand(prompt, frame_paths, **kwargs):
        indices = _prompt_indices(prompt)
        calls.append(indices)
        time.sleep({0: 0.05, 3: 0.02, 6: 0.0}[indices[0]])
        return _reply(indices, reverse=True)

    monkeypatch.setattr(vlm_understand, "understand_frames", fake_understand)

    result = vlm_understand.understand_video(_scenes(8), _frames(8), [], {})

    assert sorted(len(call) for call in calls) == [2, 3, 3]
    assert result["sceneDescriptions"] == [
        f"description-{index}" for index in range(8)
    ]
    assert result["sceneTags"] == [[f"tag-{index}"] for index in range(8)]
    assert result["simulated"] is False
    assert result["provenance"]["mode"] == "REAL"


def test_partial_batch_failure_preserves_successful_batches(monkeypatch):
    monkeypatch.setattr(config, "VLM_MAX_IMAGES_PER_BATCH", 3)
    monkeypatch.setattr(config, "VLM_BATCH_MAX_RETRIES", 0)

    def fake_understand(prompt, frame_paths, **kwargs):
        indices = _prompt_indices(prompt)
        if indices[0] == 3:
            raise TimeoutError("forced timeout")
        return _reply(indices)

    monkeypatch.setattr(vlm_understand, "understand_frames", fake_understand)

    result = vlm_understand.understand_video(_scenes(7), _frames(7), [], {})

    assert result["sceneDescriptions"][0] == "description-0"
    assert result["sceneDescriptions"][6] == "description-6"
    assert "视觉分析缺失" in result["sceneDescriptions"][3]
    assert result["provenance"]["mode"] == "MIXED"
    assert result["provenance"]["failedSceneIndices"] == [3, 4, 5]
    assert result["provenance"]["batches"][1]["failureType"] == "TIMEOUT"


def test_timeout_batch_splits_to_three_images_and_recovers(monkeypatch):
    call_sizes: list[int] = []

    def fake_understand(prompt, frame_paths, **kwargs):
        call_sizes.append(len(frame_paths))
        if len(frame_paths) > 3:
            raise TimeoutError("forced timeout")
        return _reply(_prompt_indices(prompt))

    monkeypatch.setattr(vlm_understand, "understand_frames", fake_understand)

    result = vlm_understand.understand_video(_scenes(6), _frames(6), [], {})

    assert call_sizes == [6, 3, 3]
    assert result["simulated"] is False
    assert result["provenance"]["failedSceneIndices"] == []
    metrics = result["provenance"]["batches"]
    assert [metric["status"] for metric in metrics] == [
        "FAILED",
        "SUCCESS",
        "SUCCESS",
    ]
    assert [metric["retry"] for metric in metrics] == [False, True, True]


def test_partial_fallback_keeps_successful_child_batch(monkeypatch):
    call_sizes: list[tuple[list[int], int]] = []

    def fake_understand(prompt, frame_paths, **kwargs):
        indices = _prompt_indices(prompt)
        call_sizes.append((indices, len(frame_paths)))
        if len(frame_paths) > 3 or indices[0] == 3:
            raise TimeoutError("forced partial timeout")
        return _reply(indices)

    monkeypatch.setattr(vlm_understand, "understand_frames", fake_understand)

    result = vlm_understand.understand_video(_scenes(6), _frames(6), [], {})

    assert call_sizes == [([0, 1, 2, 3, 4, 5], 6), ([0, 1, 2], 3), ([3, 4, 5], 3)]
    assert result["sceneDescriptions"][0] == "description-0"
    assert "视觉分析缺失" in result["sceneDescriptions"][3]
    assert result["provenance"]["mode"] == "MIXED"
    assert result["provenance"]["failedSceneIndices"] == [3, 4, 5]


@pytest.mark.parametrize(
    "bad_scenes",
    [
        [
            {
                "sceneIndex": 99,
                "description": "unknown",
                "tags": [],
                "importance": 0.5,
            }
        ],
        [
            {
                "sceneIndex": 0,
                "description": "first",
                "tags": [],
                "importance": 0.5,
            },
            {
                "sceneIndex": 0,
                "description": "duplicate",
                "tags": [],
                "importance": 0.5,
            },
        ],
    ],
)
def test_unknown_or_duplicate_scene_index_is_rejected(
    monkeypatch,
    bad_scenes,
):
    monkeypatch.setattr(config, "VLM_BATCH_MAX_RETRIES", 0)
    monkeypatch.setattr(
        vlm_understand,
        "understand_frames",
        lambda *args, **kwargs: json.dumps(
            {"batchSummary": "invalid", "scenes": bad_scenes}
        ),
    )

    result = vlm_understand.understand_video(_scenes(2), _frames(2), [], {})

    assert result["provenance"]["mode"] == "MIXED"
    assert result["provenance"]["failedSceneIndices"] == [0, 1]
    assert result["provenance"]["batches"][0]["failureType"] == "INVALID_RESULT"


def test_frame_filename_keeps_original_scene_index(monkeypatch):
    frames = [
        "work/scene_0004_4.500.jpg",
        "work/scene_0001_1.500.jpg",
    ]
    seen_indices: list[int] = []

    def fake_understand(prompt, frame_paths, **kwargs):
        indices = _prompt_indices(prompt)
        seen_indices.extend(indices)
        return _reply(indices)

    monkeypatch.setattr(vlm_understand, "understand_frames", fake_understand)

    result = vlm_understand.understand_video(_scenes(5), frames, [], {})

    assert seen_indices == [1, 4]
    assert result["sceneDescriptions"][1] == "description-1"
    assert result["sceneDescriptions"][4] == "description-4"
    assert result["provenance"]["failedSceneIndices"] == [0, 2, 3]
