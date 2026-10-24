"""Command line of pangolin-gui: tray only by default, --show opens the status window."""
import sys
import types

import pytest

from pangolin_gui import __main__ as entry


@pytest.fixture
def started(monkeypatch):
    seen = {}

    class FakeApp:
        def __init__(self, start_hidden=False):
            seen["start_hidden"] = start_hidden

        def run(self, argv):
            return 0

    monkeypatch.setitem(sys.modules, "pangolin_gui.app", types.SimpleNamespace(PangolinApp=FakeApp))
    return seen


@pytest.mark.parametrize("argv, hidden", [
    ([], True),                # default: tray only
    (["--hidden"], True),      # old autostart entries keep working
    (["--show"], False),
])
def test_start_mode(started, argv, hidden):
    assert entry.main(argv) == 0
    assert started["start_hidden"] is hidden
