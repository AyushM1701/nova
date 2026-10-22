"""Speaker labels for a recording: who spoke when (pyannote segmentation + CAM++ voice embeddings, run by
sherpa-onnx on this computer). Models download on first use (about 35 MB, core/models.py).

When the meeting also recorded the computer's audio, the speaker heard mostly while the computer was quiet is the
user at the microphone, so they're labelled "You"; everyone else is "Speaker 1", "Speaker 2", ...
"""
import numpy as np

from core import models

QUIET = 0.004  # the computer's audio below this RMS: nobody on the call is talking
WINDOW_S = 0.5  # the recorder measures loudness in windows this long


def available():
    return models.installed("segmentation") and models.installed("embedding")


def turns(audio, speakers=-1):
    """[(start_s, end_s, speaker_index)] for 16 kHz mono audio. speakers=-1: work out how many."""
    import sherpa_onnx
    seg = models.path("segmentation")
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(seg / "model.onnx"))),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(models.path("embedding"))),
        clustering=sherpa_onnx.FastClusteringConfig(num_clusters=speakers, threshold=0.6),
        min_duration_on=0.3, min_duration_off=0.5)
    sd = sherpa_onnx.OfflineSpeakerDiarization(config)
    return [(r.start, r.end, r.speaker) for r in sd.process(np.ascontiguousarray(audio, dtype=np.float32))
            .sort_by_start_time()]


def label(segments, turns, loudness=None):
    """Give each transcript segment {start, end, text} a "speaker": the diarized speaker it overlaps most.
    `loudness` is [(mic_rms, computer_rms)] per WINDOW_S, when the computer's audio was recorded too."""
    def overlap(s, e, ts, te):
        return max(0.0, min(e, te) - max(s, ts))

    names, you = {}, None
    if loudness and turns:  # the speaker whose time is mostly computer-quiet is the user
        quiet, total = {}, {}
        for ts, te, who in turns:
            for w in range(int(ts / WINDOW_S), min(len(loudness), int(te / WINDOW_S) + 1)):
                total[who] = total.get(who, 0) + 1
                quiet[who] = quiet.get(who, 0) + (loudness[w][1] < QUIET)
        ranked = sorted(total, key=lambda w: quiet[w] / total[w], reverse=True)
        if ranked and quiet[ranked[0]] / total[ranked[0]] > 0.7:
            you = ranked[0]
    for seg in segments:
        scores = {}
        for ts, te, who in turns:
            scores[who] = scores.get(who, 0) + overlap(seg["start"], seg["end"], ts, te)
        who = max(scores, key=scores.get) if scores and max(scores.values()) > 0 else None
        if who is None:
            seg["speaker"] = ""
        elif who == you:
            seg["speaker"] = "You"
        else:
            names.setdefault(who, f"Speaker {len(names) + 1}")
            seg["speaker"] = names[who]
    return segments
