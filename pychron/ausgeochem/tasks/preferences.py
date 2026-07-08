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

import json

from envisage.ui.tasks.preferences_pane import PreferencesPane
from traits.api import (
    Button,
    HasTraits,
    Instance,
    List,
    Password,
    Str,
    on_trait_change,
)
from traitsui.api import (
    HGroup,
    Item,
    ObjectColumn,
    TableEditor,
    UItem,
    VGroup,
    View,
)

from pychron.ausgeochem import credentials_store
from pychron.envisage.tasks.base_preferences_helper import BasePreferencesHelper


class CredentialProfile(HasTraits):
    name = Str("default")
    base_url = Str("https://ausgeochem.auscope.org.au")
    username = Str
    # numeric id of the DataPackage uploads write into; required for upload
    data_package_id = Str
    # institution id (e.g. 193203 = University of Melbourne); scopes the
    # package picker and is used when creating a new package
    institution_id = Str
    # password is transient; persisted in the OS keyring via credentials_store
    password = Password
    # remember (name, username) actually written so renames clean up the keyring
    _persisted_key = None

    def hydrate_password(self):
        """Fetch the password from the OS keyring for this profile/user."""
        self.password = credentials_store.get_password(self.name, self.username) or ""
        self._persisted_key = (self.name, self.username)

    def persist_password(self):
        if self._persisted_key and self._persisted_key != (self.name, self.username):
            old_name, old_user = self._persisted_key
            credentials_store.delete_password(old_name, old_user)
        credentials_store.set_password(self.name, self.username, self.password or "")
        self._persisted_key = (self.name, self.username)


def _profiles_to_json(profiles):
    return json.dumps(
        [
            {
                "name": p.name,
                "base_url": p.base_url,
                "username": p.username,
                "data_package_id": p.data_package_id,
                "institution_id": p.institution_id,
            }
            for p in profiles
        ]
    )


def _profiles_from_json(blob):
    if not blob:
        return []
    try:
        raw = json.loads(blob)
    except (TypeError, ValueError):
        return []
    profiles = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        p = CredentialProfile(
            name=entry.get("name", ""),
            base_url=entry.get("base_url", "https://ausgeochem.auscope.org.au"),
            username=entry.get("username", ""),
            data_package_id=str(entry.get("data_package_id") or ""),
            institution_id=str(entry.get("institution_id") or ""),
        )
        p.hydrate_password()
        profiles.append(p)
    return profiles


