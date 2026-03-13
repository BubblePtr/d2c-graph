from __future__ import annotations

import pytest

from d2c_graph.graph.checks import assert_no_absolute_kmp_layout, assert_no_absolute_react_layout


def test_react_absolute_check():
    with pytest.raises(ValueError):
        assert_no_absolute_react_layout('return <div className="absolute inset-0" />;')


def test_kmp_absolute_check():
    with pytest.raises(ValueError):
        assert_no_absolute_kmp_layout("Modifier.absoluteOffset(x = 1.dp, y = 1.dp)")
