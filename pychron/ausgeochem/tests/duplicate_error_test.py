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
"""Offline unit test for the "already uploaded" error message.

No network / credentials required. Re-uploading a sample into a package that
already holds it makes EarthBank reject the POST with a duplicate-name error.
Verifies that both server responses (bodies copied from a real upload log) are
reported as "already exists", not as an unrecognised value or a server fault.

Run:
    python -m pychron.ausgeochem.tests.duplicate_error_test
"""

from __future__ import absolute_import, print_function

import sys

from pychron.ausgeochem.earthbank_service import AusGeochemEarthBankService

DATA_POINT_400 = (
    '{"type":"https://www.jhipster.tech/problem/constraint-violation",'
    '"title":"Method argument not valid","status":400,'
    '"message":"org.postgresql.util.PSQLException: ERROR: duplicate key value '
    'violates unique constraint \\"data_point_unique_name_deleted_timestamp\\"\\n'
    "  Detail: Key (name, COALESCE(deleted_timestamp, '1970-01-01 00:00:00'::"
    "timestamp without time zone))=(F1\\\\\\\\Test Upload from Unimelb...4FA, "
    '1970-01-01 00:00:00) already exists."}'
)

SAMPLE_500 = (
    '{"type":"https://www.jhipster.tech/problem/problem-with-message",'
    '"title":"Internal Server Error","status":500,'
    '"detail":"Name \'S1\\\\\\\\Test Upload from Unimelb...4FA\' is already used '
    'and therefore not available.",'
    '"path":"/api/core/sample-with-locations","message":"error.http.500"}'
)

FK_400 = (
    '{"title":"Method argument not valid","status":400,'
    '"message":"ERROR: insert or update on table \\"arar_data_point\\" violates '
    'foreign key constraint \\"fk_ararDataPoint_mineral_id\\"\\n'
    '  Detail: Key (mineral_id)=(99) is not present in table \\"material\\"."}'
)


def _make_service():
    svc = AusGeochemEarthBankService(bind=False)
    svc.warning = svc.info = svc.debug = lambda *a, **k: None
    svc.data_package_id = "122827568"
    return svc


def _run():
    failures = []

    def check(cond, msg):
        if not cond:
            failures.append(msg)
            print("  FAIL:", msg)
        else:
            print("  ok  :", msg)

    svc = _make_service()

    # 1. duplicate data point (400 unique-constraint violation)
    msg = svc._humanize_error(400, DATA_POINT_400, "/api/arar/ArArDataPoint")
    check("already exists" in msg, "data point duplicate says 'already exists'")
    check("analysis data point" in msg, "data point duplicate names the record")
    check("F1" in msg, "data point duplicate names the sample (got %r)" % msg)
    check(
        "did not recognise" not in msg,
        "data point duplicate is not reported as an unrecognised value",
    )

    # 2. duplicate sample name (500 "already used")
    msg = svc._humanize_error(500, SAMPLE_500, "/api/core/sample-with-locations")
    check("already exists" in msg, "sample duplicate says 'already exists'")
    check("S1" in msg, "sample duplicate names the sample (got %r)" % msg)
    check(
        "server problem" not in msg,
        "sample duplicate is not reported as a server problem",
    )

    # 3. a genuine FK miss still gets the vocabulary message
    msg = svc._humanize_error(400, FK_400, "/api/arar/ArArDataPoint")
    check(
        "did not recognise" in msg,
        "foreign-key miss still reported as an unrecognised value",
    )

    print("\n%d failure(s)" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run())
