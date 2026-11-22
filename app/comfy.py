"""ComfyUI client for scene backgrounds (Krea-2／MiniMax-H3-Image／MOSS-Image／Qwen Image 2.1).

Falls back to Pillow cards when ComfyUI is down; the caller decides.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

import httpx

from . import store

# Per-family model combos (files from the ComfyUI loader enums on this box) + tuned
# sampler settings taken from the installed reference workflows. 中文文字：Krea-2 弱，
# H3／MOSS／Qwen 2.1 都能寫字；NSFW：四個都能。畫不動就退回 Pillow 字卡。
PRESETS: dict[str, dict] = {
    "krea2": {
        "label": "Krea-2（kromaKrea2）",
        "unet": "kromaKrea2_opd.safetensors",
        "clip": "Huihui-Qwen3-VL-4B-Instruct-abliterated-fp8_scaled.safetensors",
        "clip_type": "krea2",
        "vae": "qwen_image_vae.safetensors",
        "steps": 8, "cfg": 1.0, "sampler": "euler",
        "note": "NSFW 首選、最快；寫中文字能力弱，畫面要中文字時選別的組合",
    },
    "h3": {
        "label": "MiniMax-H3-Image",
        "unet": "minimax_h3_image_pruned_int8_convrot.safetensors",
        "clip": "qwen3vl_32b_h3_ultra_uncensored_heretic_int8_convrot.safetensors",
        "clip_type": "minimax",
        "vae": "minimax_h3_image_vae_fp16.safetensors",
        "steps": 6, "cfg": 1.0, "sampler": "euler",
        "note": "中文文字、NSFW 都可以；6 步 turbo，速度快",
    },
    "moss": {
        "label": "MOSS-Image",
        "unet": "kromoss_int8_convrot.safetensors",
        "clip": "qwen3.5_9b_uncensored_int8_convrot.safetensors",
        "clip_type": "moss_image",
        "vae": "flux2-vae_small.safetensors",
        "steps": 25, "cfg": 3.0, "sampler": "heun",
        "timeout_s": 2400,
        "note": "中文文字、NSFW 都可以；25 步較慢（實測超過 15 分鐘），配 dmd2 LoRA 可降到 8 步",
    },
    "qwen21": {
        "label": "Qwen Image 2.1",
        "unet": "qwen_image_2.1_int8_convrot.safetensors",
        "clip": "qwen3vl_8b_int8_convrot.safetensors",
        "clip_type": "qwen_image",
        "vae": "qwen_image_2.1_vae_bf16.safetensors",
        "encode": "qwen21",                # 2.1 要 TextEncodeQwenImage21，不能用 CLIPTextEncode（會出雜訊）
        "steps": 25, "cfg": 1.0, "sampler": "dpmpp_2m_sde_gpu",
        "timeout_s": 900,
        "note": "中文文字最強、NSFW 亦可以；25 步較慢，文字編碼器用 qwen3vl_8b",
    },
}


class ComfyError(RuntimeError):
    """kind: "connection" = server gone (trip the breaker), "error" = job/model failure."""

    def __init__(self, msg: str, kind: str = "error"):
        super().__init__(msg)
        self.kind = kind


def cfg() -> dict:
    return store.get_settings().get("visuals") or {}


def base() -> str:
    return (cfg().get("comfy_url") or "http://127.0.0.1:8188").rstrip("/")


def health(timeout: float = 4) -> dict:
    try:
        r = httpx.get(base() + "/system_stats", timeout=timeout)
        r.raise_for_status()
        dev = (r.json().get("devices") or [{}])[0]
        return {"ok": True, "detail": f"ComfyUI 就緒（{dev.get('name', 'GPU')}）"}
    except httpx.HTTPError as e:
        return {"ok": False, "detail": f"ComfyUI 連不上：{e}（請先執行 ./start_comfyui.sh）"}


def presets() -> dict:
    """Preset list plus whether each file shows up in ComfyUI's loader enums."""
    enum: dict[str, set[str]] = {}
    try:
        for path, key in (("UNETLoader", "unet"), ("CLIPLoader", "clip"), ("VAELoader", "vae")):
            r = httpx.get(base() + f"/object_info/{path}", timeout=20)
            r.raise_for_status()
            req = r.json()[path]["input"]["required"]
            field = {"unet": "unet_name", "clip": "clip_name", "vae": "vae_name"}[key]
            enum[key] = set(next(v for v in req[field] if isinstance(v, list)))
    except (httpx.HTTPError, StopIteration, KeyError):
        enum = {}
    items = []
    for pid, p in PRESETS.items():
        miss = [f"{k}:{p[k]}" for k in ("unet", "clip", "vae") if p[k] not in enum.get(k, ())] if enum else []
        if not enum:
            miss = [f"{k}:?" for k in ("unet", "clip", "vae")]
        items.append({**p, "id": pid, "installed": not miss, "missing": miss})
    return {"presets": items, "detected": bool(enum)}


