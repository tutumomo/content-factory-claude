"""ComfyUI client for scene backgrounds (Krea-2 Turbo text-to-image), built as an API graph.

Falls back to Pillow cards when ComfyUI is down; the caller decides.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

import httpx

from . import store


class ComfyError(RuntimeError):
    pass


def cfg() -> dict:
    return store.get_settings().get("visuals") or {}


def base() -> str:
    return (cfg().get("comfy_url") or "http://127.0.0.1:8188").rstrip("/")


def health() -> dict:
    try:
        r = httpx.get(base() + "/system_stats", timeout=4)
        r.raise_for_status()
        dev = (r.json().get("devices") or [{}])[0]
        return {"ok": True, "detail": f"ComfyUI 就緒（{dev.get('name', 'GPU')}）"}
    except httpx.HTTPError as e:
        return {"ok": False, "detail": f"ComfyUI 連不上：{e}（請先執行 ./start_comfyui.sh）"}


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
            "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "cf_scene"}},
    }
    lora = (c.get("lora") or "").strip()
    if lora:
        g["10"] = {"class_type": "LoraLoaderModelOnly", "inputs": {
            "model": ["1", 0], "lora_name": lora, "strength_model": float(c.get("lora_strength") or 0.8)}}
        g["7"]["inputs"]["model"] = ["10", 0]
    return g


def generate(prompt: str, size: tuple[int, int], out: Path, seed: int | None = None) -> Path:
    """Run one text-to-image job and save the result to `out`."""
    cid = uuid.uuid4().hex
    tmo = float(cfg().get("timeout_s") or 600)
    body = {"prompt": _graph(prompt, size[0], size[1], seed if seed is not None else int(time.time()) % 2**31),
            "client_id": cid}
    try:
        r = httpx.post(base() + "/prompt", json=body, timeout=30)
        r.raise_for_status()
        pid = r.json()["prompt_id"]
    except httpx.HTTPError as e:
        raise ComfyError(f"送出工作失敗：{e}") from e
    deadline = time.time() + tmo
    while time.time() < deadline:
        time.sleep(2)
        try:
            hr = httpx.get(base() + f"/history/{pid}", timeout=15).json()
        except httpx.HTTPError:
            continue
        entry = hr.get(pid) or {}
        status = entry.get("status") or {}
        if status.get("status_str") == "error":
            raise ComfyError("ComfyUI 生成失敗（看 ComfyUI 主控台錯誤）")
        imgs = [i for o in (entry.get("outputs") or {}).values() for i in (o.get("images") or [])]
        if imgs:
            im = imgs[0]
            vr = httpx.get(base() + "/view", params={"filename": im["filename"], "subfolder": im.get("subfolder", ""),
                                                     "type": im.get("type", "output")}, timeout=60)
            vr.raise_for_status()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(vr.content)
            return out
    raise ComfyError(f"等超過 {tmo:.0f} 秒還沒出圖")


def free() -> None:
    """Release ComfyUI's models after a batch so the shared GPU goes back to other work."""
    try:
        httpx.post(base() + "/free", json={"unload_models": True, "free_memory": True}, timeout=15)
    except httpx.HTTPError:
        pass
