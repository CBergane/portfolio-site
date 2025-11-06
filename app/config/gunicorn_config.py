"""
Gunicorn configuration (container/prod)
"""
import os
import multiprocessing

# ---- Server socket ----
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")
backlog = int(os.getenv("GUNICORN_BACKLOG", "2048"))

# ---- Workers/threads ----
workers = int(os.getenv("GUNICORN_WORKERS", multiprocessing.cpu_count() * 2 + 1))
worker_class = os.getenv("GUNICORN_WORKER_CLASS", "sync")
threads = int(os.getenv("GUNICORN_THREADS", "4"))  # nytt: hjälper vid I/O-blockering

# ---- Timeouts (lite generösare för att undvika falska timeouts) ----
timeout = int(os.getenv("GUNICORN_TIMEOUT", "90"))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "30"))
keepalive = int(os.getenv("GUNICORN_KEEP_ALIVE", "5"))

# ---- Proxy/forwarded headers ----
# Sätt till "*" eller en kommaseparerad lista med dina HAProxy/Cloudflare-IPn om inte 127.0.0.1 räcker
forwarded_allow_ips = os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1")
# Aktivera bara PROXY-protokoll om din proxy använder "send-proxy"
proxy_protocol = os.getenv("PROXY_PROTOCOL", "false").lower() in ("1", "true", "yes")

# ---- Stabilitet: rotera workers över tid för att mota minnesläckor ----
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "100"))

# ---- Logging ----
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOGLEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# ---- Process naming / mechanics ----
proc_name = os.getenv("GUNICORN_PROC_NAME", "gunicorn_portfolio")
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None  # OBS: inte använd i nyare versioner

# Notera: worker_connections används inte av 'sync'-workern, därför utelämnat.
# Sätt CLI-flaggor eller env för att åsidosätta detta vid behov.