def _graph(prompt: str, w: int, h: int, seed: int) -> dict:
    c = cfg()
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": c.get("unet") or "kromaKrea2_opd.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": c.get("clip") or "Huihui-Qwen3-VL-4B-Instruct-abliterated-fp8_scaled.safetensors",
                                                     "type": c.get("clip_type") or "krea2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": c.get("vae") or "qwen_image_vae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0],
            "seed": seed, "steps": int(c.get("steps") or 8), "cfg": float(c.get("cfg") or 1.0),
            "sampler_name": c.get("sampler") or "euler", "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "cf_scene"}},
    }
    lora = (c.get("lora") or "").strip()
    if lora:
        g["10"] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": ["1", 0], "lora_name": lora, "strength_model": float(c.get("lora_strength") or 0.8)}}
        g["7"]["inputs"]["model"] = ["10", 0]
    if (c.get("encode") or "") == "qwen21":
        g["4"] = {"class_type": "TextEncodeQwenImage21", "inputs": {
            "clip": ["2", 0], "prompt": prompt, "negative_prompt": "", "resolution": 0, "images": {}}}
        g.pop("5", None)
        g["7"]["inputs"]["negative"] = ["4", 1]
    return g


def generate(prompt: str, size: tuple[int, int], out: Path, seed: int | None = None) -> Path:
    """Run one text-to-image job and save the result to `out`."""
    graph = _graph(prompt, size[0], size[1], seed if seed is not None else int(time.time()) % 2**31)
    return run_graph(graph, out, float(cfg().get("timeout_s") or 600), "出圖")


def run_graph(graph: dict, out: Path, tmo: float, what: str = "出圖") -> Path:
    """Queue an API-format graph, wait for its first saved file (image or video) and copy it to `out`."""
    body = {"prompt": graph, "client_id": uuid.uuid4().hex}
    try:
        r = httpx.post(base() + "/prompt", json=body, timeout=30)
        r.raise_for_status()
        pid = r.json()["prompt_id"]
    except httpx.HTTPError as e:
        raise ComfyError(f"送出工作失敗：{e}", "connection") from e
    deadline = time.time() + tmo
    misses = 0
    while time.time() < deadline:
        time.sleep(2)
        try:
            hr = httpx.get(base() + f"/history/{pid}", timeout=15).json()
            misses = 0
        except httpx.HTTPError as e:
            misses += 1
            if misses >= 8:  # ~30 s without an answer: the server is gone, stop burning the timeout
                raise ComfyError(f"ComfyUI 中途連不上：{e}", "connection") from e
            continue
        entry = hr.get(pid) or {}
        status = entry.get("status") or {}
        if status.get("status_str") == "error":
            why = next((m[1].get("exception_message", "") for m in status.get("messages") or []
                        if m and m[0] == "execution_error" and isinstance(m[1], dict)), "")
            raise ComfyError("ComfyUI 生成失敗：" + (why.strip()[:200] or "看 ComfyUI 主控台錯誤"))
        imgs = [i for o in (entry.get("outputs") or {}).values() for k in ("images", "videos", "gifs")
                for i in (o.get(k) or []) if isinstance(i, dict) and i.get("filename")]
        if imgs:
            im = imgs[0]
            vr = httpx.get(base() + "/view", params={"filename": im["filename"], "subfolder": im.get("subfolder", ""),
                                                     "type": im.get("type", "output")}, timeout=300)
            vr.raise_for_status()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(vr.content)
            return out
    cancel(pid)  # don't leave the job holding the shared GPU
    raise ComfyError(f"等超過 {tmo:.0f} 秒還沒{what}")


def cancel(pid: str) -> None:
    """Stop a job we gave up on: /interrupt only if it is the one running, and drop it from the queue."""
    try:
        q = httpx.get(base() + "/queue", timeout=10).json()
    except (httpx.HTTPError, ValueError):
        return
    running = [row[1] for row in (q.get("queue_running") or []) if len(row) > 1]
    pending = [row[1] for row in (q.get("queue_pending") or []) if len(row) > 1]
    try:
        if pid in running:
            httpx.post(base() + "/interrupt", json={"prompt_id": pid}, timeout=10)
        if pid in pending or pid in running:
            httpx.post(base() + "/queue", json={"delete": [pid]}, timeout=10)
    except httpx.HTTPError:
        pass


def free() -> None:
    """Release ComfyUI's models after a batch so the shared GPU goes back to other work."""
    try:
        httpx.post(base() + "/free", json={"unload_models": True, "free_memory": True}, timeout=15)
    except httpx.HTTPError:
        pass
