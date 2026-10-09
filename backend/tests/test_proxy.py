from smart_meeting import proxy

SCUTIL = """<dictionary> {
  HTTPEnable : 0
  ProxyAutoConfigEnable : 1
  ProxyAutoConfigURLString : http://wpad.example.org/proxy.pac
}"""

PAC = """function FindProxyForURL(url, host) {
  if (isPlainHostName(host) || dnsDomainIs(host, ".example.org")) return "DIRECT";
  return "PROXY proxy.example.org:3128; DIRECT";
}"""


def test_the_pac_url_of_macos_settings():
    assert proxy.pac_url_from_scutil(SCUTIL) == "http://wpad.example.org/proxy.pac"
    assert proxy.pac_url_from_scutil(SCUTIL.replace("Enable : 1", "Enable : 0")) is None
    discovery = "<dictionary> {\n  ProxyAutoDiscoveryEnable : 1\n}"
    assert proxy.pac_url_from_scutil(discovery) == "http://wpad/wpad.dat"


def test_the_proxy_a_pac_script_gives_outside():
    assert proxy.proxy_from_pac(PAC) == "http://proxy.example.org:3128"
    assert proxy.proxy_from_pac('function FindProxyForURL(u, h) { return "DIRECT"; }') is None


def test_a_proxy_from_the_environment_wins(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://terminal:3128")
    monkeypatch.setattr(proxy, "_manual_proxy", lambda: "http://system:3128")
    assert proxy.apply_system_proxy() is None


def test_the_system_proxy_is_used_but_never_for_this_computer(monkeypatch):
    for name in proxy.ENV_NAMES + ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(proxy, "_manual_proxy", lambda: None)
    monkeypatch.setattr(proxy, "_pac_proxy", lambda: "http://proxy.example.org:3128")
    assert proxy.apply_system_proxy() == "http://proxy.example.org:3128"
    import os

    assert os.environ["HTTPS_PROXY"] == "http://proxy.example.org:3128"
    assert "127.0.0.1" in os.environ["NO_PROXY"]
