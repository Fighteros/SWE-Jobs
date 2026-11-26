from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from sources.http_utils import get_public_html


def test_scrapling_public_html_and_access_denial():
    paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            self.send_response(200 if self.path.startswith("/jobs?") else 403)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<p>وظيفة</p>".encode())

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            assert "وظيفة" in get_public_html(base + "/jobs", {"page": 2})
            assert get_public_html(base + "/denied") is None
            assert paths == ["/jobs?page=2", "/denied"]
        finally:
            server.shutdown()
            thread.join()
