"""Live integration test against an EarthBank (AusGeochem) account.

No public sandbox / test instance is currently advertised; the only known
host is the production app at https://app.ausgeochem.org. Write access
requires permissions granted by the data-platform admins — contact
support@lithodat.com for an account that can POST.

Run directly:
    EARTHBANK_URL=https://app.ausgeochem.org \
    EARTHBANK_USER=alice \
    EARTHBANK_PASS=secret \
    python -m pychron.ausgeochem.tests.integration_test

Smoke mode (no credentials, hits public lookup endpoints only):
    python -m pychron.ausgeochem.tests.integration_test --smoke

The script will skip if EARTHBANK_USER / EARTHBANK_PASS are unset.
"""

from __future__ import absolute_import, print_function

import os
import sys
import time
import traceback

from pychron.ausgeochem.earthbank_service import (
    AusGeochemEarthBankService,
    LOOKUP_ENDPOINTS,
)
from pychron.ausgeochem.tests import load_dotenv


def _env_or_skip(allow_anon=False):
    load_dotenv()
    user = os.environ.get("EARTHBANK_USER")
    pwd = os.environ.get("EARTHBANK_PASS")
    url = os.environ.get("EARTHBANK_URL", "https://ausgeochem.auscope.org.au")
    if not (user and pwd):
        if not allow_anon:
            print("SKIP: set EARTHBANK_USER and EARTHBANK_PASS to run.")
            sys.exit(0)
        return url, None, None
    return url, user, pwd


def smoke():
    """Anonymous reachability check — hits public lookup endpoints."""

    url, _, _ = _env_or_skip(allow_anon=True)
    print("EarthBank SMOKE ({})".format(url))

    svc = AusGeochemEarthBankService(bind=False)
    svc.base_url = url
    # Silence GUI-dependent warning() in headless mode
    svc.warning = lambda *a, **k: None
    svc.info = lambda *a, **k: None
    svc.debug = lambda *a, **k: None

    failures = 0
    sample_endpoints = sorted({ep for _, (ep, _) in LOOKUP_ENDPOINTS.items() if ep})
    for ep in sample_endpoints:
        try:
            cache = svc._load_lookup(ep)
        except Exception as exc:
            cache = None
            print("  [ERR ] {:50s} -> {}".format(ep, exc))
            failures += 1
            continue
        n = len(cache) if cache else 0
        status = "OK  " if n else "MISS"
        if not n:
            failures += 1
        print("  [{}] {:50s} -> {} entries".format(status, ep, n))

    sid = svc.lookup_id("/api/arar/LAnalysisScale", "Single Grain")
    print("\nresolve 'Single Grain' -> id={}".format(sid))

    sys.exit(1 if failures else 0)


def _step(label, fn):
    print("\n=== {} ===".format(label))
    try:
        out = fn()
    except Exception as exc:
        traceback.print_exc()
        return False, exc
    print("  ok ->", repr(out)[:200])
    return True, out


def main():
    url, user, pwd = _env_or_skip()
    print("EarthBank integration test")
    print("  url ={}".format(url))
    print("  user={}".format(user))

    svc = AusGeochemEarthBankService(bind=False)
    svc.base_url = url
    svc.username = user
    svc.password = pwd
    # headless: route logging to stdout so a warning doesn't pull in the GUI
    svc.warning = lambda *a, **k: print("  WARN:", *a)
    svc.info = lambda *a, **k: print("  INFO:", *a)
    svc.debug = lambda *a, **k: None
    package_id = os.environ.get("EARTHBANK_DATA_PACKAGE_ID")
    svc.data_package_id = package_id or ""
    print("  package={}".format(package_id or "(unset)"))

    # 1. Authentication
    ok, _ = _step("authenticate", lambda: svc._ensure_token())
    if not ok:
        sys.exit(1)

    # 2. Account ping
    ok, _ = _step("test_connection", lambda: svc.test_connection())
    if not ok:
        sys.exit(2)

    # 3. Lookup tables — sanity check a handful
    print("\n=== lookup tables ===")
    sample_endpoints = sorted({ep for _, (ep, _) in LOOKUP_ENDPOINTS.items() if ep})
    for ep in sample_endpoints:
        cache = svc._load_lookup(ep)
        n = len(cache) if cache else 0
        print("  {:50s} -> {} entries".format(ep, n))

    # 4. Create a throwaway Sample
    stamp = int(time.time())
    sample_name = "pychron-integ-{}".format(stamp)
    sample_dto = {
        "name": sample_name,
        "sampleID": sample_name,
        "description": "Pychron EarthBank integration test {}".format(stamp),
        "materialName": "sanidine",
        "sampleKindName": "Rock",
    }
    location_dto = {"lat": -34.93, "lon": 138.6, "name": sample_name}
    ok, resp = _step(
        "create_sample",
        lambda: svc.create_sample(
            sample_dto,
            location_dto,
            short_name=sample_name,
            data_package_id=int(package_id) if package_id else None,
        ),
    )
    sample_id = svc._extract_sample_id(resp) if ok else None
    print("  sample_id =", sample_id)

    # 5. Lookup sample back by name
    ok, found = _step("find_sample_by_name", lambda: svc.find_sample_by_name(sample_name))
    print("  match =", found, "expected", sample_id)

    # 6. Create an ArArDataPoint and link it
    if sample_id is not None:
        # Minimal payload whose *Name fields resolve on this instance. The
        # uncertainty type/unit vocab varies per deployment ("1 sigma" /
        # "Absolute" do not resolve here), so they are omitted from the smoke
        # test — the real upload derives them from the AnalysisGroup.
        dp_payload = {
            "analysisDate": "2026-05-20",
            "analysisScaleName": "Single Grain",
            "arMethodName": "Step-heating - laser",
            "analysisUnits": "fA",
            "mineralName": "sanidine",
        }
        # POST goes as the ArArDataPointLithoDTO wrapper: package + sample link
        # live in dataPointDTO. create_data_point builds that and links the
        # sample inline (no separate core-data-point call needed).
        ok, resp = _step(
            "create_data_point",
            lambda: svc.create_data_point(
                dp_payload,
                data_package_id=int(package_id) if package_id else None,
                sample_id=sample_id,
                name=sample_name,
            ),
        )
        dp_id = svc._extract_id(resp) if ok else None
        print("  arArDataPointId =", dp_id)

    print("\nintegration test complete; created sample={}, leave or delete via UI".format(
        sample_name
    ))


if __name__ == "__main__":
    if "--smoke" in sys.argv:
        smoke()
    else:
        main()
