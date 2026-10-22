"""Versioned, dependency-free perceptual hashing of grayscale pixel grids.

Algorithm v1 treats input pixels as constant unit squares, resizes to 32 x 32
with separable area averaging, and subtracts the resized image's mean. It then
computes the orthonormal DCT-II's upper-left 8 x 8 coefficients. The DC bit is
always zero; each remaining bit is one when its coefficient exceeds the median
of the 63 AC coefficients. Values within 1e-10 * max(1, largest AC magnitude)
of zero are snapped to zero to remove floating-point noise in symmetric images.
Bits are encoded in row-major frequency order, most significant bit first.

There is no input contrast normalization or random state. Uniform images share
the zero hash, so callers must not treat pHash alone as evidence of semantic
equivalence. PHASH_VERSION must change if any algorithm parameter changes.
"""

from __future__ import annotations

from collections.abc import Sequence
import math
from numbers import Real
import re
from statistics import median


PHASH_VERSION = "agentcut-phash-dct32-area8-v1"
MAX_GRID_DIMENSION = 4096
MAX_GRID_PIXELS = 1_048_576

_RESIZE_SIZE = 32
_HASH_SIZE = 8
_ZERO_TOLERANCE = 1e-10
_HASH_PATTERN = re.compile(r"[0-9a-f]{16}", re.ASCII)
_COSINES = tuple(
    tuple(math.cos(math.pi * (position + 0.5) * frequency / _RESIZE_SIZE)
          for position in range(_RESIZE_SIZE))
    for frequency in range(_HASH_SIZE)
)
_SCALES = tuple(
    math.sqrt((1 if frequency == 0 else 2) / _RESIZE_SIZE)
    for frequency in range(_HASH_SIZE)
)


def _is_sequence(value: object) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _validate_grid(pixels: Sequence[Sequence[int | float]]) -> tuple[int, int]:
    if not _is_sequence(pixels) or len(pixels) == 0:
        raise ValueError("pixels must be a nonempty rectangular sequence")
    height = len(pixels)
    if height > MAX_GRID_DIMENSION:
        raise ValueError(f"pixel grid dimensions must not exceed {MAX_GRID_DIMENSION}")
    if not _is_sequence(pixels[0]) or len(pixels[0]) == 0:
        raise ValueError("pixel rows must be nonempty sequences")
    width = len(pixels[0])
    if width > MAX_GRID_DIMENSION:
        raise ValueError(f"pixel grid dimensions must not exceed {MAX_GRID_DIMENSION}")
    if width * height > MAX_GRID_PIXELS:
        raise ValueError(f"pixel grid must not exceed {MAX_GRID_PIXELS} pixels")
    for row in pixels:
        if not _is_sequence(row) or len(row) != width:
            raise ValueError("pixel grid must be rectangular")
        for pixel in row:
            if isinstance(pixel, bool) or not isinstance(pixel, Real):
                raise ValueError("pixels must be finite real numbers between 0 and 255")
            # Check bounds before float conversion, including arbitrarily large ints.
            if not 0 <= pixel <= 255 or not math.isfinite(float(pixel)):
                raise ValueError("pixels must be finite real numbers between 0 and 255")
    return width, height


def _area_weights(source_size: int) -> tuple[tuple[tuple[int, float], ...], ...]:
    """Return normalized pixel-square overlap weights for each output pixel."""
    scale = source_size / _RESIZE_SIZE
    result = []
    for destination in range(_RESIZE_SIZE):
        start = destination * scale
        end = (destination + 1) * scale
        result.append(tuple(
            (source, (min(end, source + 1) - max(start, source)) / scale)
            for source in range(math.floor(start), math.ceil(end))
        ))
    return tuple(result)


def perceptual_hash(pixels: Sequence[Sequence[int | float]]) -> str:
    """Return a 64-bit pHash as exactly 16 lowercase hexadecimal characters.

    Input must be a nonempty rectangular sequence of finite numeric values in
    [0, 255]. Booleans, strings, ragged grids, dimensions over 4096, and grids
    over 1,048,576 pixels are rejected with ValueError. Inputs are never mutated.
    Larger images should be decoded to a thumbnail before calling this function.
    """
    width, height = _validate_grid(pixels)
    horizontal_weights = _area_weights(width)
    vertical_weights = _area_weights(height)
    horizontal = [
        [math.fsum(float(row[source]) * weight for source, weight in weights)
         for weights in horizontal_weights]
        for row in pixels
    ]
    resized = [
        [math.fsum(horizontal[source][column] * weight for source, weight in weights)
         for column in range(_RESIZE_SIZE)]
        for weights in vertical_weights
    ]
    mean = math.fsum(value for row in resized for value in row) / (_RESIZE_SIZE ** 2)
    # First transform the x axis, retaining only the eight required frequencies.
    transformed_rows = [
        [math.fsum((row[column] - mean) * cosine
                   for column, cosine in enumerate(_COSINES[frequency]))
         * _SCALES[frequency]
         for frequency in range(_HASH_SIZE)]
        for row in resized
    ]
    coefficients = [
        math.fsum(transformed_rows[row][x_frequency] * cosine
                  for row, cosine in enumerate(_COSINES[y_frequency]))
        * _SCALES[y_frequency]
        for y_frequency in range(_HASH_SIZE)
        for x_frequency in range(_HASH_SIZE)
    ]
    epsilon = _ZERO_TOLERANCE * max(1.0, *(abs(value) for value in coefficients[1:]))
    ac = [0.0 if abs(value) <= epsilon else value for value in coefficients[1:]]
    threshold = median(ac)
    result = 0
    for coefficient in ac:
        result = (result << 1) | int(coefficient > threshold)
    return f"{result:016x}"


def hamming_distance(hash_a: str, hash_b: str) -> int:
    """Count differing bits, accepting only canonical 16-character pHash strings."""
    for value in (hash_a, hash_b):
        if not isinstance(value, str) or _HASH_PATTERN.fullmatch(value) is None:
            raise ValueError("pHash must contain exactly 16 lowercase hexadecimal characters")
    return (int(hash_a, 16) ^ int(hash_b, 16)).bit_count()
