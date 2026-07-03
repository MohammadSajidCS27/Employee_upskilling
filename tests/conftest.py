import os

# Tests should use PostgreSQL like the application runtime.
os.environ.setdefault("APP_ENV", "test")
