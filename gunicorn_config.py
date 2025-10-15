import multiprocessing

# Timeout settings
timeout = 300  # 5 minutes (was 30 seconds by default)
graceful_timeout = 300
keepalive = 5

# Worker settings
workers = 1  # Use 1 worker on free tier to save memory
worker_class = 'sync'
worker_connections = 1000

# Logging
accesslog = '-'
errorlog = '-'
loglevel = 'info'

# Memory optimization
max_requests = 100
max_requests_jitter = 10
preload_app = False
