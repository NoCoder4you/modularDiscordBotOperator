# Single-host portal deployment

Production topology is `browser -> HTTPS Caddy -> 127.0.0.1:8000 portal -> Stage 9 application`.
Run one portal worker as a dedicated account and bind Uvicorn only to loopback:

```console
uvicorn portal.app:app --host 127.0.0.1 --port 8000 --workers 1
```

An illustrative, repository-only Caddy template is in `deploy/Caddyfile.example`. Configure a real
hostname and certificates outside this repository. HTTPS and `Secure`, `HttpOnly`, `SameSite=Strict`
cookies are mandatory in production; disabling `Secure` is development-only. The application is
authoritative for CSP and browser security headers, so the proxy must not replace them.

The application does not derive identity or authorization from forwarded headers. The example proxy
replaces client forwarding values at the loopback boundary. Never expose port 8000 or trust arbitrary
internet `Forwarded`, `X-Forwarded-*`, or `X-Real-IP` values. No live proxy, systemd, firewall, DNS,
account, or process is changed by this template.
