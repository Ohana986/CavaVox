#!/usr/bin/env python3
"""
CAVA Vocal Overlay — 双 cavacore 实例离线可视化器

核心算法完全使用 cavacore 共享库（与 cava 源码一致），
分别处理混音和人声两路音频流，人声频谱以覆盖色叠加在背景上。

配置来源：
  - general / smoothing 等参数从 ~/.config/cava/config 读取（与 cava 原生一致）
  - 人声覆盖/显示/路径等额外参数在底部 CONFIG 字典中自定义
  - 音频路径可通过 --mix / --vocal 命令行参数指定（覆盖 CONFIG）
"""
from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pygame
import soundfile as sf

from cavacore_wrap import cava_init, cava_execute, CavaPlan

_CACHE_DIR = Path(__file__).resolve().parent / "cache"


def _cache_key(mix_path: str, vocal_path: str, config: dict) -> str:
    """基于音频文件 + 关键参数生成缓存 key。"""
    h = hashlib.md5()
    for p in (mix_path, vocal_path):
        s = os.stat(p)
        h.update(f"{p}:{s.st_size}:{s.st_mtime_ns}".encode())
    relevant = {
        k: config[k] for k in (
            "bars", "framerate", "autosens", "sensitivity",
            "noise_reduction", "lower_cutoff", "higher_cutoff",
            "channels", "mono_option",
        )
    }
    h.update(json.dumps(relevant, sort_keys=True).encode())
    return h.hexdigest()

# =============================================================================
# 命令行参数
# =============================================================================

def _parse_args():
    p = argparse.ArgumentParser(description="CAVA Vocal Overlay")
    p.add_argument("--vocal", action="store_true", default=False,
                   help="只显示人声频谱（去掉白色背景）")
    p.add_argument("--offset", type=int, default=None,
                   help="帧偏移补偿（覆盖 CONFIG 中的 latency_offset）")
    p.add_argument("--mix", type=str, default=None,
                   help="混音 WAV 文件路径（覆盖 CONFIG mix_file）")
    p.add_argument("--vocal-file", type=str, default=None,
                   help="人声 WAV 文件路径（覆盖 CONFIG vocal_file）")
    return p.parse_args()


# =============================================================================
# 从 cava config 读取参数
# =============================================================================

_CAVA_CONFIG_PATH = str(Path.home() / ".config" / "cava" / "config")


def _read_cava_ini(path: str = _CAVA_CONFIG_PATH) -> dict:
    """读取 cava 配置文件中影响核心算法的参数。"""
    cfg = configparser.ConfigParser()
    cfg.optionxform = str
    cfg.read(path)

    def g(section: str, key: str, fallback: str = None):
        if not cfg.has_section(section):
            return fallback
        if cfg.has_option(section, key):
            raw = cfg.get(section, key)
            if raw.strip():
                return raw.strip()
        for k in cfg.options(section):
            if k.lstrip(";#").strip() == key:
                raw = cfg.get(section, k)
                if raw.strip():
                    return raw.strip()
        return fallback

    def gi(section: str, key: str, fb: int = 0) -> int:
        return int(g(section, key, str(fb)))

    result: dict = {}

    # [general]
    result["bars"] = gi("general", "bars", 0)
    result["framerate"] = gi("general", "framerate", 60)
    result["autosens"] = gi("general", "autosens", 1)
    result["sensitivity"] = gi("general", "sensitivity", 100)
    result["lower_cutoff"] = gi("general", "lower_cutoff_freq", 20)
    result["higher_cutoff"] = gi("general", "higher_cutoff_freq", 10000)
    result["max_height"] = gi("general", "max_height", 100)
    result["bar_width"] = gi("general", "bar_width", 2)
    result["bar_spacing"] = gi("general", "bar_spacing", 1)

    # [smoothing]
    result["noise_reduction"] = gi("smoothing", "noise_reduction", 77)

    # [output]
    ch = str(g("output", "channels", "stereo"))
    result["channels"] = "mono" if ch.strip().lower() == "mono" else "stereo"
    mo = str(g("output", "mono_option", "average"))
    result["mono_option"] = mo.strip().lower()

    # bars=0 (auto) -> 128 作为离线渲染的兜底
    if result["bars"] == 0:
        result["bars"] = 128

    return result


# =============================================================================
# 用户自定义参数
# =============================================================================

