# gunicorn_config.py
bind = "0.0.0.0:10000"
workers = 1
timeout = 600
graceful_timeout = 300
worker_class = 'sync'
max_requests = 100
max_requests_jitter = 10
loglevel = 'info'
