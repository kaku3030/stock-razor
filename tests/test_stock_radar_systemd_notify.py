import socket

import pytest

from src.services.stock_radar_v2.systemd_notify import notify_systemd


def test_notify_systemd_sends_ready_and_watchdog_to_unix_datagram(tmp_path, monkeypatch):
    socket_path = str(tmp_path / "notify.sock")
    receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    receiver.bind(socket_path)
    receiver.settimeout(1)
    monkeypatch.setenv("NOTIFY_SOCKET", socket_path)
    try:
        assert notify_systemd("READY=1", "WATCHDOG=1", "STATUS=ready") is True
        assert receiver.recv(256) == b"READY=1\nWATCHDOG=1\nSTATUS=ready"
    finally:
        receiver.close()


def test_notify_systemd_supports_systemd_abstract_socket(monkeypatch):
    receiver = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    name = "stock-razor-test-notify"
    receiver.bind("\0" + name)
    receiver.settimeout(1)
    monkeypatch.setenv("NOTIFY_SOCKET", "@" + name)
    try:
        assert notify_systemd("WATCHDOG=1") is True
        assert receiver.recv(128) == b"WATCHDOG=1"
    finally:
        receiver.close()


def test_notify_systemd_is_noop_outside_systemd(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    assert notify_systemd("WATCHDOG=1") is False


@pytest.mark.parametrize("field", ["", "WATCHDOG=1\nREADY=1", "BAD\x00FIELD"])
def test_notify_systemd_rejects_invalid_protocol_fields(monkeypatch, field):
    monkeypatch.setenv("NOTIFY_SOCKET", "/tmp/unused-notify.sock")
    with pytest.raises(ValueError):
        notify_systemd(field)
