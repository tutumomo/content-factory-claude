"""Offline tests for the source chains (visuals / narration / music / sfx).

No network and no GPU: probes are patched per test, the mock LLM supplies scripts, TTS is a
locally generated tone and every remote fetcher is stubbed. Run with:

    .venv/bin/python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from app import comfy, cost, media, music, pipeline, sfx, sources, stock, stock_audio, store


def tone(path: Path, seconds: float = 0.4, rate: int = 24000) -> Path:
    """A quiet sine wav: enough for ffmpeg/duration code, too fast to be TTS."""
    n = int(seconds * rate)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(200 * math.sin(2 * math.pi * 220 * i / rate)))
                               for i in range(n)))
    return path


def tiny_clip(path: Path, seconds: float = 1.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"testsrc=size=320x180:rate=24:duration={seconds}", "-pix_fmt", "yuv420p", str(path)],
                   check=True)
    return path


PROBES = {"visuals": sources._probe_visuals, "voice": sources._probe_voice,
          "music": sources._probe_music, "sfx": sources._probe_sfx}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data = root / "data"
        self.data.mkdir()
        patches = [
            mock.patch.object(store, "DATA", self.data),
            mock.patch.object(store, "EPISODES", self.data / "episodes"),
            mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key", "PEXELS_API_KEY": "k",
                                         "PIXABAY_API_KEY": "", "FREESOUND_API_KEY": "fs"}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        sources._cache.clear()

    def settings(self, **patch):
        """Save settings overrides (merged with defaults) and return the merged dict."""
        cur = store.get_settings()
        for k, v in patch.items():
            if isinstance(v, dict) and isinstance(cur.get(k), dict):
                cur[k] = {**cur[k], **v}
            else:
                cur[k] = v
        store.save_settings(cur)
        return store.get_settings()

    def probes(self, ok: dict[tuple[str, str], bool]):
        """Replace the probe table: (kind, source) → ok; anything unnamed is usable."""
        def make(kind):
            def fn(src):
                good = ok.get((kind, src), True)
                return {"ok": good, "detail": "" if good else "測試：未開"}
            return fn
        for kind in sources.KINDS:
            p = mock.patch.dict(sources._PROBES, {kind: make(kind)})
            p.start()
            self.addCleanup(p.stop)


class ChainTests(Base):
    def test_legacy_visuals_source_derives_chain(self):
        self.settings(visuals={"source": "comfy"})
        self.assertEqual(sources.chain("visuals"), ["comfy", "stock", "slides"])
        self.settings(visuals={"source": "slides"})
        self.assertEqual(sources.chain("visuals"), ["slides"])
        self.settings(visuals={"source": "mix"})
        self.assertEqual(sources.chain("visuals"), ["stock", "comfy", "slides"])

    def test_explicit_chain_wins_and_paid_stays_out(self):
        self.settings(sources={"visuals": {"chain": ["stock", "slides"]}},
                      music={"provider": "audiocpp"})
        self.assertEqual(sources.chain("visuals"), ["stock", "slides"])
        self.assertEqual(sources.chain("music"), ["audiocpp", "openverse"])  # lyria is paid
        self.settings(sources={"allow_paid_fallback": True})
        sources._cache.clear()
        self.assertEqual(sources.chain("music"), ["audiocpp", "openverse", "lyria"])

    def test_explicitly_chosen_paid_source_is_kept(self):
        self.settings(music={"provider": "lyria"})
        self.assertEqual(sources.chain("music"), ["lyria", "openverse"])
        self.settings(music={"provider": "audiocpp"})
        self.assertEqual(sources.chain("music"), ["audiocpp", "openverse"])

    def test_voice_chain_defaults(self):
        self.assertEqual(sources.chain("voice"), ["audiocpp", "edge"])  # gemini paid, off by default
        self.settings(sources={"allow_paid_fallback": True})
        self.assertEqual(sources.chain("voice"), ["audiocpp", "edge", "gemini"])

    def test_breaker_opens_after_two_failures(self):
        br = sources.Breaker()
        br.fail("comfy")
        self.assertTrue(br.ok("comfy"))
        br.fail("comfy")
        self.assertFalse(br.ok("comfy"))
        br2 = sources.Breaker()
        br2.trip("comfy")
        self.assertFalse(br2.ok("comfy"))

    def test_probe_results_are_cached(self):
        calls = []
        fake = lambda src: calls.append(src) or {"ok": True, "detail": ""}  # noqa: E731
        with mock.patch.dict(sources._PROBES, {"visuals": fake}):
            sources.probe("visuals", ["stock", "slides"])
            sources.probe("visuals", ["stock", "slides"])
        self.assertEqual(sorted(calls), ["slides", "stock"])


class VisualTests(Base):
    def _scenes(self, n=3):
        return [{"narration": f"第 {i} 段。", "visual": "a desk", "headline": "", "stock_query": "desk"}
                for i in range(n)]

    def test_comfy_down_falls_to_stock_then_slides(self):
        self.probes({("visuals", "h3video"): False, ("visuals", "comfy"): False})
        store.save_settings({**store.get_settings(), "visuals": {"source": "comfy"}})
        sources._cache.clear()
        plan, br = sources.start(["visuals"])
        self.assertEqual(plan.chosen("visuals"), "stock")
        seen = []

        def stock_fn(sc, i):
            seen.append(("stock", i))
            return {"kind": "stock", "path": Path(f"/tmp/x{i}.mp4"), "meta": {}} if i < 2 else None

        got = sources.visual_batches(plan, br, self._scenes(), False, {"stock": stock_fn},
                                     lambda *a: None, "e")
        self.assertEqual(sorted(got), [0, 1])
        self.assertEqual({v["kind"] for v in got.values()}, {"stock"})

    def test_no_keys_everywhere_means_slides(self):
        self.probes({("visuals", "h3video"): False, ("visuals", "comfy"): False,
                     ("visuals", "stock"): False, ("visuals", "slides"): False})
        self.settings(visuals={"source": "h3video"})
        sources._cache.clear()
        plan, _ = sources.start(["visuals"])
        self.assertEqual(plan.chosen("visuals"), "")
        self.assertEqual(sources.Report().badges(plan, 3), [])

    def test_two_comfy_errors_stop_the_batch(self):
        self.probes({("visuals", "h3video"): False})
        self.settings(visuals={"source": "comfy"})
        sources._cache.clear()
        plan, br = sources.start(["visuals"])
        calls = []

        def boom(sc, i):
            calls.append(i)
            raise comfy.ComfyError("連不上", "connection")

        sources.visual_batches(plan, br, self._scenes(4), False, {"comfy": boom}, lambda *a: None, "e")
        self.assertEqual(len(calls), 2)  # breaker opened, remaining scenes never touch ComfyUI
        self.assertFalse(br.ok("comfy"))


class VoiceTests(Base):
    def _plan(self, ok):
        self.probes(ok)
        self.settings(sources={"voice": {"chain": ["audiocpp", "edge", "gemini"]}, "allow_paid_fallback": True})
        sources._cache.clear()
        plan, br = sources.start(["voice"])
        return plan, br

    def test_audiocpp_down_uses_edge(self):
        plan, br = self._plan({("voice", "audiocpp"): False})
        narr = sources.Narrator(plan, br, lambda *a: None, "e", total_chars=500)
        with mock.patch.object(media, "TTS_SOURCES", {"edge": lambda t, o, emotion="": tone(o)}):
            src, p = narr.say("測試一句。", self.data / "a.wav")
        self.assertEqual(src, "edge")
        self.assertTrue(p.exists())

    def test_both_free_fail_lands_on_gemini(self):
        plan, br = self._plan({})

        def boom(t, o, emotion=""):
            raise media.MediaError("503")

        with mock.patch.object(media, "TTS_SOURCES",
                               {"audiocpp": boom, "edge": boom,
                                "gemini": lambda t, o, emotion="": tone(o)}):
            narr = sources.Narrator(plan, br, lambda *a: None, "e", total_chars=500)
            src, _ = narr.say("測試一句。", self.data / "b.wav")
        self.assertEqual(src, "gemini")
        self.assertGreater(cost.month_sum(), 0)  # the call was not allowed to be free

    def test_gemini_needing_approval_is_skipped_and_episode_still_errors_clearly(self):
        plan, br = self._plan({})
        self.settings(cost={"per_call_approval_usd": 0.0})  # any cost needs approval

        def boom(t, o, emotion=""):
            raise media.MediaError("down")

        with mock.patch.object(media, "TTS_SOURCES", {"audiocpp": boom, "edge": boom}):
            narr = sources.Narrator(plan, br, lambda *a: None, "e", total_chars=5000)
            with self.assertRaises(media.MediaError) as ctx:
                narr.say("測試一句。", self.data / "c.wav")
        self.assertIn("沒有可用來源", str(ctx.exception))
        self.assertNotIn("gemini", [s for s in narr.order])

    def test_gemini_spending_cap_is_reported(self):
        plan, br = self._plan({})
        body = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                          "message": "Your project has exceeded its monthly spending limit"}}

        class R:
            status_code = 429
            text = json.dumps(body)

        with mock.patch.object(media.httpx, "post", return_value=R()):
            with self.assertRaises(media.MediaError) as ctx:
                media.gemini_tts("測試", self.data / "d.wav")
        self.assertIn("spending", str(ctx.exception))


class MusicTests(Base):
    def _plan(self, ok):
        self.probes(ok)
        self.settings(music={"provider": "audiocpp"})
        sources._cache.clear()
        plan, br = sources.start(["music"])
        return plan, br

    def test_audiocpp_down_uses_openverse(self):
        plan, br = self._plan({("music", "audiocpp"): False})
        with mock.patch.object(music, "openverse_generate", lambda *a, **k: tone(self.data / "m.wav", 1.0)):
            p, src = sources.pick_music(plan, br, 10, "lo-fi", "e", lambda *a: None)
        self.assertEqual(src, "openverse")

    def test_lyria_is_last_and_needs_cost_approval(self):
        self.settings(sources={"allow_paid_fallback": True, "music": {"chain": ["audiocpp", "lyria"]}},
                      music={"provider": "audiocpp", "lyria_model": "lyria-3-pro-preview"})
        self.settings(cost={"per_call_approval_usd": 0.001})  # anything paid needs approval
        self.probes({("music", "audiocpp"): False})
        sources._cache.clear()
        plan, br = sources.start(["music"])
        logs = []
        with mock.patch.object(music.httpx, "post", side_effect=AssertionError("paid call attempted")), \
                self.assertRaises(music.MusicError):
            sources.pick_music(plan, br, 10, "lo-fi", "e", lambda *a: logs.append(a))
        self.assertTrue(any("需要核准" in str(x) for x in logs))


class ComfyCancelTests(Base):
    def test_timeout_cancels_only_that_prompt(self):
        calls = []

        class R:
            def __init__(self, body):
                self._b = body

            def raise_for_status(self):
                pass

            def json(self):
                return self._b

        def post(url, json=None, timeout=None):
            calls.append(("post", url.replace(comfy.base(), ""), json))
            return R({"prompt_id": "abc"})

        def get(url, timeout=None, params=None):
            if url.endswith("/queue"):
                return R({"queue_running": [[0, "abc", {}, {}, []]], "queue_pending": []})
            return R({})  # /history: never finished

        with mock.patch.object(comfy.httpx, "post", post), \
             mock.patch.object(comfy.httpx, "get", get), \
             mock.patch.object(comfy.time, "sleep", lambda s: None):
            with self.assertRaises(comfy.ComfyError):
                comfy.run_graph({}, self.data / "x.png", tmo=0.01, what="出圖")
        self.assertIn(("post", "/interrupt", {"prompt_id": "abc"}), calls)
        self.assertIn(("post", "/queue", {"delete": ["abc"]}), calls)


class AssembleTests(Base):
    """Real assembly on a two-scene episode: ffmpeg only, every network call stubbed."""

    def _episode(self):
        ep = store.new_episode("來源降級測試", "long")
        scr = {"music": "warm lo-fi, no vocals", "scenes": [
            {"narration": "第一段旁白，簡短。", "headline": "重點一", "bullets": ["甲"], "style": "clean",
             "visual": "a desk", "stock_query": "desk", "emotion": "", "sfx": "ding"},
            {"narration": "第二段旁白，也簡短。", "headline": "重點二", "bullets": ["乙"], "style": "clean",
             "visual": "a window", "stock_query": "window", "emotion": "", "sfx": "whoosh"},
        ]}
        store.write_json(ep["id"], "script.json", scr)
        return ep

    def _run(self, comfy_ok: bool, voice_ok: bool = True):
        ep = self._episode()
        clip = tiny_clip(self.data / "stock" / "clip.mp4")
        self.settings(visuals={"source": "comfy", "free_after": False},
                      render={"engine": "ffmpeg"},
                      sources={"voice": {"chain": ["audiocpp", "edge"]}})
        self.probes({("visuals", "h3video"): False, ("visuals", "comfy"): comfy_ok,
                     ("music", "audiocpp"): False, ("voice", "audiocpp"): voice_ok})
        sources._cache.clear()
        with mock.patch.object(media, "tts_health", lambda timeout=5: {"ok": True}), \
             mock.patch.object(media, "TTS_SOURCES", {"audiocpp": lambda t, o, emotion="": tone(o),
                                                      "edge": lambda t, o, emotion="": tone(o)}), \
             mock.patch.object(media, "align", lambda w, t: None), \
             mock.patch.object(comfy, "health", lambda timeout=4: {"ok": comfy_ok, "detail": "測試"}), \
             mock.patch.object(stock, "fetch",
                               lambda q, vertical=False: {"path": clip, "provider": "pexels", "author": "a",
                                                          "page": "", "license": "", "duration": 1.0,
                                                          "query": q}), \
             mock.patch.object(stock, "save_sources", lambda *a, **k: None), \
             mock.patch.object(music, "openverse_generate", lambda *a, **k: tone(self.data / "bgm.wav", 1.5)), \
             mock.patch.object(stock_audio, "fetch_sfx", lambda tag, dest: None):
            ok = pipeline.st_assemble(store.get_episode(ep["id"]))
        self.assertTrue(ok)
        return store.read_json(ep["id"], "output/verify.json"), ep["id"]

    def test_comfy_down_episode_finishes_with_stock_and_badges(self):
        v, eid = self._run(comfy_ok=False)
        self.assertIn("實拍素材 2 段", v["checks"]["畫面來源"]["value"])
        self.assertEqual(v["sources"]["music"], "openverse")
        kinds = {b["label"]: b["text"] for b in v["sources"]["badges"]}
        self.assertIn("畫面", kinds)
        self.assertIn("ComfyUI 生圖 未開", kinds["畫面"])   # the owner's setting asked for ComfyUI
        self.assertIn("實拍素材 2/2", kinds["畫面"])
        self.assertTrue((store.ep_dir(eid) / "output" / "final.mp4").exists())

    def test_audiocpp_down_episode_finishes_on_edge_and_flags_the_voice(self):
        v, _ = self._run(comfy_ok=True, voice_ok=False)
        self.assertEqual(v["sources"]["voice"]["used"], {"edge": 2})
        self.assertTrue(v["sources"]["voice"]["fallback"])
        self.assertFalse(v["checks"]["配音來源"]["ok"])
        self.assertIn("Edge TTS 2/2", v["checks"]["配音來源"]["value"])
        self.assertIn("配音", {b["label"] for b in v["sources"]["badges"]})

    def test_plan_is_written_before_the_work(self):
        ep = self._episode()
        self.settings(visuals={"source": "slides"})
        self.probes({("voice", "audiocpp"): False, ("voice", "edge"): False, ("voice", "gemini"): False})
        sources._cache.clear()
        with mock.patch.object(media, "TTS_SOURCES", {"audiocpp": lambda t, o, emotion="": tone(o)}):
            with self.assertRaises(media.MediaError):
                pipeline.st_assemble(store.get_episode(ep["id"]))
        v = store.read_json(ep["id"], "output/verify.json")
        self.assertTrue(v.get("running"))
        self.assertTrue(any("配音" in line for line in v["sources"]["plan"]))


if __name__ == "__main__":
    unittest.main()
