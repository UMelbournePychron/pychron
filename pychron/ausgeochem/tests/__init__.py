"""EarthBank test helpers."""

from __future__ import absolute_import

import os


def load_dotenv():
    """Zero-dependency .env loader for local test runs.

    Reads ``pychron/ausgeochem/.env`` (the package dir, one level up from this
    tests package) and sets any KEY=VALUE pairs into os.environ WITHOUT
    overriding values already present in the environment. Lines starting with
    ``#`` and blanks are ignored; surrounding quotes on the value are stripped.
    Silently does nothing if the file is absent.
    """

    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if not os.path.isfile(path):
        return
    with open(path) as fp:
        for line in fp:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
