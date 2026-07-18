from tools.configure_network import _valid_host


def test_valid_host_accepts_lan_bindings_and_hostnames():
    assert _valid_host("0.0.0.0")
    assert _valid_host("192.168.1.20")
    assert _valid_host("[::]")
    assert _valid_host("nas-box.home")
    assert _valid_host("localhost")


def test_valid_host_rejects_invalid_hostname_labels():
    assert not _valid_host("-nas.home")
    assert not _valid_host("nas-.home")
    assert not _valid_host("nas..home")
    assert not _valid_host("nas home")
    assert not _valid_host("a" * 64 + ".home")
