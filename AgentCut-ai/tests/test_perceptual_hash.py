"""Offline checks for the versioned, dependency-free pHash algorithm."""

from copy import deepcopy
from random import Random
import re

import pytest

from app.analysis.perceptual_hash import (
    MAX_GRID_DIMENSION,
    PHASH_VERSION,
    hamming_distance,
    perceptual_hash,
)


def _texture(seed: int = 84) -> list[list[int]]:
    random = Random(seed)
    return [[random.randrange(32, 224) for _ in range(64)] for _ in range(64)]


def test_versioned_reference_output_is_deterministic():
    pixels = _texture()
    assert PHASH_VERSION == "agentcut-phash-dct32-area8-v1"
    assert perceptual_hash(pixels) == "05d8e10cfba90bdc"
    assert perceptual_hash(pixels) == perceptual_hash(tuple(tuple(row) for row in pixels))
    assert re.fullmatch(r"[0-9a-f]{16}", perceptual_hash(pixels))
    # The reserved DC bit remains zero regardless of image brightness.
    assert int(perceptual_hash(pixels), 16) < 2 ** 63


@pytest.mark.parametrize("pixels", [
    [[0]],
    [[255]],
    [[96.5] * 3 for _ in range(7)],
    [[128] * 47 for _ in range(19)],
])
def test_uniform_images_have_zero_hash(pixels):
    assert perceptual_hash(pixels) == "0000000000000000"


def test_small_pixel_noise_is_a_near_duplicate():
    pixels = _texture()
    noisy = deepcopy(pixels)
    for row, column in [(0, 0), (9, 11), (20, 31), (36, 14), (63, 63)]:
        noisy[row][column] += 3
    assert noisy != pixels
    assert hamming_distance(perceptual_hash(pixels), perceptual_hash(noisy)) <= 4


def test_brightness_and_positive_contrast_changes_preserve_hash():
    pixels = _texture()
    brighter = [[value + 17 for value in row] for row in pixels]
    lower_contrast = [[value * 0.7 + 20 for value in row] for row in pixels]
    assert perceptual_hash(pixels) == perceptual_hash(brighter)
    assert perceptual_hash(pixels) == perceptual_hash(lower_contrast)


def test_different_textures_have_substantially_different_hashes():
    original = perceptual_hash(_texture(84))
    different = perceptual_hash(_texture(85))
    assert hamming_distance(original, different) >= 20


def test_area_resizing_preserves_replicated_pixels_and_rectangular_inputs():
    pixels = [[20, 80, 160], [220, 50, 110], [140, 210, 40], [10, 90, 180], [60, 30, 200]]
    replicated = [
        [value for value in row for _ in range(4)]
        for row in pixels
        for _ in range(3)
    ]
    assert perceptual_hash(pixels) == perceptual_hash(replicated)
    assert perceptual_hash(pixels) != "0000000000000000"


def test_input_is_not_mutated():
    pixels = _texture()
    before = deepcopy(pixels)
    perceptual_hash(pixels)
    assert pixels == before


@pytest.mark.parametrize("pixels", [
    [],
    [[]],
    [[1], [1, 2]],
    [[1], []],
    [[1], None],
    [1, 2],
    "pixels",
    ["12"],
    [b"12"],
    [[[1]]],
    [[True]],
    [[False]],
    [[None]],
    [["128"]],
    [[complex(1, 0)]],
    [[-1]],
    [[256]],
    [[-0.01]],
    [[255.01]],
    [[float("nan")]],
    [[float("inf")]],
    [[float("-inf")]],
    [[10 ** 1000]],
    None,
    {},
])
def test_invalid_pixel_grids_are_rejected(pixels):
    with pytest.raises(ValueError):
        perceptual_hash(pixels)


def test_iterators_are_rejected_instead_of_being_silently_consumed():
    rows = iter([[0], [255]])
    with pytest.raises(ValueError):
        perceptual_hash(rows)
    assert next(rows) == [0]


@pytest.mark.parametrize("pixels", [
    [[0] * (MAX_GRID_DIMENSION + 1)],
    [[0]] * (MAX_GRID_DIMENSION + 1),
    [[0] * 1024] * 1025,
])
def test_resource_limits_are_enforced_before_hashing(pixels):
    with pytest.raises(ValueError, match="must not exceed"):
        perceptual_hash(pixels)


@pytest.mark.parametrize("left,right,distance", [
    ("0000000000000000", "0000000000000000", 0),
    ("0000000000000000", "ffffffffffffffff", 64),
    ("0000000000000000", "0000000000000001", 1),
    ("aaaaaaaaaaaaaaaa", "0000000000000000", 32),
    ("0123456789abcdef", "fedcba9876543210", 64),
])
def test_hamming_distance_counts_bits_symmetrically(left, right, distance):
    assert hamming_distance(left, right) == distance
    assert hamming_distance(right, left) == distance


@pytest.mark.parametrize("invalid", [
    "",
    "0" * 15,
    "0" * 17,
    "FFFFFFFFFFFFFFFF",
    "000000000000000g",
    "0000000000000000\n",
    " 0000000000000000",
    "0x00000000000000",
    "０" * 16,
    0,
    None,
    True,
    b"0000000000000000",
])
def test_hamming_distance_requires_canonical_hashes_in_both_arguments(invalid):
    valid = "0000000000000000"
    with pytest.raises(ValueError, match="16 lowercase hexadecimal"):
        hamming_distance(invalid, valid)
    with pytest.raises(ValueError, match="16 lowercase hexadecimal"):
        hamming_distance(valid, invalid)
