"""
storage.py
----------
Very small disk-backed "session" store. PythonAnywhere free tier is plain
WSGI with no shared memory between workers/requests worth relying on, so
each conversion run gets its own folder on disk, keyed by a random token.
Old folders are swept on every request.
"""

import json
import os
import shutil
import time
import uuid

import pandas as pd

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sessions")
MAX_AGE_SECONDS = 2 * 60 * 60  # 2 hours


def _ensure_base():
    os.makedirs(BASE_DIR, exist_ok=True)


def new_token():
    _ensure_base()
    token = uuid.uuid4().hex
    os.makedirs(os.path.join(BASE_DIR, token), exist_ok=True)
    return token


def _path(token, name):
    return os.path.join(BASE_DIR, token, name)


def save_df(token, name, df):
    df.to_pickle(_path(token, f"{name}.pkl"))


def load_df(token, name):
    path = _path(token, f"{name}.pkl")
    if not os.path.exists(path):
        return None
    return pd.read_pickle(path)


def save_bytes(token, name, data):
    with open(_path(token, name), "wb") as f:
        f.write(data)


def load_bytes(token, name):
    path = _path(token, name)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def save_meta(token, meta):
    with open(_path(token, "meta.json"), "w") as f:
        json.dump(meta, f)


def load_meta(token):
    path = _path(token, "meta.json")
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def session_exists(token):
    return os.path.isdir(os.path.join(BASE_DIR, token))


def cleanup_old_sessions(max_age_seconds=MAX_AGE_SECONDS):
    _ensure_base()
    now = time.time()
    for name in os.listdir(BASE_DIR):
        folder = os.path.join(BASE_DIR, name)
        if not os.path.isdir(folder):
            continue
        try:
            age = now - os.path.getmtime(folder)
            if age > max_age_seconds:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass
