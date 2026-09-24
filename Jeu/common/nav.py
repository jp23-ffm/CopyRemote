"""
Loader for nav_config.json — drives the main/sub app selectors shown
in the topbar of each view. Same mtime-cache pattern as
inventory/views.py::get_field_labels.
"""
import json
import os
from threading import Lock

_nav_config_cache = None
_nav_config_file_mtime = 0
_cache_lock = Lock()


def get_nav_config():
    global _nav_config_cache, _nav_config_file_mtime

    json_path = os.path.join(os.path.dirname(__file__), 'nav_config.json')

    try:
        current_file_mtime = os.path.getmtime(json_path)
    except OSError:
        return _nav_config_cache

    if _nav_config_cache is not None and current_file_mtime == _nav_config_file_mtime:
        return _nav_config_cache

    with _cache_lock:
        try:
            current_file_mtime = os.path.getmtime(json_path)
        except OSError:
            return _nav_config_cache

        if _nav_config_cache is not None and current_file_mtime == _nav_config_file_mtime:
            return _nav_config_cache

        try:
            with open(json_path, 'r', encoding="utf-8") as f:
                _nav_config_cache = json.load(f)

            _nav_config_file_mtime = current_file_mtime

        except (OSError, json.JSONDecodeError):
            return _nav_config_cache

    return _nav_config_cache


def invalidate_nav_config_cache():
    # Call this when nav_config.json is modified
    global _nav_config_cache, _nav_config_file_mtime
    with _cache_lock:
        _nav_config_cache = None
        _nav_config_file_mtime = 0
