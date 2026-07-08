# ===============================================================================
# Copyright 2026 Pychron Developers
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ===============================================================================
"""Offline unit test for find_sample_by_name package scoping.

No network / credentials required — ``_request`` is stubbed. Verifies that
sample reuse is scoped to the target DataPackage so an upload never links a
new ArArDataPoint to a same-named sample living in a different package.

Run:
    python -m pychron.ausgeochem.tests.find_sample_scope_test
"""

from __future__ import absolute_import, print_function

import sys

from pychron.ausgeochem.earthbank_service import AusGeochemEarthBankService


class _FakeResp(object):
    def __init__(self, rows):
        self._rows = rows

    def json(self):
        return self._rows


def _make_service():
    svc = AusGeochemEarthBankService(bind=False)
    svc.warning = svc.info = svc.debug = lambda *a, **k: None
    return svc


def _run():
    failures = []

    def check(cond, msg):
        if not cond:
            failures.append(msg)
            print("  FAIL:", msg)
        else:
            print("  ok  :", msg)

    # 1. scoped lookup sends dataPackageId.equals and returns the in-package id
    svc = _make_service()
    captured = {}

    def fake_request(method, path, params=None, **kw):
        captured["params"] = params
        return _FakeResp(
            [{"sampleDTO": {"id": 111, "name": "S1", "dataPackageId": 42}}]
        )

    svc._request = fake_request
    sid = svc.find_sample_by_name("S1", data_package_id=42)
    check(sid == 111, "scoped lookup returns matching-package sample id (got %r)" % sid)
    check(
        captured["params"].get("dataPackageId.equals") == 42,
        "scoped lookup sends dataPackageId.equals=42 (got %r)"
        % captured["params"].get("dataPackageId.equals"),
    )

    # 2. server ignores the filter and returns a cross-package sample -> rejected
    svc = _make_service()
    svc._request = lambda *a, **k: _FakeResp(
        [{"sampleDTO": {"id": 222, "name": "S1", "dataPackageId": 99}}]
    )
    sid = svc.find_sample_by_name("S1", data_package_id=42)
    check(sid is None, "cross-package sample rejected when scoped (got %r)" % sid)

    # 3. unscoped lookup (data_package_id=None) omits the filter, matches by name
    svc = _make_service()
    captured = {}

    def fake_request2(method, path, params=None, **kw):
        captured["params"] = params
        return _FakeResp(
            [{"sampleDTO": {"id": 333, "name": "S1", "dataPackageId": 99}}]
        )

    svc._request = fake_request2
    sid = svc.find_sample_by_name("S1")
    check(sid == 333, "unscoped lookup matches by name only (got %r)" % sid)
    check(
        "dataPackageId.equals" not in captured["params"],
        "unscoped lookup omits dataPackageId.equals",
    )

    # 4. upload_analysis_group threads the target package into the lookup
    svc = _make_service()
    seen = {}

    def fake_find(name, data_package_id=None):
        seen["name"] = name
        seen["dpid"] = data_package_id
        return 555  # pretend the sample already exists in this package

    def fake_create_dp(*a, **k):
        seen["dp_kwargs"] = k
        return {"id": 999}

    svc.data_package_id = "42"
    svc.confirm_active_user = lambda: True
    svc.find_sample_by_name = fake_find
    svc.create_data_point = fake_create_dp
    # payload builders are exercised elsewhere; stub them so this test isolates
    # the sample-scoping wiring rather than the fake AnalysisGroup internals.
    svc.build_data_point_payload = lambda *a, **k: {}
    svc.build_aliquot_payload = lambda *a, **k: {}
    svc.build_measurement_payload = lambda *a, **k: {}
    svc.build_age_calc_payload = lambda *a, **k: {}
    svc.build_age_summary_payload = lambda *a, **k: {}
    # sub-record creators are no-ops for this test
    svc.create_aliquot = lambda *a, **k: {"id": 1}
    svc.create_measurement = lambda *a, **k: {"id": 1}
    svc.create_age_calculation = lambda *a, **k: {"id": 1}
    svc.create_age_summary = lambda *a, **k: {"id": 1}
    svc._aliquot_name = lambda a: "aliq"

    class _AG(object):
        analyses = [type("A", (), {"sample": "S1", "step": "", "extract_value": 1})()]

    svc.upload_analysis_group(_AG(), confirm=False)
    check(
        seen.get("dpid") == 42,
        "upload passes int package id 42 to find_sample_by_name (got %r)"
        % seen.get("dpid"),
    )
    check(
        seen.get("dp_kwargs", {}).get("sample_id") == 555,
        "reused in-package sample id linked to the data point (got %r)"
        % seen.get("dp_kwargs", {}).get("sample_id"),
    )

    print("\n%d/%d checks passed" % (0 if failures else 1, 1))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run())
