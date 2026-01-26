# Christian Bergane - Cybersecurity Portfolio

Modern portfolio site showcasing my cybersecurity work, CTF write-ups, and projects.

**Tech Stack:** Django, Wagtail CMS, PostgreSQL, Podman, Cloudflare Tunnel

**Live Site:** https://cbergane.se

## Features
- 🏗️ Infrastructure as Code (Docker/Podman)
- 🔐 Security-first architecture
- 📝 Dynamic blog & project showcase
- 🚀 Zero-downtime deployments

## Cloudflare / HTTPS Enforcement
- Configure Cloudflare (or upstream proxy) to issue a strict HTTP→HTTPS redirect using status **308** so POST requests, like the contact form, are never downgraded or retried over HTTP.
- Verification: open the browser devtools Network tab and submit `/contact/`; every request (page load + `/api/contact-submit`) must show `https://` in the scheme and no traffic to port 80.

## Hack The Box widget
The HTB card is rendered server-side and cached. Configure these env vars (and set the manual fallback values in Wagtail settings):
- `HTB_TOKEN` — Hack The Box API token
- `HTB_USER_ID` — your HTB user ID
- `HTB_CACHE_TTL_SECONDS` — optional cache TTL (default 21600)

## Local Development
See [INSTALL.md](INSTALL.md) for setup instructions.

---
Built with ❤️ for the infosec community
