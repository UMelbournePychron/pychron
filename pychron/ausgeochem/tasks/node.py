# ===============================================================================
# Copyright 2024 Pychron Developers
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

from __future__ import absolute_import

import os
import subprocess
import sys
import time

from traits.api import (
    Bool,
    Button,
    Directory,
    Enum,
    HasTraits,
    Instance,
    Int,
    List,
    Str,
)
from traitsui.api import (
    DirectoryEditor,
    EnumEditor,
    HGroup,
    Item,
    ObjectColumn,
    TableEditor,
    UItem,
    VGroup,
    View,
)

from pychron.pipeline.nodes.base import BaseNode
from pychron.processing.analyses.analysis_group import InterpretedAgeGroup


# -- helpers -----------------------------------------------------------------


def _open_with_default_app(path):
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif os.name == "nt":
            os.startfile(path)  # noqa: B019
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


def _group_by_sample(analyses):
    buckets = {}
    order = []
    for a in analyses:
        key = getattr(a, "sample", None) or "unknown"
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(a)
    return [(s, buckets[s]) for s in order]


# Hard-coded fallback list, used when the live LArArInterpretation endpoint
# cannot be reached at configure time.
_FALLBACK_INTERPRETATIONS = [
    "Unknown",
    "I (age of igneous crystallization)",
    "M (age of metamorphism)",
    "Y (maximum depositional age)",
    "S (age of main detrital component)",
    "X (age of xenocrystic component)",
    "D (discordant)",
    "P (Pb loss)",
    "M2 (age of second metamorphic event)",
    "M3 (age of third metamorphic event)",
]


# -- per-group override row --------------------------------------------------


class GroupOverride(HasTraits):
    sample = Str
    datapoint_key = Str
    n_analyses = Int
    interpretation = Str("Unknown")
    flux_monitor = Str
    funding = Str
    literature = Str
    # populated by the node before view opens; controls EnumEditor values
    available_interpretations = List(Str)


# -- node --------------------------------------------------------------------


