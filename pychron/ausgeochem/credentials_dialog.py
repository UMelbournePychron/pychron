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

from traits.api import HasTraits, List, Password, Str
from traitsui.api import EnumEditor, Item, OKCancelButtons, View, VGroup


class EarthBankCredentialsDialog(HasTraits):
    available_profiles = List(Str)
    profile_name = Str("default")
    base_url = Str("https://ausgeochem.auscope.org.au")
    username = Str
    password = Password

    def traits_view(self):
        if self.available_profiles:
            profile_item = Item(
                "profile_name",
                label="Profile",
                editor=EnumEditor(name="available_profiles"),
            )
        else:
            profile_item = Item("profile_name", label="Profile")

        return View(
            VGroup(
                profile_item,
                Item("base_url", label="Base URL"),
                Item("username"),
                Item("password"),
                show_border=True,
                label="EarthBank Login",
            ),
            title="EarthBank Credentials",
            buttons=OKCancelButtons,
            width=420,
        )


# ============= EOF =============================================
