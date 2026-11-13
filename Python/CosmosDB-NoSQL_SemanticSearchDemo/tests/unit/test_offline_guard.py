import asyncio
import socket

import pytest


def test_runtime_socketpair_and_event_loop_are_allowed():
    left, right = socket.socketpair()
    try:
        left.sendall(b"x")
        assert right.recv(1) == b"x"
    finally:
        left.close()
        right.close()
    loop = asyncio.new_event_loop()
    loop.close()


@pytest.mark.parametrize("method", ["connect", "connect_ex"])
def test_external_tcp_is_blocked_before_connection(method):
    with socket.socket() as connection:
        with pytest.raises(AssertionError, match="Offline test attempted"):
            getattr(connection, method)(("203.0.113.1", 443))


def test_external_udp_is_blocked_before_send():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        with pytest.raises(AssertionError, match="Offline test attempted"):
            connection.sendto(b"must-not-leave-host", ("203.0.113.1", 53))


def test_external_dns_is_blocked():
    with pytest.raises(AssertionError, match="Offline test attempted"):
        socket.getaddrinfo("example.com", 443)
