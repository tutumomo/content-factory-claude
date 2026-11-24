"""MiniMax-H3 text-to-video scene clips through ComfyUI's native H3 nodes.

Graph follows the installed reference workflow (CG迷 MiniMax H3 文生视频): MiniMaxH3ImageToVideo with no
frames = T2V, SamplerCustomAdvanced + res_multistep, VAEDecode + VAEDecodeAudio -> CreateVideo -> SaveVideo. The clip
keeps H3's own ambient soundtrack; the pipeline mixes it under the narration (h3video.ambient_gain_db).
"""
from __future__ import annotations

import math
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from . import comfy, store

_OVERRIDE = threading.local()
FPS = 24
# Pika H3 Flex 6-NFE sigma knots (from the official template's ManualSigmas node)
FLEX_SIGMAS = "1.0, 0.972973, 0.923077, 0.8, 0.571429, 0.333333, 0.0"
CAMERA = [
    "The camera pushes in with small amplitude at slow speed",
    "The camera trucks right with small amplitude at slow speed",
    "The camera pulls out with small amplitude at slow speed",
    "The camera tilts up with small amplitude at slow speed",
]


def cfg() -> dict:
    """The h3video settings, with any per-call override merged on top."""
    base = dict(store.get_settings().get("h3video") or {})
    over = getattr(_OVERRIDE, "cfg", None)
    if over:
        base.update(over)
    return base


@contextmanager
def using(overrides: dict | None):
    """Apply per-call H3 settings for the block (an episode may pick its own recipe)."""
    prev = getattr(_OVERRIDE, "cfg", None)
    _OVERRIDE.cfg = dict(overrides) if overrides else None
    try:
        yield
    finally:
        _OVERRIDE.cfg = prev



def frames_for(seconds: float) -> int:
    """H3 wants 17k+5 frames at 24 fps (same rule as the reference workflow's math node)."""
    n = max(5, round(seconds * FPS))
    return n + (5 - n % 17) % 17


def dims_for(size: tuple[int, int], megapixels: float) -> tuple[int, int]:
    """Generation size with the target aspect ratio, area ≈ megapixels·1024², multiples of 32."""
    px = max(0.1, megapixels) * 1024 * 1024
    ar = size[0] / size[1]
    w = max(256, round(math.sqrt(px * ar) / 32) * 32)
    h = max(256, round(math.sqrt(px / ar) / 32) * 32)
    return w, h


def prompt_for(desc: str, style: str, i: int) -> str:
    """H3 T2VA prompt: one continuous shot, gentle camera move, no speech, no text, no score."""
    look = f"{style.strip().rstrip('.')}. " if style.strip() else ""
    return (
        f"integrated_multimodal_description: [Shot 1] {look}{desc.strip().rstrip('.')}. "
        f"One continuous shot with no cuts. {CAMERA[i % len(CAMERA)]}, revealing the scene gradually. "
        "Nobody speaks and no lips move. No on-screen text, captions, subtitles, logos or watermarks appear.\n\n"
        "overall_soundscape: Soft ambient room tone that matches the setting, with quiet natural background sounds.\n\n"
        "non_diegetic_music: N/A"
    )


def graph(prompt: str, w: int, h: int, length: int, seed: int) -> dict:
    c = cfg()
    flex = (c.get("recipe") or "flex").lower() == "flex"
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": c.get("unet") or "minimax_h3_fl2va_pruned_int8_convrot_ssd.safetensors",
                                                     "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": c.get("clip") or "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                                                     "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": c.get("vae") or "minimax_h3_video_vae_int8_convrot_ssd.safetensors"}},
        "4": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {"clip": ["2", 0], "vae": ["3", 0], "prompt": prompt,
                                                                "width": w, "height": h, "length": length}},
        "5": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "6": {"class_type": "BasicGuider", "inputs": {"model": ["1", 0], "conditioning": ["4", 0]}},
        "9": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["5", 0], "guider": ["6", 0], "sampler": ["7", 0],
                                                                "sigmas": ["8", 0], "latent_image": ["4", 1]}},
        "10": {"class_type": "VAEDecode", "inputs": {"samples": ["9", 0], "vae": ["3", 0]}},
        "13": {"class_type": "VAELoader", "inputs": {"vae_name": c.get("audio_vae") or "minimax_h3_audio_vae_fp32_ssd.safetensors"}},
        "14": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["9", 0], "vae": ["13", 0]}},
        "11": {"class_type": "CreateVideo", "inputs": {"images": ["10", 0], "audio": ["14", 0], "fps": float(FPS)}},
        "12": {"class_type": "SaveVideo", "inputs": {"video": ["11", 0], "filename_prefix": "video/cf_h3",
                                                     "format": "auto", "format.codec": "auto"}},
    }
    model = ["1", 0]
    lora = (c.get("lora") or "").strip()
    if lora:  # flex adapter, strength 1.0 = the released scale
        strength = float(c.get("lora_strength") or 1.0)
        if (c.get("lora_node") or "turbo").lower() == "turbo":
            # Stock LoRA patching costs ~13 s/step on this int8 base; the Turbo pack's adapter
            # bypasses it (measured 6 steps in 130 s vs 502 s) and needs prefix-stripped keys.
            g["15"] = {"class_type": "MiniMaxH3TurboLoRA", "inputs": {
                "model": ["1", 0], "lora_name": lora, "strength": strength,
                "low_vram": bool(c.get("lora_merge", False))}}
        else:
            g["15"] = {"class_type": "LoraLoaderModelOnly", "inputs": {
                "model": ["1", 0], "lora_name": lora, "strength_model": strength}}
        model = ["15", 0]
        g["6"]["inputs"]["model"] = model
    if flex:
        # Pika H3 Flex contract: 6 NFE, lcm sampler, fixed sigma knots (generic 6-step sampling is not equivalent)
        g["7"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "lcm"}}
        g["8"] = {"class_type": "ManualSigmas", "inputs": {"sigmas": c.get("sigmas") or FLEX_SIGMAS}}
    else:
        g["7"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": c.get("sampler") or "res_multistep"}}
        g["8"] = {"class_type": "BasicScheduler", "inputs": {"model": model, "scheduler": "simple",
                                                             "steps": int(c.get("steps") or 25), "denoise": 1.0}}
    return g


def generate(desc: str, size: tuple[int, int], seconds: float, out: Path, i: int = 0,
             seed: int | None = None) -> Path:
    """Render one scene clip (mp4 with H3 ambient audio) and save it to `out`."""
    c = cfg()
    secs = min(float(c.get("max_seconds") or 6), max(2.0, seconds))
    w, h = dims_for(size, float(c.get("megapixels") or 0.4))
    g = graph(prompt_for(desc, c.get("style_hint") or "", i), w, h, frames_for(secs),
              seed if seed is not None else int(time.time()) % 2**31)
    return comfy.run_graph(g, out, float(c.get("timeout_s") or 1800), "出影片")
