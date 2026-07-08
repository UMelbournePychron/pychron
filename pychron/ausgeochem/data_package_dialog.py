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

"""Dialog to pick an existing EarthBank DataPackage or create a new one.

Write permission is not exposed by the API, so the list is scoped to the
account's institution; picking a package the account cannot write surfaces a
server error at upload time (the upload guard reports it). Creating a package
adds the current user as supervisor server-side, so a freshly created package
is always writable.
"""

from __future__ import absolute_import

from traits.api import Button, HasTraits, Instance, Int, List, Str
from traitsui.api import (
    HGroup,
    Item,
    Label,
    ObjectColumn,
    OKCancelButtons,
    TableEditor,
    UItem,
    VGroup,
    View,
    spring,
)


class PackageRow(HasTraits):
    id = Int
    name = Str
    institution = Str
    distribution = Str


def _rows_from(packages):
    return [
        PackageRow(
            id=int(p.get("id") or 0),
            name=p.get("name") or "",
            institution=p.get("institutionName") or "",
            distribution=p.get("distribution") or "",
        )
        for p in packages
        if p.get("id")
    ]


class DataPackageDialog(HasTraits):
    """Select or create a DataPackage. On OK, ``selected_id`` holds the id."""

    service = Instance("pychron.ausgeochem.earthbank_service.AusGeochemEarthBankService")
    institution_id = Str

    rows = List(PackageRow)
    selected_row = Instance(PackageRow)
    name_filter = Str
    refresh_button = Button("Refresh")

    new_name = Str
    create_button = Button("Create Package")
    status = Str

    selected_id = Int

    def load(self):
        """Fetch packages for the configured institution."""
        self.status = "loading..."
        try:
            inst = int(self.institution_id) if self.institution_id else None
        except (TypeError, ValueError):
            inst = None
        pkgs = self.service.list_data_packages(
            institution_id=inst, name=self.name_filter or None
        )
        self.rows = _rows_from(pkgs)
        if not self.rows and getattr(self.service, "_last_error", None):
            self.status = "Could not load packages: {}".format(
                self.service._last_error
            )
        else:
            self.status = "{} package(s)".format(len(self.rows))

    def _refresh_button_fired(self):
        self.load()

    def _selected_row_changed(self, row):
        if row is not None:
            self.selected_id = row.id

    def _create_button_fired(self):
        name = self.new_name.strip()
        if not name:
            self.status = "enter a name for the new package"
            return
        try:
            inst = int(self.institution_id) if self.institution_id else None
        except (TypeError, ValueError):
            inst = None
        new_id = self.service.create_data_package(name, institution_id=inst)
        if new_id:
            self.selected_id = int(new_id)
            self.status = "created id={}; selected".format(new_id)
            self.new_name = ""
            self.load()
            for r in self.rows:
                if r.id == self.selected_id:
                    self.selected_row = r
                    break
        else:
            self.status = "Create failed: {}".format(
                getattr(self.service, "_last_error", None) or "see log"
            )

    def traits_view(self):
        table = TableEditor(
            columns=[
                ObjectColumn(name="id", label="Id", editable=False),
                ObjectColumn(name="name", label="Name", editable=False),
                ObjectColumn(name="institution", label="Institution", editable=False),
                ObjectColumn(name="distribution", label="Dist.", editable=False),
            ],
            selected="object.selected_row",
            sortable=True,
            editable=False,
        )
        return View(
            VGroup(
                HGroup(
                    Item("name_filter", label="Filter", springy=True),
                    UItem("refresh_button"),
                ),
                UItem("rows", editor=table, height=280),
                VGroup(
                    Label("Create a new package (you become its supervisor):"),
                    HGroup(
                        Item("new_name", label="New name", springy=True),
                        UItem("create_button"),
                    ),
                    show_border=True,
                ),
                HGroup(spring, UItem("status", style="readonly")),
                show_border=True,
                label="EarthBank Data Package",
            ),
            title="Select or Create Data Package",
            buttons=OKCancelButtons,
            width=640,
            height=460,
            resizable=True,
            kind="livemodal",
        )


# ============= EOF =============================================
