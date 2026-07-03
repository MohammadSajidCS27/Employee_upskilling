import uvicorn
import socket
from http.client import HTTPConnection
from src.main import app
from src.logging_config import setup_logging
from src.config import settings


def _is_port_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _is_existing_api_healthy(host: str, port: int) -> bool:
    try:
        conn = HTTPConnection(host, port, timeout=1.0)
        conn.request("GET", "/health")
        response = conn.getresponse()
        return 200 <= int(response.status) < 500
    except Exception:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass

if __name__ == "__main__":
    setup_logging()
    if _is_port_open(settings.api_host, settings.api_port):
        if _is_existing_api_healthy(settings.api_host, settings.api_port):
            print(f"API already running at http://{settings.api_host}:{settings.api_port}; skipping duplicate startup.")
            raise SystemExit(0)
        print(
            f"Port {settings.api_port} is already in use on {settings.api_host}. "
            "Stop the process using that port or set API_PORT to a free value."
        )
        raise SystemExit(1)
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        workers=max(1, settings.api_workers),
        proxy_headers=True,
        server_header=False,
    )