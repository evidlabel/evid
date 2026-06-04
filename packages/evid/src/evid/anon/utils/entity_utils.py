"""Utility functions for entity processing."""

import re

import numpy as np
from rapidfuzz import fuzz
from rapidfuzz.process import cdist


def strip_titles(name: str) -> str:
    """Strip common titles from the beginning of a name for normalization."""
    titles = [
        r"Dr\.",
        r"Prof\.",
        r"Mr\.",
        r"Mrs\.",
        r"Ms\.",
        r"Ph\.D\.",
        r"M\.D\.",
        r"Ing\.",
        r"Fru",
        r"Hr\.",
        r"Md\.",
        r"Lic\.",
        r"Dr\.",
        r"Prof\.",  # Danish/English common
    ]
    for title in titles:
        name = re.sub(r"^" + title + r"\s*", "", name, flags=re.IGNORECASE)
    return name.strip()


def normalize_name(name: str) -> str:
    """Normalize a name for comparison, stripping titles first."""
    name = strip_titles(name)
    return (
        name.lower()
        .replace("å", "aa")
        .replace("æ", "ae")
        .replace("ø", "oe")
        .replace("-", "")
        .replace("\n", " ")
    )


def normalize_number(number: str) -> str:
    """Normalize a number for comparison."""
    return (
        number.replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
        .replace("+", "")
    )


def is_valid_name(name: str) -> bool:
    """Check if a string is a valid name."""
    words = name.strip().split()
    return (
        1 <= len(words) <= 3
        and all(any(c.isalpha() for c in word) for word in words)
        and not any(
            word.lower() in ["multiline", "phone", "account", "code", "street"]
            for word in words
        )
    )


def is_possible_variant(short_name: str, full_name: str) -> bool:
    """Check if short_name is a possible variant of full_name."""
    short_norm = normalize_name(short_name)
    full_norm = normalize_name(full_name)
    short_parts = short_norm.split()
    full_parts = full_norm.split()
    if len(short_parts) > len(full_parts) or len(short_parts) == 0:
        return False
    j = 0
    for sp in short_parts:
        found = False
        while j < len(full_parts) and not found:
            fp = full_parts[j]
            if sp == fp or (sp.endswith(".") and len(sp) <= 4 and fp.startswith(sp[0])):
                found = True
                j += 1
            else:
                j += 1
        if not found:
            return False
    return True


def find_name_variants(names: list, threshold: float = 85) -> list:
    """Group similar names using vectorized rapidfuzz."""
    if not names:
        return []
    valid_names = [name for name in names if is_valid_name(name)]
    if not valid_names:
        return []
    normalized = [normalize_name(name) for name in valid_names]
    scores = cdist(normalized, normalized, scorer=fuzz.ratio)
    grouped_names = []
    visited = np.zeros(len(valid_names), dtype=bool)
    for i in range(len(valid_names)):
        if visited[i]:
            continue
        variants = [valid_names[i]]
        visited[i] = True
        # Collect all directly similar
        similar = np.where(scores[i] > threshold)[0]
        for j in similar:
            if not visited[j]:
                variants.append(valid_names[j])
                visited[j] = True
        if variants:
            grouped_names.append(variants)
    # Postprocessing: merge short variants into unique matching core groups
    current_groups = [list(g) for g in grouped_names]
    current_groups.sort(key=lambda g: max(len(name) for name in g), reverse=True)
    merges = {}  # target_core: list of small_indices
    for small_idx in range(1, len(current_groups)):
        small_rep = max(current_groups[small_idx], key=len)
        possible_cores = []
        for core_idx in range(small_idx):
            core_rep = max(current_groups[core_idx], key=len)
            if is_possible_variant(small_rep, core_rep):
                possible_cores.append(core_idx)
        if len(possible_cores) == 1:
            target = possible_cores[0]
            if target not in merges:
                merges[target] = []
            merges[target].append(small_idx)
    # Apply merges
    new_groups = []
    indices_to_skip = set()
    for idx in range(len(current_groups)):
        if idx in indices_to_skip:
            continue
        group = current_groups[idx][:]
        if idx in merges:
            for small_idx in merges[idx]:
                group.extend(current_groups[small_idx])
                indices_to_skip.add(small_idx)
        new_groups.append(group)
    return new_groups


def find_number_variants(numbers: list, threshold: float = 80) -> list:
    """Group similar numbers using vectorized rapidfuzz."""
    if not numbers:
        return []
    normalized = [normalize_number(num) for num in numbers]
    scores = cdist(normalized, normalized, scorer=fuzz.ratio)
    grouped_numbers = []
    visited = np.zeros(len(numbers), dtype=bool)
    for i in range(len(numbers)):
        if visited[i]:
            continue
        variants = [numbers[i]]
        visited[i] = True
        similar = np.where(scores[i] > threshold)[0]
        for j in similar:
            if not visited[j]:
                variants.append(numbers[j])
                visited[j] = True
        if variants:
            grouped_numbers.append(variants)
    return grouped_numbers
