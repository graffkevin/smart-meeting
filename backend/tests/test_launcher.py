from smart_meeting import launcher


def run_launcher(monkeypatch, health_answers, wait_s):
    opened = []
    answers = iter(health_answers)
    monkeypatch.setattr(launcher, "_health", lambda url: next(answers, {"ui_open": False}))
    monkeypatch.setattr(launcher, "open_window", opened.append)
    monkeypatch.setattr(launcher.time, "sleep", lambda s: None)
    launcher.open_unless_already_open("http://x/", wait_s=wait_s)
    return opened


def test_reuses_an_open_page(monkeypatch):
    assert run_launcher(monkeypatch, [{"ui_open": True}], wait_s=0) == []


def test_waits_for_a_page_reconnecting_after_restart(monkeypatch):
    answers = [{"ui_open": False}, {"ui_open": False}, {"ui_open": True}]
    assert run_launcher(monkeypatch, answers, wait_s=60) == []


def test_opens_a_tab_when_no_page_is_open(monkeypatch):
    assert run_launcher(monkeypatch, [{"ui_open": False}], wait_s=0) == ["http://x/"]
