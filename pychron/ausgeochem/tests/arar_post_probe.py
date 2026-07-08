"""Find how /api/arar/ArArDataPoint accepts its DataPackage.

create_sample works when dataPackageId is in the sample-with-locations
wrapper, but /api/arar/ArArDataPoint still 500s "Package is not writable by
user" with dataPackageId in the body. This probe tries several placements to
discover the one the server honours. Reuses/creates a sample in the writable
package first, then attempts each variant and prints the status.

    python -m pychron.ausgeochem.tests.arar_post_probe
"""

from __future__ import absolute_import

import json
import os
import sys
import time

from pychron.ausgeochem.earthbank_service import AusGeochemEarthBankService
from pychron.ausgeochem.tests import load_dotenv


def _svc():
    load_dotenv()
    user = os.environ.get("EARTHBANK_USER")
    pwd = os.environ.get("EARTHBANK_PASS")
    url = os.environ.get("EARTHBANK_URL", "https://ausgeochem.auscope.org.au")
    pkg = os.environ.get("EARTHBANK_DATA_PACKAGE_ID")
    if not (user and pwd and pkg):
        print("SKIP: need EARTHBANK_USER, EARTHBANK_PASS, EARTHBANK_DATA_PACKAGE_ID")
        sys.exit(0)
    svc = AusGeochemEarthBankService(bind=False)
    svc.base_url = url
    svc.username = user
    svc.password = pwd
    svc.warning = lambda *a, **k: None
    svc.info = lambda *a, **k: None
    svc.debug = lambda *a, **k: None
    return svc, int(pkg)


def _post(svc, path, body=None, params=None):
    """Raw POST that returns (status_code, short_text) without raising."""
    token = svc._ensure_token()
    url = svc._url(path)
    headers = {
        "Authorization": "Bearer {}".format(token),
        "Content-Type": "application/json",
    }
    try:
        resp = svc._session.post(
            url, json=body, params=params, headers=headers, timeout=30
        )
    except Exception as exc:
        return None, str(exc)
    txt = resp.text or ""
    return resp.status_code, txt[:300]


def main():
    svc, pkg = _svc()
    print("arar POST probe url={} pkg={}".format(svc.base_url, pkg))

    # base ArArDataPoint DTO (minimal, resolved)
    dto = svc.resolve_lookups(
        {
            "analysisDate": "2026-05-20",
            "analysisScaleName": "Single Grain",
            "arMethodName": "Step-heating - laser",
            "analysisUnits": "fA",
            "mineralName": "sanidine",
        }
    )

    variants = [
        ("body dataPackageId (int)", "/api/arar/ArArDataPoint",
         dict(dto, dataPackageId=pkg), None),
        ("body dataPackageId (str)", "/api/arar/ArArDataPoint",
         dict(dto, dataPackageId=str(pkg)), None),
        ("query ?dataPackageId", "/api/arar/ArArDataPoint",
         dto, {"dataPackageId": pkg}),
        ("query ?packageId", "/api/arar/ArArDataPoint",
         dto, {"packageId": pkg}),
        ("body packageId", "/api/arar/ArArDataPoint",
         dict(dto, packageId=pkg), None),
        ("body dataPackage.id nested", "/api/arar/ArArDataPoint",
         dict(dto, dataPackage={"id": pkg}), None),
    ]

    for label, path, body, params in variants:
        code, txt = _post(svc, path, body=body, params=params)
        ok = code and 200 <= code < 300
        print("\n[{}] {}".format("OK" if ok else code, label))
        if ok:
            print("   -> SUCCESS. response head: {}".format(txt[:200]))
            print("\nWINNER: {}".format(label))
            return
        else:
            print("   {}".format(txt))

    # umbrella-first: create the core data-point (which HAS dataPackageId),
    # then the arar record — maybe the package association flows from there.
    print("\n--- umbrella-first attempt (core data-points then arar) ---")
    stamp = int(time.time())
    core = {
        "dataStructure": "ARARDATAPOINT",
        "dataPackageId": pkg,
        "name": "arar-probe-{}".format(stamp),
    }
    code, txt = _post(svc, "/api/core/data-points", body=core)
    print("core /api/core/data-points -> {}: {}".format(code, txt))


if __name__ == "__main__":
    main()
