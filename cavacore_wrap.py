"""
cavacore_wrap.py — ctypes wrapper for cavacore shared library

Provides the same cava_init / cava_execute / cava_destroy API
plus safe getter functions for reading the plan struct.

Algorithm is EXACTLY cavacore.c — no modifications.
"""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path
from typing import List

# ---------------------------------------------------------------------------
# Load shared library (cross-platform)
# ---------------------------------------------------------------------------
_dll_dir = Path(__file__).resolve().parent

if sys.platform == "win32":
    # Windows: need fftw3.dll on PATH for cavacore.dll to find it
    os.environ.setdefault("PATH", "")
    os.environ["PATH"] = str(_dll_dir) + os.pathsep + os.environ["PATH"]
    _lib_name = "cavacore.dll"
else:
    # Linux/macOS: FFTW3 resolved via ld.so.cache / dyld
    _lib_name = "libcavacore.so"

_lib = ctypes.CDLL(str(_dll_dir / _lib_name))

# ---------------------------------------------------------------------------
# ctypes types
# ---------------------------------------------------------------------------
c_plan_p = ctypes.c_void_p  # opaque pointer
c_double_p = ctypes.POINTER(ctypes.c_double)
c_float_p = ctypes.POINTER(ctypes.c_float)
c_int_p = ctypes.POINTER(ctypes.c_int)
c_char_p = ctypes.c_char_p

# ---------------------------------------------------------------------------
# cava_init
# ---------------------------------------------------------------------------
_lib.cava_init.argtypes = [
    ctypes.c_int,    # number_of_bars
    ctypes.c_uint,   # rate
    ctypes.c_int,    # channels
    ctypes.c_int,    # autosens
    ctypes.c_double, # noise_reduction
    ctypes.c_int,    # low_cut_off
    ctypes.c_int,    # high_cut_off
]
_lib.cava_init.restype = c_plan_p

# ---------------------------------------------------------------------------
# cava_execute
# ---------------------------------------------------------------------------
_lib.cava_execute.argtypes = [
    c_double_p,   # cava_in
    ctypes.c_int, # new_samples
    c_double_p,   # cava_out
    c_plan_p,     # plan
]
_lib.cava_execute.restype = None

# ---------------------------------------------------------------------------
# cava_destroy
# ---------------------------------------------------------------------------
_lib.cava_destroy.argtypes = [c_plan_p]
_lib.cava_destroy.restype = None

# ---------------------------------------------------------------------------
# Getter functions for cava_plan fields
# ---------------------------------------------------------------------------
_lib.cavacore_get_number_of_bars.argtypes = [c_plan_p]
_lib.cavacore_get_number_of_bars.restype = ctypes.c_int

_lib.cavacore_get_audio_channels.argtypes = [c_plan_p]
_lib.cavacore_get_audio_channels.restype = ctypes.c_int

_lib.cavacore_get_status.argtypes = [c_plan_p]
_lib.cavacore_get_status.restype = ctypes.c_int

_lib.cavacore_get_error.argtypes = [c_plan_p]
_lib.cavacore_get_error.restype = c_char_p

_lib.cavacore_get_cut_off_frequency.argtypes = [c_plan_p, ctypes.c_int]
_lib.cavacore_get_cut_off_frequency.restype = ctypes.c_float

_lib.cavacore_get_bass_cut_off_bar.argtypes = [c_plan_p]
_lib.cavacore_get_bass_cut_off_bar.restype = ctypes.c_int

_lib.cavacore_get_input_buffer_size.argtypes = [c_plan_p]
_lib.cavacore_get_input_buffer_size.restype = ctypes.c_int

_lib.cavacore_get_rate.argtypes = [c_plan_p]
_lib.cavacore_get_rate.restype = ctypes.c_int

# ---------------------------------------------------------------------------
# Python-level wrapper
# ---------------------------------------------------------------------------

