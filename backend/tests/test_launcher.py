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


def test_a_second_server_cannot_bind_the_port():
    first = launcher.bind_port(0)
    port = first.getsockname()[1]
    first.listen()
    try:
        assert launcher.bind_port(port) is None
    finally:
        first.close()


def test_replaces_a_frozen_server(monkeypatch, tmp_path):
    from smart_meeting.config import Settings

    monkeypatch.setattr(launcher, "get_settings", lambda: Settings(data_dir=tmp_path))
    launcher.pid_path(tmp_path).write_text("4242")
    killed = []
    binds = iter([None, "socket"])  # port held until the frozen server is killed
    monkeypatch.setattr(launcher, "_port_owner", lambda url: None)
    monkeypatch.setattr(launcher, "bind_port", lambda port: next(binds, "socket"))
    monkeypatch.setattr(launcher, "STALL_S", -5)  # no waiting
    monkeypatch.setattr(launcher, "_is_our_server", lambda pid: True)
    monkeypatch.setattr(launcher.os, "kill", lambda pid, sig: killed.append(pid))
    assert launcher.replace_frozen_server("http://x/", 1) == "socket"
    assert killed == [4242]
    assert not launcher.pid_path(tmp_path).exists()


def test_the_starting_page_goes_to_the_app_once_it_answers(monkeypatch, tmp_path):
    from smart_meeting.config import Settings

    monkeypatch.setattr(launcher, "get_settings", lambda: Settings(data_dir=tmp_path))
    monkeypatch.setattr(launcher, "tr", lambda key: f"<{key}>")
    page = launcher.write_starting_page("http://127.0.0.1:8417/", tmp_path / "data").read_text()
    assert "const app = 'http://127.0.0.1:8417/';" in page
    assert "&lt;starting_title&gt;" in page  # texts are escaped
    assert "$" not in page.split("<script>")[0]  # every placeholder filled
