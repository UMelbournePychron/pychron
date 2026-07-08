"""Discover which EarthBank DataPackages the account can write into.

Diagnoses the upload failure ``500 Package is not writable by user`` — the
POST to /api/arar/ArArDataPoint has no ``dataPackageId``, so the server picks
an implicit package the account can't write. This lists every package visible
to the credentials, dumps the raw fields (owner / permission flags vary by API
version), and highlights any that look writable so you can grab the id for the
per-profile ``dataPackageId`` preference.

Run directly:
    EARTHBANK_URL=https://app.ausgeochem.org \
    EARTHBANK_USER=alice \
    EARTHBANK_PASS=secret \
    python -m pychron.ausgeochem.tests.packages_probe

Skips if EARTHBANK_USER / EARTHBANK_PASS are unset.
"""

from __future__ import absolute_import, print_function

import json
import os
import sys

from pychron.ausgeochem.earthbank_service import AusGeochemEarthBankService
from pychron.ausgeochem.tests import load_dotenv


# Substrings that, if present in a key and truthy, suggest write access.
_WRITE_HINT_KEYS = ("writable", "canwrite", "canedit", "editable", "owner", "write")


def _looks_writable(row):
    hits = []
    for k, v in (row or {}).items():
        kl = k.lower()
        if any(h in kl for h in _WRITE_HINT_KEYS) and v not in (None, False, "", 0):
            hits.append("{}={!r}".format(k, v))
    return hits


def main():
    load_dotenv()
    user = os.environ.get("EARTHBANK_USER")
    pwd = os.environ.get("EARTHBANK_PASS")
    url = os.environ.get("EARTHBANK_URL", "https://ausgeochem.auscope.org.au")
    if not (user and pwd):
        print("SKIP: set EARTHBANK_USER and EARTHBANK_PASS to run.")
        sys.exit(0)

    svc = AusGeochemEarthBankService(bind=False)
    svc.base_url = url
    svc.username = user
    svc.password = pwd
    # headless: silence GUI-dependent logging hooks
    svc.warning = lambda *a, **k: print("  WARN:", *a)
    svc.info = lambda *a, **k: None
    svc.debug = lambda *a, **k: None

    print("EarthBank data-package probe ({}) user={}".format(url, user))

    # decode the JWT payload to see what authorities the account actually has
    tok = svc._ensure_token()
    if tok:
        try:
            import base64

            pl = tok.split(".")[1]
            pl += "=" * (-len(pl) % 4)
            claims = json.loads(base64.urlsafe_b64decode(pl))
            print("  token auth = {}".format(claims.get("auth")))
            print("  token sub  = {}".format(claims.get("sub")))
        except Exception as exc:
            print("  (could not decode token: {})".format(exc))

    # who am I? account.id turned out NOT to match package.createdById, so dump
    # the whole account to hunt for a person/researcher id in another field.
    account_id = None
    ar = svc._request("get", "/api/account")
    if ar is not None:
        try:
            acct = ar.json()
            account_id = acct.get("id")
            print("\n  full /api/account:")
            print(json.dumps(acct, indent=2, default=str))
        except ValueError:
            print("  /api/account returned non-JSON")

    # fetch DETAIL of the two packages known to be the user's — detail views
    # commonly carry an editors/permissions list the collection view omits.
    for known in os.environ.get(
        "EARTHBANK_KNOWN_PACKAGES", "52610703,32545398"
    ).split(","):
        known = known.strip()
        if not known:
            continue
        dr = svc._request("get", "/api/management/data-packages/{}".format(known))
        print("\n  detail /api/management/data-packages/{} -> {}".format(
            known, getattr(dr, "status_code", "ERR")))
        if dr is not None:
            try:
                print(json.dumps(dr.json(), indent=2, default=str)[:4000])
            except ValueError:
                print("    (non-JSON)")

    # Webui uses host ausgeochem.auscope.org.au and the /api/management/
    # prefix (NOT /api/core/), scoped by celestialId (institution/archive).
    celestial = os.environ.get("EARTHBANK_CELESTIAL_ID")
    base_params = {"page": 0, "size": 200}
    if celestial:
        base_params["celestialId"] = celestial
    candidates = [
        "/api/management/data-packages",
        "/api/management/data-packages/my",
        "/api/core/data-packages",
    ]
    hit_path = None
    for path in candidates:
        r = svc._request("get", path, params=dict(base_params, size=1))
        status = getattr(r, "status_code", "ERR/None")
        print("  probe {:36s} -> {}".format(path, status))
        if r is not None and hit_path is None:
            hit_path = path

    if hit_path is None:
        # last resort: dump the swagger and grep for package endpoints
        for docs in ("/v3/api-docs", "/v2/api-docs", "/api/v2/api-docs"):
            r = svc._request("get", docs)
            if r is None:
                continue
            try:
                spec = r.json()
            except ValueError:
                continue
            paths = [p for p in (spec.get("paths") or {}) if "packag" in p.lower()]
            print("\n{} package-ish paths from {}:".format(len(paths), docs))
            for p in paths:
                print("   ", p)
            break
        print("\nNo working list endpoint auto-found. Pick from paths above.")
        sys.exit(1)

    print("\nUsing endpoint: {}".format(hit_path))
    r = svc._request("get", hit_path, params=base_params)
    try:
        rows = r.json() if r is not None else []
    except ValueError:
        rows = []
    if not rows:
        print(
            "\nNo data packages returned. Either the account has none, the "
            "endpoint differs, or auth failed. If auth is fine, ask the "
            "EarthBank admin (support@lithodat.com) to grant a writable "
            "package."
        )
        sys.exit(1)

    print("\n{} package(s) visible (showing owned/writable-looking):\n".format(len(rows)))
    owned = []
    for row in rows:
        dto = (row or {}).get("dataPackageDTO") or row or {}
        pid = (row or {}).get("id") or dto.get("id")
        name = (row or {}).get("name") or dto.get("name")
        created_by = dto.get("createdById")
        is_mine = account_id is not None and created_by == account_id
        hints = _looks_writable(dto)
        if not (is_mine or hints):
            continue
        tag = "MINE" if is_mine else "WRIT?"
        print(
            "  [{}] id={} createdById={} name={!r}".format(tag, pid, created_by, name)
        )
        if hints:
            print("            -> {}".format(", ".join(hints)))
        owned.append(pid)
    writable = owned

    print("\nFull first row (inspect for the real permission field):")
    print(json.dumps(rows[0], indent=2, default=str))

    if writable:
        print(
            "\nCandidate writable dataPackageId(s): {}".format(writable)
        )
        print(
            "Set the chosen id as the per-profile 'dataPackageId' preference "
            "once wired."
        )
    else:
        print(
            "\nNo row shows an obvious write flag. Confirm the permission "
            "field name from the dump above, or request write access from "
            "the EarthBank admin."
        )


if __name__ == "__main__":
    main()
