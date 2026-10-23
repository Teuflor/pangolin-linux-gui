import pytest

from pangolin_gui import service


@pytest.fixture(autouse=True)
def no_system_service(monkeypatch):
    """Tests must not depend on (or start) a system service installed on the machine."""
    monkeypatch.setattr(service, "installed", lambda: False)
