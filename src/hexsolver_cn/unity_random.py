from __future__ import annotations

import math
import struct
from dataclasses import dataclass


UINT32_MASK = 0xFFFFFFFF
UNITY_VALUE_MASK = 0x7FFFFF
UNITY_SEED_MULTIPLIER = 1_812_433_253


def float32(value: float) -> float:
    """Round a Python float to the IEEE-754 single used by Unity 5.6."""

    return struct.unpack("<f", struct.pack("<f", value))[0]


def float32_bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", float32(value)))[0]


@dataclass(frozen=True)
class UnityRandomState:
    s0: int
    s1: int
    s2: int
    s3: int


class UnityRandom:
    """Bit-compatible core of ``UnityEngine.Random`` from Unity 5.6.3f1.

    The initialization, xorshift transition, integer modulo behavior and
    23-bit inclusive float mapping are all captured from the installed game at
    runtime.  This class deliberately exposes only the operations used by the
    Hexcells Infinite generators.
    """

    def __init__(self, seed: int) -> None:
        self.init_state(seed)

    def init_state(self, seed: int) -> None:
        word = seed & UINT32_MASK
        words = [word]
        for _ in range(3):
            word = (UNITY_SEED_MULTIPLIER * word + 1) & UINT32_MASK
            words.append(word)
        self._state = words

    @property
    def state(self) -> UnityRandomState:
        return UnityRandomState(*self._state)

    def next_uint32(self) -> int:
        s0, s1, s2, s3 = self._state
        temp = (s0 ^ ((s0 << 11) & UINT32_MASK)) & UINT32_MASK
        next_word = (s3 ^ (s3 >> 19) ^ temp ^ (temp >> 8)) & UINT32_MASK
        self._state = [s1, s2, s3, next_word]
        return next_word

    def value(self) -> float:
        numerator = self.next_uint32() & UNITY_VALUE_MASK
        return float32(numerator / UNITY_VALUE_MASK)

    def range_int(self, minimum: int, maximum: int) -> int:
        if maximum <= minimum:
            return minimum
        return minimum + self.next_uint32() % (maximum - minimum)

    def range_float(self, minimum: float, maximum: float) -> float:
        minimum = float32(minimum)
        maximum = float32(maximum)
        delta = float32(maximum - minimum)
        # Unity 5.6's native float Range path uses the complemented 23-bit
        # fraction.  It advances the same xorshift state as ``Random.value``,
        # but maps that word in the opposite direction.  This was verified by
        # reading Random.state before/after the exact LevelGenerator prefix.
        unit = float32(1.0 - self.value())
        return float32(minimum + float32(unit * delta))


def unity_floor_to_int(value: float) -> int:
    return math.floor(float32(value))


def unity_round_to_int(value: float) -> int:
    return round(float32(value))
