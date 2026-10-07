import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """No test reads or writes the real data folder (meetings, measured AI speeds…)."""
    monkeypatch.setenv("SM_DATA_DIR", str(tmp_path / "data"))
