"""Offline smoke test: mock LLM, fake services, real ffmpeg — episode start to approved.

Run:  .venv/bin/python -m pytest tests -q
"""
from __future__ import annotations

import json

import pytest

from app import store

from .conftest import run_to_done, set_settings, wait_for

# every visual source, both engines, all three music providers
MATRIX = [
    ("slides", "ffmpeg", "audiocpp"),
    ("slides", "remotion", "openverse"),
    ("comfy", "ffmpeg", "openverse"),
    ("stock", "remotion", "audiocpp"),
    ("mix", "ffmpeg", "openverse"),
    ("mix", "remotion", "lyria"),      # also exercises the paid-music budget gate
    ("h3video", "ffmpeg", "openverse"),
    ("h3video", "remotion", "audiocpp"),
]


def _new_episode(c, topic: str = "為什麼貓咪喜歡鑽紙箱") -> str:
    r = c.post("/api/episodes", json={"topic": topic, "format": "short"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_data_is_isolated(data_dir):
    assert store.DATA == data_dir
    assert store.DATA != store.ROOT / "data"


@pytest.mark.parametrize("source,engine,provider", MATRIX, ids=[f"{s}-{e}-{m}" for s, e, m in MATRIX])
def test_episode_runs_to_approved(client, source, engine, provider):
    set_settings(client,
                 llm={"provider": "mock"},
                 visuals={"source": source},
                 render={"engine": engine, "fallback_ffmpeg": True},
                 music={"provider": provider, "enabled": True},
                 cost={"per_call_approval_usd": 0.01 if provider == "lyria" else 0.5},
                 pipeline={"review_script": True, "review_storyboard": True})
    eid = _new_episode(client)
    ep, gates = run_to_done(client, eid)

    assert ep["status"] == "done"
    assert gates == ["direction", "script", "storyboard"] + (["cost"] if provider == "lyria" else []) \
        + ["package", "approval"]

    d = store.ep_dir(eid)
    verify = json.loads((d / "output/verify.json").read_text("utf-8"))
    bad = {k: v for k, v in verify["checks"].items() if not v["ok"]}
    assert not bad, f"verify 有 ✗：{bad}"
    for key in ("播放長度", "解析度", "有音軌", "音量", "長靜音段", "畫面變化", "字幕對齊", "語速", "背景音樂"):
        assert key in verify["checks"], f"verify 少了「{key}」"

    # the publish package the SOP review step hands over
    pub = d / "publish"
    for name in ("video.mp4", "subtitles.srt", "thumbnail.jpg", "metadata.json", "description.txt",
                 "shorts/caption_tiktok.txt", "shorts/caption_instagram.txt",
                 "shorts/vertical_9x16.mp4"):
        assert (pub / name).is_file(), f"發布包少了 {name}"
    meta = json.loads((pub / "metadata.json").read_text("utf-8"))
    assert meta["title"] and meta["shorts"]["vertical"] is True


def test_gate_double_click_runs_once(client):
    set_settings(client, llm={"provider": "mock"})
    eid = _new_episode(client, "台灣夜市小吃的由來")
    ep = wait_for(client, eid)
    assert ep["waiting_for"] == "direction"
    did = ep["files"]["brief"]["directions"][0]["id"]

    first = client.post(f"/api/episodes/{eid}/direction", json={"id": did})
    second = client.post(f"/api/episodes/{eid}/direction", json={"id": did})
    assert first.status_code == 200
    assert second.status_code == 409, "第二次點擊應該被擋下，不能重跑一次"

    ep = wait_for(client, eid)
    assert ep["waiting_for"] == "script"
    assert client.post(f"/api/episodes/{eid}/approve").status_code == 409  # wrong gate


def test_bad_direction_id_is_400_and_keeps_gate(client):
    set_settings(client, llm={"provider": "mock"})
    eid = _new_episode(client, "電動機車換電站怎麼運作")
    ep = wait_for(client, eid)
    r = client.post(f"/api/episodes/{eid}/direction", json={"id": "Z"})
    assert r.status_code == 400, r.text
    ep = client.get(f"/api/episodes/{eid}").json()  # still parked at the same gate, retryable
    assert (ep["status"], ep["waiting_for"]) == ("waiting", "direction")
    assert client.post(f"/api/episodes/{eid}/direction",
                       json={"id": ep["files"]["brief"]["directions"][0]["id"]}).status_code == 200


def test_bad_package_index_is_400(client):
    set_settings(client, llm={"provider": "mock"}, visuals={"source": "slides"},
                 render={"engine": "ffmpeg"}, music={"provider": "openverse"})
    eid = _new_episode(client)
    for _ in range(4):  # direction, script, storyboard, then stop at package
        ep = wait_for(client, eid)
        if ep["waiting_for"] == "package":
            break
        {"direction": lambda: client.post(f"/api/episodes/{eid}/direction",
                                          json={"id": ep["files"]["brief"]["directions"][0]["id"]}),
         "script": lambda: client.post(f"/api/episodes/{eid}/script", json={"approve": True}),
         "storyboard": lambda: client.post(f"/api/episodes/{eid}/storyboard", json={"approve": True}),
         }[ep["waiting_for"]]()
    else:
        pytest.fail("沒有走到標題閘門")
    assert client.post(f"/api/episodes/{eid}/package", json={"title": 99, "thumb": 0}).status_code == 400
    assert client.post(f"/api/episodes/{eid}/package", json={"title": 0, "thumb": 99}).status_code == 400


def test_music_open_outside_data_is_400(client):
    assert client.post("/api/music/open", json={"path": "/etc/hostname"}).status_code == 400
    assert client.post("/api/music/open", json={"path": "/nope/missing.wav"}).status_code == 400


def test_reject_to_script_resets_storyboard_gate(client):
    """B3: a new script must be re-checked at the storyboard gate, not skipped."""
    set_settings(client, llm={"provider": "mock"})
    eid = _new_episode(client)
    ep = wait_for(client, eid)
    client.post(f"/api/episodes/{eid}/direction", json={"id": ep["files"]["brief"]["directions"][0]["id"]})
    ep = wait_for(client, eid)
    client.post(f"/api/episodes/{eid}/script", json={"approve": True})
    ep = wait_for(client, eid)
    assert ep["waiting_for"] == "storyboard"
    client.post(f"/api/episodes/{eid}/storyboard", json={"approve": True})

    ep = wait_for(client, eid)
    # reject back to the script even though the storyboard was approved
    client.post(f"/api/episodes/{eid}/reject", json={"back_to": "script", "reason": "講稿事實要再查一次"})
    ep2 = store.get_episode(eid)
    assert ep2["stage"] == "script", "退件回講稿要從寫稿重跑"
    assert ep2["storyboard_approved"] is False, "退回講稿後分鏡閘門必須重跑"

    ep = wait_for(client, eid)
    assert ep["waiting_for"] == "script"
    client.post(f"/api/episodes/{eid}/script", json={"approve": True})
    ep = wait_for(client, eid)
    assert ep["waiting_for"] == "storyboard", "重寫講稿後應再過一次分鏡閘門"
