"""WSGI entrypoint for Render's existing `gunicorn app:app` service command."""

from urllib.parse import parse_qs

import runner


_loaded = False


def _ensure_loaded():
    global _loaded
    if not _loaded:
        runner.load_existing_outputs()
        _loaded = True


def _response(start_response, status, body, content_type="text/plain; charset=utf-8", headers=None):
    payload = body.encode("utf-8")
    response_headers = [
        ("Content-Type", content_type),
        ("Content-Length", str(len(payload))),
    ]
    if headers:
        response_headers.extend(headers)
    start_response(status, response_headers)
    return [payload]


def app(environ, start_response):
    """Serve the runner UI without starting runner.py's built-in HTTP server."""
    _ensure_loaded()
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO", "/")

    if method == "GET" and path in {"/healthz", "/api/status"}:
        return _response(start_response, "200 OK", "ok")

    if method == "POST" and path == "/run":
        try:
            length = int(environ.get("CONTENT_LENGTH") or "0")
        except ValueError:
            length = 0
        body = environ["wsgi.input"].read(length).decode("utf-8")
        target = parse_qs(body).get("target", [""])[0]
        try:
            _, message = runner.start_single_day_run(target)
            runner.live["status"] = message
        except Exception as exc:
            runner.live["status"] = f"Could not start run: {exc}"
        return _response(
            start_response,
            "303 See Other",
            "",
            headers=[("Location", "/")],
        )

    if method == "GET":
        return _response(
            start_response,
            "200 OK",
            runner.render_html(),
            content_type="text/html; charset=utf-8",
        )

    return _response(start_response, "404 Not Found", "not found")