CONFIG: dict = {
    # --- 音频文件（通过 --mix / --vocal-file 命令行参数指定） ---
    "mix_file":   "",
    "vocal_file": "",

    # --- 显示 ---
    "win_w":         1600,
    "win_h":         400,
    "background_color": (255, 255, 255),
    "vocal_color":      (240, 225, 45),
    "vocal_only": False,             # True: 只显示人声，不画白色背景
    "latency_offset": 18,            # 帧偏移补偿（FFT 半窗延迟 ~46ms @ 22050Hz/400FPS）

}

# 合并 cava 原生配置（后者覆盖前者同名键）
_CAVA_PARAMS = _read_cava_ini()
CONFIG.update(_CAVA_PARAMS)

CONFIG["bars"] = 300         # 用户指定
CONFIG["sensitivity"] = 150  # 用户指定


# =============================================================================
# 离线预处理
# =============================================================================

def _load_audio(path: str, target_sr: int) -> np.ndarray:
    """加载音频，转为 target_sr Hz 单声道，返回 float32 [-1, 1] 数组。"""
    data, sr = sf.read(path)
    if data.ndim == 2:
        data = data.mean(axis=1)
    if sr != target_sr:
        import librosa
        data = librosa.resample(data, orig_sr=sr, target_sr=target_sr)
    return data.astype(np.float32)


def precompute_bars(
    mix_path: str,
    vocal_path: str,
    config: dict,
) -> tuple[np.ndarray, np.ndarray, list[float], int, int]:
    """
    用两个独立 cavacore 实例分别处理混音和人声。

    与 cava Windows 端行为对齐:
      - 统一采样到 22050 Hz，单声道
      - 输入缩放 = float[-1,1] * 32767（匹配 16-bit PCM 范围）
      - sensitivity 在 cava_execute 输出后乘以 sens，再 clamp [0,1]
    """
    sr = 22050
    print("加载音频...", flush=True)
    mix = _load_audio(mix_path, sr)
    print(f"  混音: {len(mix)} 样本", flush=True)
    vocal = _load_audio(vocal_path, sr)
    print(f"  人声: {len(vocal)} 样本", flush=True)

    min_len = min(len(mix), len(vocal))
    mix = mix[:min_len]
    vocal = vocal[:min_len]
    duration = min_len / sr
    print(f"  时长: {duration:.1f}s, 采样率: {sr} Hz, 单声道", flush=True)

    n_bars = config["bars"]
    noise_red = config["noise_reduction"] / 100.0
    autosens = config["autosens"]
    low_cut = config["lower_cutoff"]
    high_cut = config["higher_cutoff"]

    print(f"  初始化 cavacore (bars={n_bars}, ch=1, autosens={autosens})...", flush=True)
    plan_mix = cava_init(n_bars, sr, 1, autosens, noise_red, low_cut, high_cut)
    plan_vocal = cava_init(n_bars, sr, 1, autosens, noise_red, low_cut, high_cut)

    cut_off_freqs = plan_mix.cut_off_frequencies
    fps = config["framerate"]
    # 总帧数 = 时长 * fps（基于时间，而非基于固定每帧样本数）
    total_frames = int(duration * fps)
    sens = config["sensitivity"] / 100.0

    mix_bars = np.zeros((total_frames, n_bars), dtype=np.float32)
    vocal_bars = np.zeros((total_frames, n_bars), dtype=np.float32)

    print(f"  预处理 {total_frames} 帧 (目标 {fps} FPS)...", flush=True)

    INPUT_SCALE = 32767.0  # 16-bit PCM 范围

    for fi in range(total_frames):
        # 每帧覆盖 1/fps 秒的音频，用时间计算精确的样本起止位置
        t_start = fi / fps
        t_end = (fi + 1) / fps
        start = int(t_start * sr)
        end = int(t_end * sr)
        if end >= min_len:
            end = min_len
            if end <= start:
                end = start + 1
        n_avail = end - start

        mc = np.zeros(n_avail, dtype=np.float64)
        vc = np.zeros(n_avail, dtype=np.float64)
        mc[:n_avail] = mix[start:end] * INPUT_SCALE
        vc[:n_avail] = vocal[start:end] * INPUT_SCALE

        out_mix = cava_execute(plan_mix, mc.tolist())
        out_vocal = cava_execute(plan_vocal, vc.tolist())

        for b in range(n_bars):
            v = out_mix[b] * sens
            mix_bars[fi, b] = 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)
            v = out_vocal[b] * sens
            vocal_bars[fi, b] = 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)

        if (fi + 1) % 500 == 0:
            print(f"    帧 {fi+1}/{total_frames}", flush=True)

    plan_mix.destroy()
    plan_vocal.destroy()
    print("  预处理完成。", flush=True)
    return mix_bars, vocal_bars, cut_off_freqs, total_frames, sr