class AusGeochemPreferences(BasePreferencesHelper):
    preferences_path = "pychron.ausgeochem"

    # serialized profile list — what actually gets persisted
    profiles_json = Str
    active_profile = Str

    # UI-only, editable list derived from profiles_json. Leading-underscore
    # names are excluded from the preferences store (both load and save) by
    # apptools, so this List(CredentialProfile) is never reloaded from a
    # stringified preference value (which would fail trait validation).
    _profiles = List(CredentialProfile)
    _suppress_sync = False

    # UI controls (live on the model; the PreferencesPane binds items by
    # name against the model as the view context object)
    add_profile = Button("Add Profile")
    remove_profile = Button("Remove Selected")
    test_profile = Button("Test Selected")
    select_package = Button("Select / Create Package")
    _selected_profile = Instance(CredentialProfile)
    _test_status = Str

    def _initialize(self, preferences):
        # Legacy cleanup: older builds persisted the derived 'profiles' trait
        # as a stringified list of CredentialProfile objects. apptools would
        # try to coerce that string back into a List(CredentialProfile) and
        # raise a TraitError, crashing the preferences dialog. Remove the
        # stale key before delegating so it can never be reloaded.
        for legacy in ("profiles", "selected_profile"):
            key = "{}.{}".format(self.preferences_path, legacy)
            try:
                if preferences.get(key) is not None:
                    preferences.remove(key)
            except Exception:
                pass
        super(AusGeochemPreferences, self)._initialize(preferences)
        # apptools sets profiles_json during load with notifications
        # suppressed, so _profiles_json_changed never fires and the editable
        # _profiles list would stay empty. Populate it explicitly here.
        self._suppress_sync = True
        try:
            self._profiles = _profiles_from_json(self.profiles_json)
        finally:
            self._suppress_sync = False

    def _svc_for(self, p):
        from pychron.ausgeochem.earthbank_service import (
            AusGeochemEarthBankService,
        )

        svc = AusGeochemEarthBankService(bind=False)
        svc.base_url = p.base_url
        svc.username = p.username
        svc.password = p.password
        svc.data_package_id = p.data_package_id
        svc.institution_id = p.institution_id
        return svc

    def _add_profile_fired(self):
        existing = {p.name for p in self._profiles}
        i = 1
        while "profile{}".format(i) in existing:
            i += 1
        new = CredentialProfile(name="profile{}".format(i))
        self._profiles = self._profiles + [new]
        self._selected_profile = new
        if not self.active_profile:
            self.active_profile = new.name

    def _remove_profile_fired(self):
        if self._selected_profile is None:
            return
        # also nuke the keyring entry
        credentials_store.delete_password(
            self._selected_profile.name, self._selected_profile.username
        )
        remaining = [p for p in self._profiles if p is not self._selected_profile]
        self._profiles = remaining
        if self.active_profile == self._selected_profile.name:
            self.active_profile = remaining[0].name if remaining else ""
        self._selected_profile = None

    def _test_profile_fired(self):
        if self._selected_profile is None:
            self._test_status = "select a profile first"
            return
        p = self._selected_profile
        svc = self._svc_for(p)
        ok = svc.test_connection()
        self._test_status = (
            "[OK] {}".format(p.name) if ok else "[FAIL] {}".format(p.name)
        )

    def _select_package_fired(self):
        if self._selected_profile is None:
            self._test_status = "select a profile first"
            return
        from pychron.ausgeochem.data_package_dialog import DataPackageDialog

        p = self._selected_profile
        svc = self._svc_for(p)
        if not svc.login(prompt=True):
            self._test_status = "[FAIL] login for {}".format(p.name)
            return
        dlg = DataPackageDialog(service=svc, institution_id=p.institution_id)
        dlg.load()
        info = dlg.edit_traits(kind="livemodal")
        if info.result and dlg.selected_id:
            p.data_package_id = str(dlg.selected_id)
            self._test_status = "package set to {}".format(dlg.selected_id)

    def _profiles_json_changed(self, new):
        if self._suppress_sync:
            return
        self._suppress_sync = True
        try:
            self._profiles = _profiles_from_json(new)
        finally:
            self._suppress_sync = False

    @on_trait_change(
        "_profiles[],_profiles:name,_profiles:base_url,_profiles:username,"
        "_profiles:data_package_id,_profiles:institution_id"
    )
    def _profiles_changed(self):
        if self._suppress_sync:
            return
        self._suppress_sync = True
        try:
            self.profiles_json = _profiles_to_json(self._profiles)
        finally:
            self._suppress_sync = False

    @on_trait_change("_profiles:password,_profiles:username,_profiles:name")
    def _profile_secret_changed(self, obj, name, old, new):
        if self._suppress_sync:
            return
        # Push password into keyring whenever any of the keying parts change
        try:
            obj.persist_password()
        except Exception:
            pass


class AusGeochemPreferencesPane(PreferencesPane):
    model_factory = AusGeochemPreferences
    category = "AusGeochem"

    def traits_view(self):
        cols = [
            ObjectColumn(name="name", label="Profile"),
            ObjectColumn(name="base_url", label="Base URL"),
            ObjectColumn(name="username", label="Username"),
            ObjectColumn(name="password", label="Password", format_func=lambda v: "•" * len(v) if v else ""),
            ObjectColumn(name="data_package_id", label="Data Package Id"),
            ObjectColumn(name="institution_id", label="Institution Id"),
        ]
        table = TableEditor(
            columns=cols,
            selected="_selected_profile",
            sortable=False,
            editable=True,
            row_factory=CredentialProfile,
            deletable=True,
        )

        return View(
            VGroup(
                HGroup(
                    Item("active_profile", label="Active Profile"),
                ),
                UItem("_profiles", editor=table),
                HGroup(
                    UItem("add_profile"),
                    UItem("remove_profile"),
                    UItem("test_profile"),
                    UItem("select_package"),
                    UItem("_test_status", style="readonly"),
                ),
                label="EarthBank Credentials",
                show_border=True,
            )
        )


# ============= EOF =============================================
