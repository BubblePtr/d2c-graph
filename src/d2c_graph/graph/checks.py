from __future__ import annotations

import re


REACT_ABSOLUTE_PATTERNS = [
    r"position\s*:\s*['\"]absolute['\"]",
    r"className\s*=\s*['\"][^'\"]*\babsolute\b",
    r"`[^`]*\babsolute\b",
]

KMP_ABSOLUTE_PATTERNS = [
    r"absoluteOffset\s*\(",
    r"IntOffset\s*\(",
    r"\.offset\s*\(",
]


def assert_no_absolute_react_layout(source: str) -> None:
    for pattern in REACT_ABSOLUTE_PATTERNS:
        if re.search(pattern, source, flags=re.IGNORECASE | re.MULTILINE):
            raise ValueError("React output still contains absolute layout primitives")


def assert_no_absolute_kmp_layout(source: str) -> None:
    for pattern in KMP_ABSOLUTE_PATTERNS:
        if re.search(pattern, source, flags=re.IGNORECASE | re.MULTILINE):
            raise ValueError("KMP output still contains absolute coordinate primitives")
