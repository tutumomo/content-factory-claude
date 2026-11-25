"""YouTube 成效自動回收：單集同步、同日更新、貼網址、批次同步。"""
from __future__ import annotations

import time

import pytest

from app import store, youtube


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _episode(topic: str, video_id: str = "") -> dict:
    ep = store.new_episode(topic, "short")
    if video_id:
        store.update_episode(ep["id"], youtube={
            "video_id": video_id, "status": "done",
            "url": f"https://www.youtube.com/watch?v={video_id}",
        })
    return ep


@pytest.fixture
def stats(monkeypatch):
    """Fake Data API; each call returns the next snapshot so a re-sync can change numbers."""
    snapshots = iter([{"views": 1000, "likes": 50, "comments": 7},
                      {"views": 1500, "likes": 80, "comments": 9}])
    seen: dict[str, object] = {}

    def fake(ids):
        seen["ids"] = list(ids)
        snap = next(snapshots, {"views": 1500, "likes": 80, "comments": 9})
        return {vid: dict(snap) for vid in ids if not vid.startswith("MISSING")}

    monkeypatch.setattr(youtube, "video_stats", fake)
    return seen


def test_sync_appends_todays_row(client, stats):
    ep = _episode("YouTube 成效：同步一集", "vidAAAAAAA1")
    r = client.post(f"/api/episodes/{ep['id']}/metrics/youtube", json={})
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "appended"
    assert stats["ids"] == ["vidAAAAAAA1"]
    rows = store.read_json(ep["id"], "metrics.json", [])
    assert len(rows) == 1
    assert rows[0] == {"platform": "YouTube", "date": _today(), "views": "1000", "watch_time": "",
                       "followers": "", "likes": "50", "saves": "", "comments": "7", "note": ""}


def test_resync_same_day_updates_instead_of_duplicating(client, stats):
    ep = _episode("YouTube 成效：同日重抓", "vidBBBBBBB2")
    assert client.post(f"/api/episodes/{ep['id']}/metrics/youtube", json={}).status_code == 200
    r = client.post(f"/api/episodes/{ep['id']}/metrics/youtube", json={})
    assert r.json()["action"] == "updated"
    rows = store.read_json(ep["id"], "metrics.json", [])
    assert len(rows) == 1
    assert (rows[0]["views"], rows[0]["likes"], rows[0]["comments"]) == ("1500", "80", "9")


def test_pasting_a_url_stores_the_video_id(client, stats):
    ep = _episode("YouTube 成效：貼網址")
    r = client.post(f"/api/episodes/{ep['id']}/metrics/youtube",
                    json={"url": "https://youtu.be/dQw4w9WgXcQ?t=10"})
    assert r.status_code == 200, r.text
    assert store.get_episode(ep["id"])["youtube"]["video_id"] == "dQw4w9WgXcQ"


def test_episode_without_video_is_a_400(client, stats):
    ep = _episode("YouTube 成效：沒影片")
    r = client.post(f"/api/episodes/{ep['id']}/metrics/youtube", json={})
    assert r.status_code == 400
    assert "網址" in r.json()["detail"]


def test_video_missing_on_youtube_is_a_404(client, stats):
    ep = _episode("YouTube 成效：影片不存在", "MISSING0001")
    r = client.post(f"/api/episodes/{ep['id']}/metrics/youtube", json={})
    assert r.status_code == 404


def test_batch_sync_updates_linked_episodes_only(client, stats):
    linked = _episode("YouTube 成效：批次有連結", "vidCCCCCCC3")
    plain = _episode("YouTube 成效：批次沒連結")
    r = client.post("/api/insights/sync-youtube")
    assert r.status_code == 200, r.text
    assert "vidCCCCCCC3" in stats["ids"]
    assert len(store.read_json(linked["id"], "metrics.json", [])) == 1
    assert store.read_json(plain["id"], "metrics.json", []) == []