class AusGeochemNode(BaseNode):
    service = Instance(
        "pychron.ausgeochem.earthbank_service.AusGeochemEarthBankService", ()
    )
    name = "AusGeochem EarthBank"
    skip_configure = False

    mode = Enum("upload", "export_xlsx", "preflight")
    confirm_upload = Bool(True)
    select_package = Button("Select / Create Package")
    package_label = Str
    output_dir = Directory
    file_prefix = Str("earthbank")
    include_sample_xlsx = Bool(True)
    open_after_export = Bool(True)
    one_workbook_per_sample = Bool(False)

    groups = List(GroupOverride)
    _interpretation_vocab = List(Str)

    # ------------------------------------------------------------------
    # lifecycle: refresh group list from unknowns before view opens
    def _configure_hook(self):
        self._update_package_label()
        self._interpretation_vocab = self._fetch_interpretations()
        existing = {g.sample: g for g in self.groups}
        new_groups = []
        for sample, analyses in _group_by_sample(self.unknowns or []):
            prev = existing.get(sample)
            interp = prev.interpretation if prev else "Unknown"
            fm = prev.flux_monitor if prev else ""
            dk = prev.datapoint_key if prev else sample
            new_groups.append(
                GroupOverride(
                    sample=sample,
                    n_analyses=len(analyses),
                    interpretation=interp,
                    flux_monitor=fm,
                    datapoint_key=dk,
                    available_interpretations=self._interpretation_vocab,
                )
            )
        self.groups = new_groups

    def _fetch_interpretations(self):
        try:
            cache = self.service._load_lookup("/api/arar/LArArInterpretation")
        except Exception:
            cache = None
        if not cache:
            return list(_FALLBACK_INTERPRETATIONS)
        # _load_lookup keys are lowercased; recover original casing via a
        # fresh request that returns the rows in display order.
        try:
            resp = self.service._request(
                "get",
                "/api/arar/LArArInterpretation",
                require_auth=bool(self.service.username and self.service.password),
                params={"size": 200},
            )
            if resp is not None:
                rows = resp.json()
                names = [r.get("name") for r in rows if isinstance(r, dict)]
                names = [n for n in names if n]
                if names:
                    return names
        except Exception:
            pass
        return list(_FALLBACK_INTERPRETATIONS)

    # ------------------------------------------------------------------
    def _update_package_label(self):
        pid = self.service.data_package_id
        self.package_label = "Data package: {}".format(pid or "(none — select one)")

    def _select_package_fired(self):
        from pychron.ausgeochem.data_package_dialog import DataPackageDialog

        svc = self.service
        if not svc.login(prompt=True):
            self.package_label = "Data package: login failed"
            return
        dlg = DataPackageDialog(service=svc, institution_id=svc.institution_id)
        dlg.load()
        info = dlg.edit_traits(kind="livemodal")
        if info.result and dlg.selected_id:
            svc.data_package_id = str(dlg.selected_id)
        self._update_package_label()

    # ------------------------------------------------------------------
    def traits_view(self):
        mode_grp = HGroup(
            Item(
                "mode",
                label="Action",
                editor=EnumEditor(
                    values={
                        "upload": "1:Upload to EarthBank",
                        "export_xlsx": "2:Export to xlsx (no upload)",
                        "preflight": "3:Pre-flight check (no write)",
                    }
                ),
            )
        )
        upload_grp = VGroup(
            Item(
                "confirm_upload",
                label="Confirm active user before upload",
                enabled_when="mode == 'upload'",
            ),
            HGroup(
                UItem("select_package", enabled_when="mode == 'upload'"),
                UItem("package_label", style="readonly"),
            ),
            label="Upload",
            show_border=True,
        )
        export_grp = VGroup(
            UItem(
                "output_dir",
                editor=DirectoryEditor(),
                enabled_when="mode == 'export_xlsx'",
            ),
            Item(
                "file_prefix",
                label="Filename prefix",
                enabled_when="mode == 'export_xlsx'",
            ),
            Item(
                "include_sample_xlsx",
                label="Also export Sample workbook",
                enabled_when="mode == 'export_xlsx'",
            ),
            Item(
                "one_workbook_per_sample",
                label="One workbook per sample (else single batch)",
                enabled_when="mode == 'export_xlsx'",
            ),
            Item(
                "open_after_export",
                label="Open file(s) when done",
                enabled_when="mode == 'export_xlsx'",
            ),
            label="Export",
            show_border=True,
        )

        group_table = TableEditor(
            columns=[
                ObjectColumn(name="sample", label="Sample", editable=False),
                ObjectColumn(
                    name="n_analyses", label="# Analyses",
                    editable=False, width=70,
                ),
                ObjectColumn(name="datapoint_key", label="Datapoint Key"),
                ObjectColumn(
                    name="interpretation",
                    label="Interpretation",
                    editor=EnumEditor(name="available_interpretations"),
                    width=260,
                ),
                ObjectColumn(name="flux_monitor", label="Flux Monitor (override)"),
                ObjectColumn(name="funding", label="Funding"),
                ObjectColumn(name="literature", label="Literature"),
            ],
            sortable=False,
            auto_size=False,
            editable=True,
            deletable=False,
            row_factory=GroupOverride,
        )
        groups_grp = VGroup(
            UItem("groups", editor=group_table),
            label="Analysis Groups",
            show_border=True,
        )

        return View(
            VGroup(mode_grp, upload_grp, export_grp, groups_grp),
            title="EarthBank",
            buttons=["OK", "Cancel"],
            kind="livemodal",
            width=720,
            height=520,
            resizable=True,
        )

    # ------------------------------------------------------------------
    def run(self, state):
        if not state.unknowns:
            self.service.warning("no unknowns selected to upload")
            return

        group_meta = {g.sample: g for g in self.groups}
        groups = []
        for sample, analyses in _group_by_sample(state.unknowns):
            ag = InterpretedAgeGroup(analyses=analyses)
            meta = group_meta.get(sample)
            groups.append((ag, meta, sample))

        if self.mode == "export_xlsx":
            self._run_export(groups)
        elif self.mode == "preflight":
            self._run_preflight(groups)
        else:
            self._run_upload(groups)

    # ------------------------------------------------------------------
    @staticmethod
    def _overrides_from(meta):
        """Translate a GroupOverride row into kwargs the service accepts."""
        if meta is None:
            return {}
        dp = {}
        if meta.interpretation:
            dp["interpretationName"] = meta.interpretation
        if meta.flux_monitor:
            dp["fluxMonitorName"] = meta.flux_monitor
        return dp

    def _run_upload(self, groups):
        for ag, meta, sample in groups:
            self.service.info(
                "Uploading {} ({} analyses) to EarthBank".format(
                    sample, len(ag.analyses)
                )
            )
            # interpretation + flux monitor reach the AgeSummary/AgeCalc
            # payloads via attributes on the AnalysisGroup, not the
            # DataPoint **kwargs path.
            if meta is not None:
                if meta.flux_monitor:
                    ag.eb_flux_monitor = meta.flux_monitor
                if meta.interpretation:
                    ag.eb_interpretation = meta.interpretation
                if meta.funding:
                    ag.eb_funding = meta.funding
                if meta.literature:
                    ag.eb_literature = meta.literature
            dp_id = self.service.upload_analysis_group(
                ag, confirm=self.confirm_upload
            )
            if dp_id is not None:
                self.service.info(
                    "EarthBank ArArDataPoint id={} ({})".format(dp_id, sample)
                )

    def _run_preflight(self, groups):
        total = 0
        for ag, meta, sample in groups:
            # apply overrides so validation considers user-selected values
            extras = self._overrides_from(meta)
            orig_fm = getattr(ag, "eb_flux_monitor", None)
            orig_interp = getattr(ag, "eb_interpretation", None)
            if extras.get("fluxMonitorName"):
                ag.eb_flux_monitor = extras["fluxMonitorName"]
            if extras.get("interpretationName"):
                ag.eb_interpretation = extras["interpretationName"]
            misses = self.service.validate_analysis_group(ag)
            ag.eb_flux_monitor = orig_fm
            ag.eb_interpretation = orig_interp
            if not misses:
                self.service.info("[OK] {}".format(sample))
                continue
            total += len(misses)
            self.service.warning("[{} MISS] {}".format(len(misses), sample))
            for sheet, field, value, endpoint in misses:
                self.service.warning(
                    "  {}: {} = {!r} (vs {})".format(sheet, field, value, endpoint)
                )
        self.service.info(
            "preflight: {} group(s), {} total miss(es)".format(len(groups), total)
        )

    def _run_export(self, groups):
        out_dir = self.output_dir
        if not out_dir:
            self.service.warning("export mode: no output directory configured")
            return
        if not os.path.isdir(out_dir):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except OSError as exc:
                self.service.warning(
                    "could not create output dir {}: {}".format(out_dir, exc)
                )
                return

        from pychron.ausgeochem.xlsx_exporter import EarthBankXlsxExporter

        exporter = EarthBankXlsxExporter(service=self.service)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        prefix = self.file_prefix or "earthbank"
        produced = []

        # Per-group overrides are injected into the AGE_SUMMARY / AGE_CALC
        # payloads by mutating the AnalysisGroup before the builder runs.
        # The builders honor `monitor_info` and the AnalysisGroup-level
        # interpretation we patch in.
        def _apply_meta(ag, meta):
            if meta is None:
                return
            if meta.flux_monitor:
                ag.eb_flux_monitor = meta.flux_monitor
            if meta.interpretation:
                ag.eb_interpretation = meta.interpretation
            if meta.funding:
                ag.eb_funding = meta.funding
            if meta.literature:
                ag.eb_literature = meta.literature

        if self.one_workbook_per_sample:
            for ag, meta, sample in groups:
                _apply_meta(ag, meta)
                key = (meta.datapoint_key if meta and meta.datapoint_key else sample)
                arar_path = os.path.join(
                    out_dir,
                    "{}_ArArDataPoint_{}_{}.xlsx".format(prefix, key, stamp),
                )
                exporter.export_analysis_group(ag, arar_path, datapoint_key=key)
                produced.append(arar_path)
                self.service.info("EarthBank xlsx -> {}".format(arar_path))
                if self.include_sample_xlsx:
                    sp = os.path.join(
                        out_dir,
                        "{}_Sample_{}_{}.xlsx".format(prefix, key, stamp),
                    )
                    exporter.export_sample(ag, sp)
                    produced.append(sp)
                    self.service.info("EarthBank Sample xlsx -> {}".format(sp))
        else:
            items = []
            for ag, meta, sample in groups:
                _apply_meta(ag, meta)
                key = (meta.datapoint_key if meta and meta.datapoint_key else sample)
                items.append((ag, key))
            arar_path = os.path.join(
                out_dir,
                "{}_ArArDataPoints_batch_{}.xlsx".format(prefix, stamp),
            )
            exporter.export_analysis_groups(items, arar_path)
            produced.append(arar_path)
            self.service.info(
                "EarthBank batch xlsx ({} groups) -> {}".format(
                    len(groups), arar_path
                )
            )
            if self.include_sample_xlsx:
                sp = os.path.join(
                    out_dir,
                    "{}_Samples_batch_{}.xlsx".format(prefix, stamp),
                )
                exporter.export_samples([ag for ag, _, _ in groups], sp)
                produced.append(sp)
                self.service.info(
                    "EarthBank Samples batch ({} samples) -> {}".format(
                        len(groups), sp
                    )
                )

        if self.open_after_export:
            for p in produced:
                if not _open_with_default_app(p):
                    self.service.warning("could not open {}".format(p))


# ============= EOF =============================================
