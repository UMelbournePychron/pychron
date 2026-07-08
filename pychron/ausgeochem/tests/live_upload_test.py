"""End-to-end live upload of a full AnalysisGroup to EarthBank.

Exercises the whole upload_analysis_group chain against the real API:
Sample -> ArArDataPoint (Litho wrapper) -> Aliquots -> Measurements ->
AgeCalc -> AgeSummary. Uses the fake AnalysisGroup fixture from
xlsx_export_test. Creates a throwaway package for isolation and prints its id
so it (and everything in it) can be deleted afterward.

    python -m pychron.ausgeochem.tests.live_upload_test
"""

from __future__ import absolute_import, print_function

import os
import sys
import time

from pychron.ausgeochem.earthbank_service import AusGeochemEarthBankService
from pychron.ausgeochem.tests import load_dotenv
from pychron.ausgeochem.tests.xlsx_export_test import _FakeAG


def main():
    load_dotenv()
    user = os.environ.get("EARTHBANK_USER")
    pwd = os.environ.get("EARTHBANK_PASS")
    url = os.environ.get("EARTHBANK_URL", "https://ausgeochem.auscope.org.au")
    inst = os.environ.get("EARTHBANK_INSTITUTION_ID", "193203")
    if not (user and pwd):
        print("SKIP: set EARTHBANK_USER / EARTHBANK_PASS")
        sys.exit(0)

    svc = AusGeochemEarthBankService(bind=False)
    svc.base_url = url
    svc.username = user
    svc.password = pwd
    svc.institution_id = inst
    svc.warning = lambda *a, **k: print("  WARN:", *a)
    svc.info = lambda *a, **k: print("  INFO:", *a)
    svc.debug = lambda *a, **k: None

    stamp = int(time.time())
    print("creating throwaway package...")
    pkg_id = svc.create_data_package(
        "pychron-live-upload-{}".format(stamp), institution_id=int(inst)
    )
    if not pkg_id:
        print("FAILED to create package; aborting")
        sys.exit(1)
    svc.data_package_id = str(pkg_id)
    print("package id =", pkg_id)

    ag = _FakeAG()
    print("\nuploading AnalysisGroup ({} analyses)...".format(len(ag.analyses)))
    dp_id = svc.upload_analysis_group(ag, confirm=False)
    print("\nupload_analysis_group returned arArDataPointId =", dp_id)

    # verify record counts landed in the package
    detail = svc._request(
        "get", "/api/management/data-packages/{}".format(pkg_id)
    )
    if detail is not None:
        try:
            d = detail.json()
            print(
                "package counts: samples={} arar={}".format(
                    d.get("countSamples"), d.get("countArArDataPoints")
                )
            )
        except ValueError:
            pass

    print(
        "\nDONE. Throwaway package id={} (delete via API/UI to clean up).".format(
            pkg_id
        )
    )


if __name__ == "__main__":
    main()
