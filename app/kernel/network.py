"""업무 PC 접속 대역 제한. 업무 모듈을 알지 못하며 config/security.yaml의 network 값을 따른다.

「개인정보의 안전성 확보조치 기준」 제6조①: 접속 권한을 IP 주소 등으로 제한하고(1호),
접속한 IP 주소를 분석해 유출 시도를 탐지한다(2호). 거부는 접속기록(DENIED)에 남긴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network
from pathlib import Path

import yaml


DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config" / "security.yaml"
type Network = IPv4Network | IPv6Network


def _contains(networks: tuple[Network, ...], address: str) -> bool:
    try:
        parsed = ip_address(address)
    except ValueError:
        return False
    return any(parsed in network for network in networks)


@dataclass(frozen=True)
class NetworkPolicy:
    allowed: tuple[Network, ...]
    trusted_proxies: tuple[Network, ...] = ()

    @classmethod
    def load(cls, path: Path | None = None) -> NetworkPolicy:
        with open(path or DEFAULT_CONFIG, encoding="utf-8") as source:
            raw = yaml.safe_load(source)["network"]
        return cls(tuple(ip_network(value) for value in raw["allowed_client_cidrs"]),
                   tuple(ip_network(value) for value in raw["trusted_proxy_cidrs"]))

    def client_ip(self, peer: str, forwarded_for: str | None) -> str:
        """신뢰하는 프록시(Caddy 등)를 거친 경우에만 X-Forwarded-For를 오른쪽부터 읽는다."""
        if not forwarded_for or not _contains(self.trusted_proxies, peer):
            return peer
        for hop in reversed([part.strip() for part in forwarded_for.split(",")]):
            if not _contains(self.trusted_proxies, hop):
                return hop
        return peer

    def allows(self, address: str) -> bool:
        # 해석할 수 없는 주소는 허용하지 않는다(실패 시 닫힘).
        return _contains(self.allowed, address)
