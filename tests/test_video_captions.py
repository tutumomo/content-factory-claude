"""Remotion caption frames: short aligner cues must not crash the render or flash by."""
from app import video


def cues(*rows):
    return [{"start": s, "end": e, "text": t} for s, e, t in rows]


def test_short_cue_borrows_gap_before():
    # real case: a 2-frame "DeepSearchQA" with the next cue starting right after it
    caps = video._captions(cues((156.43, 158.10, "官方說"), (159.80, 159.87, "DeepSearchQA"),
                                (159.87, 162.10, "MCP Atlas")), 30)
    assert all(c["to"] - c["from"] >= 9 for c in caps)
    assert all(b["from"] >= a["to"] for a, b in zip(caps, caps[1:]))
    assert [c["text"] for c in caps] == ["官方說", "DeepSearchQA", "MCP Atlas"]


def test_short_cue_without_room_merges():
    caps = video._captions(cues((0, 1, "測試"), (1, 1.05, "QA"), (1.05, 2, "下一句")), 30)
    assert [c["text"] for c in caps] == ["測試QA", "下一句"]
    assert caps[0]["to"] <= caps[1]["from"]


def test_latin_words_keep_space_when_merged():
    caps = video._captions(cues((0, 1, "GPT"), (1, 1.03, "5"), (1.03, 2, "上線")), 30)
    assert caps[0]["text"] == "GPT 5"


def test_overlap_removed_and_props_use_it():
    p = video.build_props([{"headline": "h"}], cues((0, 1, "a"), (0.9, 2, "b")), (1920, 1080), [2.0])
    caps = p["captions"]
    assert caps[1]["from"] >= caps[0]["to"]
