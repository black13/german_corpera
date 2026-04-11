"""WSGI entrypoint for Render's existing `gunicorn app:app` service command."""

import os
from html import escape
from urllib.parse import parse_qs

import runner


_loaded = False
_DEFAULT_LAST_DAYS = int(os.environ.get("RENDER_DEFAULT_DAYS", "1"))


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


def _is_truthy(value):
    return str(value).lower() in {"1", "true", "yes", "all"}


def _one_day(query):
    target = (query.get("day") or query.get("kann") or [""])[0].strip()
    if not target:
        return None
    try:
        day_num, _ = runner.resolve_run_target(target)
    except ValueError:
        return None
    return [day for day in runner.live["days"] if int(day.get("day", 0)) == day_num]


def _latest_days(query):
    requested = (query.get("last") or [""])[0].strip()
    try:
        count = int(requested) if requested else _DEFAULT_LAST_DAYS
    except ValueError:
        count = _DEFAULT_LAST_DAYS
    count = max(1, min(count, len(runner.live["days"])))
    return runner.live["days"][-count:]


def _selected_days(query):
    if _is_truthy((query.get("all") or [""])[0]):
        return runner.live["days"]
    one_day = _one_day(query)
    if one_day is not None:
        return one_day
    if "last" in query:
        return _latest_days(query)
    return runner.live["days"][-_DEFAULT_LAST_DAYS:]


def _index_html(all_days, selected_days):
    selected = {int(day.get("day", 0)) for day in selected_days}
    links = []
    for day in all_days:
        day_num = int(day.get("day", 0))
        kann_id = day.get("kann_id", "")
        kann_text = day.get("kann_text", "")
        active = day_num in selected
        style = (
            "display:block;padding:3px 4px;border-radius:4px;"
            f"background:{'#e6f4f1' if active else 'transparent'};"
            f"font-weight:{'700' if active else '400'};"
            "color:#123;text-decoration:none;line-height:1.35;"
        )
        label = f"{day_num}. {kann_id}: {kann_text}"
        links.append(f'<a href="/?day={day_num}" style="{style}">{escape(label)}</a>')
    return (
        '<div class="sidebar-section">'
        '<div class="sidebar-title">Kann Index</div>'
        '<div class="status-text">Showing one conversation at a time. '
        'Use this list to open any saved KB.</div>'
        '<div style="max-height:320px;overflow:auto;margin-top:8px;font-size:.76em">'
        + "".join(links) +
        '</div></div>'
    )


def _render_windowed_html(query_string):
    query = parse_qs(query_string or "")
    all_days = runner.live["days"]
    selected_days = _selected_days(query)
    original_days = runner.live["days"]
    original_status = runner.live["status"]
    original_current = {
        key: runner.live.get(key)
        for key in (
            "current_day",
            "current_kann",
            "current_kann_text",
            "current_kann_focus",
        )
    }
    runner.live["days"] = selected_days
    if selected_days:
        selected = selected_days[-1]
        runner.live["current_day"] = selected.get("day", 0)
        runner.live["current_kann"] = selected.get("kann_id", "")
        runner.live["current_kann_text"] = selected.get("kann_text", "")
        runner.live["current_kann_focus"] = selected.get("kann_focus", {})
    runner.live["status"] = (
        f"{original_status} Showing {len(selected_days)} of {len(all_days)} saved days. "
        "Use the Kann Index or query ?day=175 / ?day=K176."
    )
    try:
        html = runner.render_html()
        return html.replace(
            '<div class="sidebar" id="sidebar">',
            '<div class="sidebar" id="sidebar">' + _index_html(all_days, selected_days),
            1,
        )
    finally:
        runner.live["days"] = original_days
        runner.live["status"] = original_status
        for key, value in original_current.items():
            runner.live[key] = value


def app(environ, start_response):
    """Serve the runner UI without starting runner.py's built-in HTTP server."""
    _ensure_loaded()
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO", "/")

    if method in {"GET", "HEAD"} and path in {"/healthz", "/api/status"}:
        if method == "HEAD":
            return _response(start_response, "200 OK", "")
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

    if method == "HEAD":
        return _response(start_response, "200 OK", "", content_type="text/html; charset=utf-8")

    if method == "GET":
        return _response(
            start_response,
            "200 OK",
            _render_windowed_html(environ.get("QUERY_STRING", "")),
            content_type="text/html; charset=utf-8",
        )

    return _response(start_response, "404 Not Found", "not found")
