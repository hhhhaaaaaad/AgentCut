"""Replay declared VAD/ASR evidence against a visual plan, with no ASR client."""

import argparse
import json
from pathlib import Path

from app.analysis.asr_track import AsrChunkResult, AsrTrack, assemble_asr_track
from app.analysis.audio_track import AudioChunkPolicy, VadObservation, plan_audio
from app.analysis.window_planner import PlanningResult
from app.schemas.script_contracts_v1 import Contract


class OfflineAudioInput(Contract):
    vad: VadObservation
    policy: AudioChunkPolicy = AudioChunkPolicy()
    chunkResults: list[AsrChunkResult] = []


def replay_audio(visual: PlanningResult, request: OfflineAudioInput) -> AsrTrack:
    return assemble_asr_track(plan_audio(request.vad, request.policy), visual, request.chunkResults)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visual-plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--input", type=Path, help="Declared VAD and ASR fixture JSON")
    sources.add_argument("--video", type=Path, help="Local audio decoding/VAD only; no recognizer calls")
    sources.add_argument("--wav", type=Path, help="PCM WAV source asset with matching SHA-256")
    args = parser.parse_args()
    visual = PlanningResult.model_validate_json(args.visual_plan.read_text(encoding="utf-8"))
    if args.input:
        request = OfflineAudioInput.model_validate_json(args.input.read_text(encoding="utf-8"))
    else:
        from app.tools.audio_vad import detect_video_audio, detect_wav_audio

        detector = detect_video_audio if args.video else detect_wav_audio
        vad = detector(str(args.video or args.wav), visual.sourceIndex.assetRef)
        request = OfflineAudioInput(vad=vad)
    track = replay_audio(visual, request)
    serialized = track.model_dump_json(indent=2)
    AsrTrack.model_validate_json(serialized)
    args.output.write_text(serialized + "\n", encoding="utf-8")
    print(json.dumps({"status": track.status, "audioChunks": len(track.audioPlan.chunks),
        "transcripts": len(track.transcripts), "windows": len(track.windowLinks),
        "speechMs": track.audioPlan.speechMs, "transcribedSpeechMs": track.transcribedSpeechMs,
        "missingSpeechMs": track.missingSpeechMs, "output": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
