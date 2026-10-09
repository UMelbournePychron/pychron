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
"""Offline unit test for the end-of-upload report.

No network / credentials / GUI required — the service is a stub. Verifies the
upload node confirms once per run (not once per sample) and always finishes
with a single dialog naming each sample that failed and why.

Run:
    python -m pychron.ausgeochem.tests.upload_report_test
"""

from __future__ import absolute_import, print_function

import sys

from pychron.ausgeochem.earthbank_service import AusGeochemEarthBankService
from pychron.ausgeochem.tasks.node import AusGeochemNode


class _Group(object):
    def __init__(self, sample):
        self.sample = sample
        self.analyses = [object()]


class _FakeService(AusGeochemEarthBankService):
    def __init__(self, outcomes, package="42", confirm=True):
        super(_FakeService, self).__init__(bind=False)
        # outcomes: sample -> (dp_id, problem)
        self.outcomes = outcomes
        self.data_package_id = package
        self._confirm = confirm
        self.confirms = 0
        self.uploads = []
        self.dialogs = []
        self.last_upload_problem = None

    def info(self, *a, **k):
        pass

    warning = debug = info

    def confirm_active_user(self):
        self.confirms += 1
        return self._confirm

    def upload_analysis_group(self, ag, confirm=True):
        self.uploads.append((ag, confirm))
        dp_id, self.last_upload_problem = self.outcomes[ag.sample]
        return dp_id

    def warning_dialog(self, msg, **kw):
        self.dialogs.append(("warning", msg))

    def information_dialog(self, msg, **kw):
        self.dialogs.append(("information", msg))


def _upload(svc):
    node = AusGeochemNode()
    node.service = svc
    node._run_upload([(_Group(s), None, s) for s in svc.outcomes])
    return svc


def _run():
    failures = []

    def check(cond, msg):
        if not cond:
            failures.append(msg)
            print("  FAIL:", msg)
        else:
            print("  ok  :", msg)

    # 1. mixed run: one dialog, one confirmation, every failure explained
    svc = _upload(
        _FakeService(
            {
                "F1": (None, "The analysis data point 'F1' already exists."),
                "S1": (7, None),
                "F7": (8, "F7 was partly uploaded."),
            }
        )
    )
    check(svc.confirms == 1, "confirmed once for 3 samples (got %d)" % svc.confirms)
    check(
        all(c is False for _, c in svc.uploads),
        "service is not asked to confirm again per sample",
    )
    check(len(svc.dialogs) == 1, "exactly one report dialog (got %d)" % len(svc.dialogs))
    kind, msg = svc.dialogs[0]
    check(kind == "warning", "report with problems is a warning (got %r)" % kind)
    check("2 of 3" in msg, "report counts uploaded samples")
    check("already exists" in msg, "report explains the failed sample")
    check("partly uploaded" in msg, "report explains the incomplete sample")

    # 2. clean run reports success as information
    svc = _upload(_FakeService({"S1": (7, None)}))
    check(
        [k for k, _ in svc.dialogs] == ["information"],
        "clean run ends with one information dialog (got %r)" % svc.dialogs,
    )

    # 3. no package: one warning, no confirmation, no upload attempts
    svc = _upload(_FakeService({"S1": (7, None)}, package=""))
    check(
        [k for k, _ in svc.dialogs] == ["warning"] and not svc.uploads,
        "missing package warns once and uploads nothing",
    )
    check(svc.confirms == 0, "missing package does not ask for confirmation")

    # 4. cancelling the confirmation uploads nothing
    svc = _upload(_FakeService({"S1": (7, None)}, confirm=False))
    check(not svc.uploads and not svc.dialogs, "cancel uploads nothing")

    print("\n%d failure(s)" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run())
