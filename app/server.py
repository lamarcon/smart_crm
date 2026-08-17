"""Dependency-free HTTP server for the Smart CRM local prototype."""

from __future__ import annotations

import argparse
import json
import logging
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from typing import Callable


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
LOG = logging.getLogger("smart-crm-demo")


class DemoRequestHandler(SimpleHTTPRequestHandler):
    """Serve local assets and expose a small health endpoint."""

    server_version = "SmartCRMDemo/1.0"

    def do_GET(self) -> None:  # noqa: N802 - inherited HTTP method name
        parsed = urllib.parse.urlsplit(self.path)
        decoded_parts = PurePosixPath(urllib.parse.unquote(parsed.path)).parts
        if ".." in decoded_parts:
            self.send_error(HTTPStatus.FORBIDDEN, "Path traversal rejected")
            return

        if parsed.path == "/health":
            payload = json.dumps(
                {"status": "ok", "service": "smart-crm-demo"}
            ).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return

        super().do_GET()

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self' 'unsafe-inline'")
        super().end_headers()

    def log_message(self, message: str, *args: object) -> None:
        LOG.info("%s - %s", self.address_string(), message % args)


def handler_factory(static_dir: Path) -> Callable[..., DemoRequestHandler]:
    """Bind the standard handler to a specific static directory."""

    resolved = static_dir.resolve()

    def create_handler(*args: object, **kwargs: object) -> DemoRequestHandler:
        return DemoRequestHandler(*args, directory=str(resolved), **kwargs)

    return create_handler


def create_server(
    host: str = "0.0.0.0", port: int = 8000, static_dir: Path = STATIC_DIR
) -> ThreadingHTTPServer:
    """Create the demo server; split out so the same wiring is self-tested."""

    return ThreadingHTTPServer((host, port), handler_factory(static_dir))


def run_self_test() -> int:
    """Exercise health, static delivery and traversal rejection over real HTTP."""

    with tempfile.TemporaryDirectory(prefix="smart-crm-demo-") as temp:
        static_dir = Path(temp)
        (static_dir / "index.html").write_text(
            "<!doctype html><title>Smart CRM test</title>", encoding="utf-8"
        )
        server = create_server("127.0.0.1", 0, static_dir)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"

        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=2) as response:
                health = json.load(response)
                assert response.status == HTTPStatus.OK
                assert health == {"status": "ok", "service": "smart-crm-demo"}

            with urllib.request.urlopen(f"{base_url}/", timeout=2) as response:
                body = response.read().decode("utf-8")
                assert response.status == HTTPStatus.OK
                assert "Smart CRM test" in body

            try:
                urllib.request.urlopen(f"{base_url}/%2e%2e/secret", timeout=2)
            except urllib.error.HTTPError as error:
                assert error.code == HTTPStatus.FORBIDDEN
            else:
                raise AssertionError("Traversal request was not rejected")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    print("server self-test: ok")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=8000, type=int)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.self_test:
        return run_self_test()

    server = create_server(args.host, args.port)
    LOG.info("Smart CRM demo disponível em http://%s:%s", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOG.info("Encerrando Smart CRM demo")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
