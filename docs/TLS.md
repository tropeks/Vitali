# TLS / HTTPS Setup

Two supported paths: **certbot (Let's Encrypt)** for servers you own, or **load-balancer TLS termination** for cloud deployments.

---

## How the nginx config is structured

| File | Purpose | Always active? |
|------|---------|----------------|
| `docker/nginx/nginx.conf` | Plain-HTTP `:80` server — the default for local dev and HTTP-only staging | Yes |
| `docker/nginx/ssl.conf` | `:80 → :443` redirect + `:443 ssl` server — operator-enabled | Only when mounted |

The stack boots with **only `nginx.conf`** present. When you mount `ssl.conf`, its `listen 80 default_server` redirect block takes over plain-HTTP traffic while nginx.conf continues to load without error (nginx allows multiple `:80` server blocks; the explicit `default_server` wins).

---

## Option A — Let's Encrypt / certbot (direct TLS in nginx)

### 1. Prerequisites

- A DNS A/AAAA record pointing your domain at the server's public IP.
- Ports 80 and 443 open in the firewall.
- `certbot` installed on the host (`apt install certbot` or equivalent).

### 2. Obtain the certificate

Use the **standalone** plugin (certbot temporarily binds port 80; stop nginx first if it is running):

```bash
# Stop nginx so certbot can bind :80
docker compose stop nginx

certbot certonly --standalone -d your.domain.com

# Certbot writes certs to /etc/letsencrypt/live/your.domain.com/
docker compose start nginx
```

Or, if nginx is already running, use the **webroot** plugin:

```bash
certbot certonly --webroot \
  -w /var/www/certbot \         # must be served by nginx as /.well-known/acme-challenge/
  -d your.domain.com
```

### 3. Mount ssl.conf and the certificate directory

Edit the `nginx` service in your compose file:

```yaml
nginx:
  image: nginx:alpine
  ports:
    - "80:80"
    - "443:443"
  volumes:
    - ./docker/nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    - ./docker/nginx/ssl.conf:/etc/nginx/conf.d/ssl.conf:ro          # add this
    - /etc/letsencrypt/live/your.domain.com:/etc/nginx/ssl:ro        # add this
    - static_files:/app/staticfiles:ro
```

> The path inside the container must be `/etc/nginx/ssl/` — that is what `ssl.conf` expects.
> Let's Encrypt names its files `fullchain.pem` and `privkey.pem`, which matches the config.

### 4. Apply

```bash
docker compose up -d --no-deps nginx
```

### 5. Automatic renewal

certbot installs a systemd timer or cron job that runs `certbot renew` twice a day. After renewal nginx must reload to pick up the new cert:

```bash
# /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
#!/bin/bash
docker compose -f /path/to/docker-compose.yml exec nginx nginx -s reload
```

```bash
chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
```

### 6. Verify

```bash
curl -I https://your.domain.com/health/
# Expect HTTP/2 200 or HTTP/1.1 200

curl -I http://your.domain.com/
# Expect HTTP/1.1 301 Moved Permanently  Location: https://...
```

---

## Option B — TLS termination at a cloud load balancer

Use this when running on AWS (ALB), GCP (HTTPS LB), DigitalOcean (LB), or any managed Kubernetes ingress. The load balancer handles certificates; nginx only sees plain HTTP from the LB.

### What to configure on the load balancer

| Setting | Value |
|---------|-------|
| Frontend listener | HTTPS / 443 |
| Backend target | Host IP + port 80 (the nginx container) |
| Health-check path | `/health/` |
| SSL certificate | Upload or reference a managed cert (ACM, GCP Certificate Manager, etc.) |
| `X-Forwarded-Proto` header | Set to `https` on the LB |

### nginx stays on HTTP only

Do **not** mount `ssl.conf` — the load balancer terminates TLS before traffic reaches nginx. The existing `:80` server in `nginx.conf` already forwards `X-Forwarded-Proto` to Django, so `request.is_secure()` works correctly.

Restrict ingress: allow port 80 from the LB's security group / VPC only; block direct external access to port 80 on the host.

### When to prefer this approach

- Multi-region or auto-scaling deployments
- Managed cert rotation (no certbot cron jobs)
- DDoS mitigation and WAF at the LB layer
- Existing CDN (CloudFront, Cloudflare) fronting the origin

---

## Cipher suite rationale

`ssl.conf` uses the **Mozilla Intermediate** configuration:

- **Protocols**: TLS 1.2 + TLS 1.3 only (drops 1.0/1.1 and SSL)
- **Ciphers**: ECDHE + AES-GCM / ChaCha20; no RC4, no 3DES, no export ciphers
- `ssl_prefer_server_ciphers off` — lets TLS 1.3 clients negotiate freely (server-side cipher ordering is not meaningful for TLS 1.3)
- **HSTS**: `max-age=31536000; includeSubDomains` — enforced from the first HTTPS response. **Do not enable HSTS until you are sure HTTPS is stable**; browsers cache the header for one year.
- Session cache + tickets off — improves performance while keeping forward secrecy intact

Test your configuration after activation:

```
https://www.ssllabs.com/ssltest/
```

---

## Do NOT commit certificates

`/etc/nginx/ssl/` lives only inside the container at runtime. Never add `.pem`, `.key`, `.crt`, or `.pfx` files to the repository. The `.gitignore` should include:

```
*.pem
*.key
*.crt
*.pfx
```

---

## Option C — certbot in docker-compose.prod.yml (automatic renewal)

`docker-compose.prod.yml` ships a `certbot` service that renews every 12h and an
nginx that reloads every 6h to pick up renewed certs. Nginx serves the ACME
HTTP-01 challenge from `/var/www/certbot` on plain `:80` (carved out of the HTTPS
redirect in both `nginx.conf` and `ssl.conf`), so renewals need no downtime.

**One-time initial issuance** (DNS A/AAAA already pointing at the host, ports 80/443 open):

```bash
# 1. Create the webroot the challenge is served from
sudo mkdir -p /var/www/certbot

# 2. Bring up nginx WITHOUT ssl.conf first (so :80 answers the challenge).
#    Temporarily comment the ssl.conf mount + 443 port, then:
GHCR_REPO=tropeks docker compose -f docker-compose.prod.yml --env-file /etc/vitali/secrets.env up -d nginx

# 3. Issue the cert (replace domain + email):
docker run --rm \
  -v /etc/letsencrypt:/etc/letsencrypt \
  -v /var/www/certbot:/var/www/certbot \
  certbot/certbot certonly --webroot -w /var/www/certbot \
  -d clinica.exemplo.com.br --email "$ACME_EMAIL" --agree-tos --no-eff-email

# 4. Set TLS_LIVE_DIR in /etc/vitali/secrets.env:
#    TLS_LIVE_DIR=/etc/letsencrypt/live/clinica.exemplo.com.br
#    Re-enable the ssl.conf mount + 443 port, then bring the full stack up:
GHCR_REPO=tropeks docker compose -f docker-compose.prod.yml --env-file /etc/vitali/secrets.env up -d
```

From here renewal is automatic. Verify with
`docker compose -f docker-compose.prod.yml logs certbot`.

## Alternative — Cloudflare Tunnel (no public ports)

If the host has no public IP / open ports, run a `cloudflared` tunnel pointing at
`http://nginx:80` and let Cloudflare terminate TLS at the edge. In that mode nginx
stays HTTP-only (don't mount `ssl.conf`); set `SECURE_PROXY_SSL_HEADER` so Django
trusts `X-Forwarded-Proto: https`. This is the same pattern used elsewhere in the
homelab and avoids managing certs on the host entirely.