# =============================================================================
# 实时渲染
# =============================================================================

def render(
    mix_path: str,
    mix_bars: np.ndarray,
    vocal_bars: np.ndarray,
    total_frames: int,
    sr: int,
    config: dict,
):
    """OpenCV 实时渲染 + pygame 音频播放。"""
    win_w = config["win_w"]
    win_h = config["win_h"]
    n_bars = config["bars"]
    bg_color = config["background_color"]
    v_color = config["vocal_color"]
    fps = config["framerate"]
    frame_ms = max(1, int(1000 / fps))
    offset = config.get("latency_offset", 0)

    cv2.namedWindow("CAVA Vocal Overlay", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("CAVA Vocal Overlay", win_w, win_h)

    pygame.mixer.init(frequency=sr)
    pygame.mixer.music.load(mix_path)
    pygame.mixer.music.play()

    print(f"渲染中 (目标 {fps} FPS)...", flush=True)
    t0 = time.time()

    while True:
        elapsed = time.time() - t0
        fi = int(elapsed * fps) + offset
        if fi >= total_frames:
            break

        frame = np.zeros((win_h, win_w, 3), dtype=np.uint8)
        cm = mix_bars[fi]
        cv = vocal_bars[fi]

        for i in range(n_bars):
            x0 = int(i / n_bars * win_w)
            x1 = int((i + 1) / n_bars * win_w)
            if x1 <= x0:
                x1 = x0 + 1

            hm = int(cm[i] * win_h)
            if not config.get("vocal_only", False) and hm > 0:
                cv2.rectangle(frame, (x0, win_h - hm), (x1, win_h), bg_color, -1)

            hv = int(cv[i] * win_h)
            if hv > 0:
                hd = hm if hm > 0 and hm < hv else hv
                if hd > 0:
                    cv2.rectangle(frame, (x0, win_h - hd), (x1, win_h), v_color, -1)

        cv2.imshow("CAVA Vocal Overlay", frame)
        key = cv2.waitKey(frame_ms) & 0xFF
        if key == 27 or cv2.getWindowProperty("CAVA Vocal Overlay", cv2.WND_PROP_VISIBLE) < 1:
            break

    pygame.mixer.music.stop()
    cv2.destroyAllWindows()


# =============================================================================
# 入口
# =============================================================================

if __name__ == "__main__":
    args = _parse_args()
    CONFIG["vocal_only"] = args.vocal
    if args.offset is not None:
        CONFIG["latency_offset"] = args.offset
    if args.mix is not None:
        CONFIG["mix_file"] = args.mix
    if args.vocal_file is not None:
        CONFIG["vocal_file"] = args.vocal_file

    if not CONFIG["mix_file"] or not CONFIG["vocal_file"]:
        print("错误: 请通过 --mix 和 --vocal-file 指定音频文件路径", flush=True)
        sys.exit(1)

    # --- 缓存检查 ---
    key = _cache_key(CONFIG["mix_file"], CONFIG["vocal_file"], CONFIG)
    cache_path = _CACHE_DIR / f"{key}.npz"
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if cache_path.exists():
        print("缓存命中，加载预处理数据...", flush=True)
        data = np.load(cache_path)
        mb = data["mix_bars"]
        vb = data["vocal_bars"]
        freqs = data["cut_off_freqs"].tolist()
        nf = mb.shape[0]
        sr = int(data["sr"])
        data.close()
    else:
        mb, vb, freqs, nf, sr = precompute_bars(
            CONFIG["mix_file"], CONFIG["vocal_file"], CONFIG,
        )
        print("保存缓存...", flush=True)
        np.savez_compressed(
            cache_path,
            mix_bars=mb,
            vocal_bars=vb,
            cut_off_freqs=np.array(freqs, dtype=np.float32),
            sr=sr,
        )

    render(CONFIG["mix_file"], mb, vb, nf, sr, CONFIG)