class CavaPlan:
    """Python-side handle to a cava_plan instance."""

    def __init__(self, ptr: ctypes.c_void_p):
        self._ptr = ptr
        # Cache immutable fields
        self.number_of_bars: int = _lib.cavacore_get_number_of_bars(ptr)
        self.audio_channels: int = _lib.cavacore_get_audio_channels(ptr)
        self.bass_cut_off_bar: int = _lib.cavacore_get_bass_cut_off_bar(ptr)
        self.input_buffer_size: int = _lib.cavacore_get_input_buffer_size(ptr)
        self.rate: int = _lib.cavacore_get_rate(ptr)

        # Cut-off frequencies (Hz) for each bar, length = number_of_bars + 1
        self.cut_off_frequencies: List[float] = [
            _lib.cavacore_get_cut_off_frequency(ptr, i)
            for i in range(self.number_of_bars + 1)
        ]

    def destroy(self) -> None:
        _lib.cava_destroy(self._ptr)
        self._ptr = None


def cava_init(
    number_of_bars: int,
    rate: int,
    channels: int,
    autosens: int,
    noise_reduction: float,
    low_cut_off: int,
    high_cut_off: int,
) -> CavaPlan:
    """Initialize a cavacore instance. Returns a CavaPlan handle.

    Raises RuntimeError if initialization fails.
    """
    ptr = _lib.cava_init(
        ctypes.c_int(number_of_bars),
        ctypes.c_uint(rate),
        ctypes.c_int(channels),
        ctypes.c_int(autosens),
        ctypes.c_double(noise_reduction),
        ctypes.c_int(low_cut_off),
        ctypes.c_int(high_cut_off),
    )
    if not ptr:
        raise RuntimeError("cava_init returned NULL")
    plan = CavaPlan(ptr)
    status = _lib.cavacore_get_status(ptr)
    if status != 0:
        err = _lib.cavacore_get_error(ptr)
        if isinstance(err, bytes):
            err = err.decode("utf-8", errors="replace")
        plan.destroy()
        raise RuntimeError(f"cava_init failed: {err}")
    return plan


def cava_execute(plan: CavaPlan, cava_in: List[float]) -> List[float]:
    """Execute visualization on the input samples.

    Args:
        plan: CavaPlan handle from cava_init.
        cava_in: List of audio samples (interleaved if stereo).

    Returns:
        List[float] of length number_of_bars * audio_channels.
        Values are in [0, 1] when autosens=1; raw when autosens=0.
    """
    n_bars = plan.number_of_bars
    n_ch = plan.audio_channels
    n_samples = len(cava_in)

    # Allocate input buffer
    in_arr = (ctypes.c_double * n_samples)(*cava_in)
    # Allocate output buffer
    out_arr = (ctypes.c_double * (n_bars * n_ch))()

    _lib.cava_execute(in_arr, n_samples, out_arr, plan._ptr)

    return [out_arr[i] for i in range(n_bars * n_ch)]


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import math

    print("=== cavacore wrapper self-test ===")

    # Parameters matching user config
    N_BARS = 32
    RATE = 22050
    CHANNELS = 1
    AUTOSENS = 0
    NOISE_REDUCTION = 0.0
    LOW_CUT = 50
    HIGH_CUT = 10000

    plan = cava_init(N_BARS, RATE, CHANNELS, AUTOSENS, NOISE_REDUCTION, LOW_CUT, HIGH_CUT)
    print(f"Bars: {plan.number_of_bars}, Channels: {plan.audio_channels}")
    print(f"Rate: {plan.rate}, Input buf size: {plan.input_buffer_size}")
    print(f"Cut-off frequencies (Hz): {[f'{f:.0f}' for f in plan.cut_off_frequencies]}")

    # Generate a test sine wave at 440 Hz
    buf_size = plan.input_buffer_size
    samples = [
        math.sin(2 * math.pi * 440 / RATE * i) * 20000
        for i in range(buf_size // 4)
    ]
    out = cava_execute(plan, samples)
    print(f"Output ({len(out)} values): {[f'{v:.4f}' for v in out[:8]]}...")

    plan.destroy()
    print("=== Self-test passed ===")
