# ADR-003: Caddy internal TLS와 원내 경계

상태: 지정 기술 선택 기록, 운영 주소·인증서 배포는 Phase 5 승인 대상.

Caddy `tls internal`로 원내 서버 주소의 인증서를 발급하고 HTTP를 HTTPS로 리다이렉트한다. 기본 공개 CA/ACME 경로로 넘어가지 않게 내부 issuer를 명시한다. 원내 PC에는 공개 root 인증서만 설치한다. [Caddy Automatic HTTPS](https://caddyserver.com/docs/automatic-https)

구성은 app+postgres+caddy 3개 상시 서비스다. app/postgres는 internal 전용 network, Caddy의 외부 목적지 통신도 host firewall로 거부한다. Caddy가 호스트 LAN 포트를 수신하는 bridge를 갖는 경우 internal network만 설정했다고 egress 차단 완료로 보지 않는다. 업데이트·이미지 빌드는 별도 설치 단계다. 외부 DNS·CA·telemetry·CDN·외부 폰트는 runtime에 사용하지 않는다.

80/443만 서버의 업무 LAN IP에 바인딩하고 PostgreSQL·app·Caddy admin API는 LAN에 공개하지 않는다. proxy forwarding header는 정해진 Caddy 주소에서만 신뢰한다. URI chart_no·폼·쿼리는 범용 access log에서 제외하고 서비스 AccessLog로 대체한다.

쿠키 Secure·HttpOnly·SameSite=Strict, CSRF token+Origin 검사, no-store, CSP self 기반을 적용한다. Caddy CA 개인키·백업 복호화 개인키는 용도가 다르며 각각 보호한다. root 설치·지문 대조·인증서 갱신·분실 복구는 운영 검증이 필요하다.

Phase 5 TECH: 실제 proxy HTTP→HTTPS, 브라우저 쿠키·CSRF·egress·ports 검사. OPS: 다른 원내 업무 PC의 신뢰·접속, Windows 방화벽·절전·재부팅 복구. 자동 테스트만으로 OPS를 통과시키지 않는다.
