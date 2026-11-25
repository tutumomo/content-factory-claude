"""系統狀態面板：狀態判定（就緒／降級／停用）與探測失敗的處理。"""
from app import health


def _stub(ok, detail="", hint=""):
    return lambda: {"ok": ok, "detail": detail, "hint": hint}


def _all(monkeypatch, ok=True):
    for key in list(health.PROBES):
        monkeypatch.setitem(health.PROBES, key, _stub(ok))


def test_all_ok_reports_everything_ready(monkeypatch):
    _all(monkeypatch)
    d = health.services()
    assert d["summary"] == {"ok": len(health.SERVICES), "warn": 0, "off": 0,
                            "total": len(health.SERVICES)}
    assert [s["id"] for s in d["services"]] == [sid for sid, *_ in health.SERVICES]
    assert all(s["state"] == "ok" and s["hint"] == "" for s in d["services"])


def test_required_down_is_off_and_optional_down_is_warn(monkeypatch):
    _all(monkeypatch)
    monkeypatch.setitem(health.PROBES, "ffmpeg", _stub(False, "沒有 libass", "brew link --overwrite ffmpeg-full"))
    monkeypatch.setitem(health.PROBES, "comfy", _stub(False, "ComfyUI 沒開"))
    rows = {s["id"]: s for s in health.services()["services"]}
    assert rows["ffmpeg"]["state"] == "off"
    assert rows["ffmpeg"]["hint"].startswith("brew link")
    assert rows["comfy"]["state"] == "warn"
    assert rows["comfy"]["detail"] == "ComfyUI 沒開"


def test_probe_exception_becomes_a_row_instead_of_a_crash(monkeypatch):
    _all(monkeypatch)

    def boom():
        raise RuntimeError("socket closed")

    monkeypatch.setitem(health.PROBES, "youtube", boom)
    d = health.services()
    row = next(s for s in d["services"] if s["id"] == "youtube")
    assert row["state"] == "warn"
    assert "RuntimeError" in row["detail"] and "socket closed" in row["detail"]


def test_endpoint_serves_the_rows(client, monkeypatch):
    _all(monkeypatch)
    monkeypatch.setitem(health.PROBES, "audiocpp", _stub(False, "連不上 audio.cpp"))
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["total"] == len(health.SERVICES)
    assert next(s for s in body["services"] if s["id"] == "audiocpp")["state"] == "warn"
