"""업무 PC 접속 대역 제한(고시 제6조①1호)의 주소 판정. DB 모드 연결 시험은 test_auth_access_log.py에 있다."""

from __future__ import annotations

from ipaddress import ip_network

import pytest

from app.kernel.network import NetworkPolicy


POLICY = NetworkPolicy(allowed=(ip_network("192.168.0.0/24"), ip_network("127.0.0.0/8")),
                       trusted_proxies=(ip_network("10.9.0.2/32"),))


@pytest.mark.parametrize(("address", "allowed"), [
    ("192.168.0.20", True), ("127.0.0.1", True), ("192.168.1.20", False), ("10.0.0.5", False),
    ("testclient", False), ("", False), ("unknown", False),
])
def test_only_listed_networks_are_allowed(address, allowed):
    assert POLICY.allows(address) is allowed


def test_forwarded_header_from_untrusted_peer_is_ignored():
    # 외부 PC가 헤더로 원내 주소를 사칭해도 실제 접속 주소로 판정한다.
    assert POLICY.client_ip("10.0.0.5", "192.168.0.20") == "10.0.0.5"


def test_trusted_proxy_uses_rightmost_untrusted_hop():
    assert POLICY.client_ip("10.9.0.2", "8.8.8.8, 192.168.0.20") == "192.168.0.20"
    assert POLICY.client_ip("10.9.0.2", None) == "10.9.0.2"


def test_default_config_keeps_server_pc_and_rejects_internet():
    policy = NetworkPolicy.load()
    assert policy.allows("127.0.0.1") and policy.allows("::1")
    assert not policy.allows("8.8.8.8")
    assert policy.trusted_proxies == ()
