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
import re
from datetime import datetime

import requests
from traits.api import List, Str, on_trait_change
from uncertainties import nominal_value, std_dev
from uncertainties.core import AffineScalarFunc

from pychron.core.ui.preference_binding import bind_preference
from pychron.loggable import Loggable
from pychron.pychron_constants import SE, SD, SEM, MSEM

# Field whitelists derived from EarthBank (AusGeochem) v2 Core/ArAr DTOs.
# Mirror the apiField row of the upload spreadsheets so payloads pass through
# the same gate as the manual template-based ingest.

# Map from a payload "*Name" field to the GET endpoint that resolves it to an id.
# Keys are the *Name field; values are (endpoint, idField).
# Uncertainty *type* (sigma level) lives in the `l_uncertainty` table, which
# has NO list endpoint on this deployment but uses stable small ids
# (1 = "1 sigma", 2 = "2 sigma"). It is NOT `/api/core/l-error-types` (that
# table's "1 sigma" is id 59666 and violates the ar_ar_data_point FK). Resolve
# these names statically via STATIC_LOOKUPS below; the uncertainty *unit*
# (abs./%) still resolves against /api/arar/LUncertaintyUnit.


def _norm_uncertainty(name):
    """Normalize a sigma-level name to a UNCERTAINTY_TYPE_VOCAB key."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


UNCERTAINTY_TYPE_VOCAB = {
    "1sigma": 1,
    "1s": 1,
    "1": 1,
    "2sigma": 2,
    "2s": 2,
    "2": 2,
}
# pychron reports error-kinds as SE / SEM / SD / MSEM (MSEM = SE inflated by
# sqrt(MSWD)); all are 1-sigma-level estimators, so they map to l_uncertainty
# id 1. Keyed by the normalized constant value so a rename in pychron_constants
# stays in sync.
for _kind in (SE, SEM, SD, MSEM):
    UNCERTAINTY_TYPE_VOCAB[_norm_uncertainty(_kind)] = 1


LOOKUP_ENDPOINTS = {
    "analysisScaleName": ("/api/arar/LAnalysisScale", "analysisScaleId"),
    "analyticalUncertaintyUnitName": (
        "/api/arar/LUncertaintyUnit",
        "analyticalUncertaintyUnitId",
    ),
    "apparentAgeUncertaintyUnitName": (
        "/api/arar/LUncertaintyUnit",
        "apparentAgeUncertaintyUnitId",
    ),
    "jvalueUncertaintyUnitName": (
        "/api/arar/LUncertaintyUnit",
        "jvalueUncertaintyUnitId",
    ),
    "arMethodName": ("/api/arar/LArArMethod", "arMethodId"),
    "ageCalcTypeName": ("/api/arar/LAgeType", "ageCalcTypeId"),
    "calculatedAgeUncertaintyTypeUnitsName": (
        "/api/arar/LUncertaintyUnit",
        "calculatedAgeUncertaintyTypeUnitsId",
    ),
    "dataInterpretationToolName": (
        "/api/arar/LArArDataInterpretationTool",
        "dataInterpretationToolId",
    ),
    "interpretationName": ("/api/arar/LArArInterpretation", "interpretationId"),
    "decayConstantName": ("/api/arar/DecayConstant", "decayConstantId"),
    "airRatioName": ("/api/arar/AirRatio", "airRatioId"),
    "fluxMonitorName": ("/api/arar/FluxMonitor", "fluxMonitorId"),
    "mineralName": ("/api/core/materials", "mineralId"),
    "plateauStepName": (None, "plateauStepId"),
    "inverseIsoStepName": (None, "inverseIsoStepId"),
    "weightedMeanStepName": (None, "weightedMeanStepId"),
    # Sample DTO lookups
    "sampleKindName": ("/api/core/l-sample-kinds", "sampleKindId"),
    "sampleMethodName": ("/api/core/l-sample-methods", "sampleMethodId"),
    "materialName": ("/api/core/materials", "materialId"),
    "locationKindName": ("/api/core/l-location-kinds", "locationKindId"),
    "archiveName": ("/api/core/archives", "archiveId"),
    "stratographicUnitName": (
        "/api/core/stratigraphic-units",
        "stratographicUnitId",
    ),
    # Funding + literature — separate /api/core endpoints; the upload flow
    # uses 2-way link tables (funding-2-data-points, literature-2-data-points)
    # but we resolve the name → id here so the link payload can be built.
    "fundingName": ("/api/core/fundings", "fundingId"),
    "literatureName": ("/api/core/literature", "literatureId"),
}

# name_key -> (vocab, id_key): resolved from a static map instead of an API
# endpoint. Used for the uncertainty *type* (sigma level) fields whose backing
# table is not exposed by any list endpoint.
STATIC_LOOKUPS = {
    "analyticalUncertaintyTypeName": (
        UNCERTAINTY_TYPE_VOCAB,
        "analyticalUncertaintyTypeId",
    ),
    "apparentAgeUncertaintyTypeName": (
        UNCERTAINTY_TYPE_VOCAB,
        "apparentAgeUncertaintyTypeId",
    ),
    "apparentAgeUncertainityTypeName": (
        UNCERTAINTY_TYPE_VOCAB,
        "apparentAgeUncertainityTypeId",
    ),
    "jvalueUncertaintyTypeName": (
        UNCERTAINTY_TYPE_VOCAB,
        "jvalueUncertaintyTypeId",
    ),
    "ageUncertaintyTypeName": (UNCERTAINTY_TYPE_VOCAB, "ageUncertaintyTypeId"),
    "calculatedAgeUncertaintyTypeName": (
        UNCERTAINTY_TYPE_VOCAB,
        "calculatedAgeUncertaintyTypeId",
    ),
}

DATA_POINT_FIELDS = (
    # extension: funding/literature names are carried so xlsx exporter can
    # write the `datapoint.funding`/`datapoint.literature` columns and the
    # upload flow can resolve to ids for the link tables. They are not in
    # the ArArDataPointDTO itself; resolve_lookups strips them before POST
    # to /api/arar/ArArDataPoint.
    "fundingName",
    "fundingId",
    "literatureName",
    "literatureId",
    "analysisDate",
    "analysisScaleId",
    "analysisScaleName",
    "analysisUnits",
    "analyticalUncertaintyTypeId",
    "analyticalUncertaintyTypeName",
    "analyticalUncertaintyUnitId",
    "analyticalUncertaintyUnitName",
    "apparentAgeUncertaintyTypeId",
    "apparentAgeUncertaintyTypeName",
    "apparentAgeUncertaintyUnitId",
    "apparentAgeUncertaintyUnitName",
    "arArAnalyticalSetUpId",
    "arMethodId",
    "arMethodName",
    "commentAnalyte",
    "grainDiameterMax",
    "grainDiameterMin",
    "id",
    "irradiationBatchIDId",
    "jvalueUncertaintyUnitId",
    "jvalueUncertaintyUnitName",
    "lithologyId",
    "lithologyName",
    "mineralId",
    "mineralName",
)

MEASUREMENT_FIELDS = (
    "aliquotName",
    "analysisTime",
    "analysisUnits",
    "apparentAge",
    "apparentAgeUncertainityTypeId",
    "apparentAgeUncertainityTypeName",
    "apparentAgeUncertainty",
    "ar36Corr",
    "ar36CorrUncertainty",
    "ar36ExcInt",
    "ar36ExcIntUncertainty",
    "ar36blank",
    "ar36blankUncertainty",
    "ar37Corr",
    "ar37CorrUncertainty",
    "ar37ExcInt",
    "ar37ExcIntUncertainty",
    "ar37blank",
    "ar37blankUncertainty",
    "ar38Corr",
    "ar38CorrUncertainty",
    "ar38ExcInt",
    "ar38ExcIntUncertainty",
    "ar38blank",
    "ar38blankUncertainty",
    "ar39Corr",
    "ar39CorrUncertainty",
    "ar39ExcInt",
    "ar39ExcIntUncertainty",
    "ar39KReleased",
    "ar39blank",
    "ar39blankUncertainty",
    "ar40Corr",
    "ar40CorrUncertainty",
    "ar40ExcInt",
    "ar40ExcIntUncertainty",
    "ar40blank",
    "ar40blankUncertainty",
    "arArDataPointId",
    "beamSize",
    "beamSizeUnits",
    "caK",
    "caKUncertainty",
    "clK",
    "clKUncertainty",
    "cumulative39ArK",
    "furnaceTemperature",
    "id",
    "inverseIsoStepId",
    "inverseIsoStepName",
    "jValue",
    "jValueUncertainty",
    "jvalueUncertaintyTypeId",
    "jvalueUncertaintyTypeName",
    "kCa",
    "kCaUncertainty",
    "kContent",
    "kContentUncertainty",
    "laserPower",
    "laserPowerUnits",
    "measurementComment",
    "plateauStepId",
    "plateauStepName",
    "radiogenicArgon",
    "ratio36Arx39ArCorr",
    "ratio36Arx39ArCorrUncertainty",
    "ratio37Arx39ArCorr",
    "ratio37Arx39ArCorrUncertainty",
    "ratio38Arx39ArCorr",
    "ratio38Arx39ArCorrUncertainty",
    "ratio40Arx36ArTrapped",
    "ratio40Arx36ArTrappedUncertainty",
    "ratio40Arx39ArCorr",
    "ratio40Arx39ArCorrUncertainty",
    "ratio40Arx39ArK",
    "ratio40Arx39ArKUncertainty",
    "stepNumber",
    "weightedMeanStepId",
    "weightedMeanStepName",
)

ALIQUOT_FIELDS = (
    "aliquotComment",
    "aliquotName",
    "aliquotSize",
    "aliquotUnits",
    "arArDataPointId",
    "id",
)

AGE_SUMMARY_FIELDS = (
    "age",
    "ageCalcTypeId",
    "ageCalcTypeName",
    "ageUncertainty",
    "ageUncertaintyTypeId",
    "ageUncertaintyTypeName",
    "agepvalue",
    "arArDataPointId",
    "calculatedAgeUncertaintyTypeId",
    "calculatedAgeUncertaintyTypeName",
    "calculatedAgeUncertaintyTypeUnitsId",
    "calculatedAgeUncertaintyTypeUnitsName",
    "dataInterpretationToolId",
    "dataInterpretationToolName",
    "description",
    "id",
    "interpretationId",
    "interpretationName",
    "mswd",
    "nAnalysisGrouped",
    "preferredAge",
)

AGE_CALC_FIELDS = (
    "airRatioId",
    "airRatioName",
    "arArDataPointId",
    "comment",
    "decayConstantId",
    "decayConstantName",
    "fluxMonitorId",
    "fluxMonitorName",
    "id",
)

# Core-model Sample DTO subset (SampleDTO). Only fields we actually populate
# from a pychron Analysis / sample record; full DTO is much larger.
SAMPLE_FIELDS = (
    # extension: same funding/literature carriers as DataPoint
    "fundingName",
    "fundingId",
    "literatureName",
    "literatureId",
    "archiveId",
    "archiveName",
    "collectDateMax",
    "collectDateMin",
    "dataPackageId",
    "description",
    "id",
    "igsn",
    "locationId",
    "locationKindId",
    "locationKindName",
    "locationName",
    "materialId",
    "materialName",
    "name",
    "referenceElevation",
    "relativeElevationMax",
    "relativeElevationMin",
    "rockUnitAgeDescription",
    "rockUnitAgeMax",
    "rockUnitAgeMin",
    "sampleID",
    "sampleKindId",
    "sampleKindName",
    "sampleMethodId",
    "sampleMethodName",
    "stratographicUnitId",
    "stratographicUnitName",
)

LOCATION_FIELDS = (
    "description",
    "id",
    "lat",
    "latLonPrecision",
    "lon",
    "name",
)

# Core DataPoint umbrella record — links Sample to the discipline-specific
# (ArAr/UPb/etc.) data point. dataStructure is the discriminator enum.
CORE_DATA_POINT_FIELDS = (
    "arArDataPointId",
    "arArIrradiationId",
    "arArSetUpId",
    "dataPackageId",
    "dataStructure",
    "description",
    "id",
    "name",
    "sampleId",
    "sampleName",
    "sourceId",
)


# EarthBank controlled-vocabulary names for AgeCalc references. Map from a
# normalized "author_year" key derived from the pychron citation string.
DECAY_CONSTANT_VOCAB = {
    "steiger_1977": "Steiger and Jager, 1977",
    "steigerjager_1977": "Steiger and Jager, 1977",
    "min_2000": "Min et al. 2000",
    "min_2008": "Min et al. 2000",  # Pychron default citation is 2008-era paper that updates the 2000 model
    "renne_2010": "Renne et al. 2011",
    "renne_2011": "Renne et al. 2011",
}

AIR_RATIO_VOCAB = {
    "nier_1950": "Nier 1950",
    "lee_2006": "Lee et al. 2006",
}


def _citation_key(citation):
    """Normalize a 'Author (1977)' / 'Author and X (2011)' /
    'Author et al. 2008' string to 'author_year' for vocab lookup."""
    if not citation:
        return None
    raw = str(citation)
    s = re.sub(r"\([^)]*\)", " ", raw)  # strip "(...)" content
    year_match = re.search(r"(19|20)\d{2}", raw)
    year = year_match.group(0) if year_match else ""
    # First surname only: split on any non-alpha character, take token #1
    tokens = [t for t in re.split(r"[^A-Za-z]+", s) if t]
    author = tokens[0].lower() if tokens else ""
    if not author:
        return None
    return "{}_{}".format(author, year) if year else author


def _normalize_decay_constant(citation):
    key = _citation_key(citation)
    if key and key in DECAY_CONSTANT_VOCAB:
        return DECAY_CONSTANT_VOCAB[key]
    return citation  # pass-through; lookup_id will warn if unknown


def _normalize_air_ratio(citation):
    key = _citation_key(citation)
    if key and key in AIR_RATIO_VOCAB:
        return AIR_RATIO_VOCAB[key]
    return citation


def _infer_ar_method(analyses):
    """Map pychron run conventions to an EarthBank LArArMethod name.

    Rules (per lab convention):
      - RunID with alphabetical step suffix (1000-01A, 1000-01B) =>
        step-heating. extract_value 0-50 => laser, >=300 => furnace,
        otherwise "Step-heating - undefined".
      - RunID with no step (1000-01, 1000-02, sequential aliquots) =>
        "Total fusion - laser" (laser fusion is the dominant total-fusion
        modality in pychron labs; furnace total-fusion would still come
        through here but is rarely used).
    """

    if not analyses:
        return None

    has_step = False
    extracts = []
    for a in analyses:
        step = getattr(a, "step", "")
        if step and str(step).strip():
            has_step = True
        ev = getattr(a, "extract_value", None)
        if ev is not None:
            try:
                extracts.append(float(ev))
            except (TypeError, ValueError):
                pass

    if not has_step:
        return "Total fusion - laser"

    if extracts:
        # use the max extract value across the heating schedule
        peak = max(extracts)
        if peak >= 300:
            return "Step-heating - furnace"
        if peak <= 50:
            return "Step-heating - laser"
    return "Step-heating - undefined"


def _flux_monitor_query(monitor_info):
    """Pychron stores monitor_info as ``(monitor_age, monitor_reference)`` or
    just a plain string. Reduce to a single string suitable for fuzzy
    lookup against the FluxMonitor vocab."""
    if monitor_info is None:
        return None
    if isinstance(monitor_info, (list, tuple)):
        parts = [str(p) for p in monitor_info if p not in (None, "")]
        return " ".join(parts) if parts else None
    return str(monitor_info)


def _split_ufloat(u):
    if u is None:
        return None, None
    try:
        return float(nominal_value(u)), float(std_dev(u))
    except (TypeError, ValueError):
        return None, None


def _iso_corr(analysis, name):
    iso = analysis.get_isotope(name) if hasattr(analysis, "get_isotope") else None
    if iso is None:
        return None, None
    try:
        return _split_ufloat(iso.get_interference_corrected_value())
    except Exception:
        return None, None


def _iso_raw(analysis, name):
    iso = analysis.get_isotope(name) if hasattr(analysis, "get_isotope") else None
    if iso is None:
        return None, None
    try:
        return _split_ufloat(iso.get_non_detector_corrected_value())
    except Exception:
        return None, None


def _iso_blank(analysis, name):
    iso = analysis.get_isotope(name) if hasattr(analysis, "get_isotope") else None
    if iso is None or getattr(iso, "blank", None) is None:
        return None, None
    return _split_ufloat(iso.blank.uvalue)


def _ratio(analysis, key):
    if not hasattr(analysis, "get_ratio"):
        return None, None
    try:
        return _split_ufloat(analysis.get_ratio(key))
    except Exception:
        return None, None


def _to_float(v):
    """Coerce to float, returning None for empty/blank/non-numeric values."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class AusGeochemEarthBankService(Loggable):
    """HTTP helper for the AusGeochem EarthBank (v2) API."""

    base_url = Str("https://ausgeochem.auscope.org.au")
    username = Str
    password = Str

    # Numeric id of the EarthBank DataPackage uploads are written into. Every
    # ArArDataPoint POST must carry a dataPackageId the account can write, else
    # the server rejects with 500 "Package is not writable by user". Set
    # per-profile; pick/create via the package dialog or discover ids with
    # tests/packages_probe.py.
    data_package_id = Str
    # Institution the account belongs to (e.g. 193203 = University of
    # Melbourne). Scopes the package picker list and is used when creating a
    # new package. Not available from /api/account, so configured per-profile.
    institution_id = Str

    profiles_json = Str
    active_profile = Str
    profiles = List

    _token = None
    # last human-friendly error message produced by a failed request
    _last_error = None

    def __init__(self, bind=True, *args, **kw):
        super(AusGeochemEarthBankService, self).__init__(*args, **kw)
        self._session = requests.Session()
        # lookup cache: { endpoint: { name.lower(): id } }
        self._lookup_cache = {}
        if bind:
            self._bind_preferences()
            self._apply_active_profile()

    @on_trait_change("profiles_json,active_profile")
    def _profile_changed(self):
        self._apply_active_profile()

    def _apply_active_profile(self):
        """Hydrate base_url/username/password from the active profile entry."""

        try:
            data = json.loads(self.profiles_json) if self.profiles_json else []
        except (TypeError, ValueError):
            data = []
        self.profiles = [d for d in data if isinstance(d, dict)]

        if not self.profiles:
            return
        target = self.active_profile
        chosen = None
        for entry in self.profiles:
            if entry.get("name") == target:
                chosen = entry
                break
        if chosen is None:
            chosen = self.profiles[0]
            self.active_profile = chosen.get("name", "")

        self.base_url = chosen.get("base_url") or self.base_url
        self.username = chosen.get("username", "")
        # per-profile upload target package (str; may be blank until configured)
        self.data_package_id = str(chosen.get("data_package_id") or "")
        self.institution_id = str(chosen.get("institution_id") or "")
        # Password lives in the OS keyring rather than the JSON blob. The blob
        # may still carry one (for back-compat); fall back to that if present.
        try:
            from pychron.ausgeochem import credentials_store

            stored = credentials_store.get_password(
                chosen.get("name", ""), chosen.get("username", "")
            )
        except Exception:
            stored = None
        self.password = stored or chosen.get("password", "")
        # changing creds invalidates the cached token
        self._token = None

    # ------------------------------------------------------------------
    # authentication
    def test_connection(self):
        if not self._ensure_credentials():
            return False
        resp = self._request("get", "/api/account")
        return bool(resp and resp.ok)

    def login(self, prompt=True):
        """Force a fresh login. Prompts for credentials if missing and
        ``prompt`` is True. Returns True on success."""

        self._token = None
        if not self._ensure_credentials(prompt=prompt):
            return False
        return self._ensure_token() is not None

    def _ensure_credentials(self, prompt=True):
        if self.username and self.password:
            return True
        if not prompt:
            return False
        return self._prompt_credentials()

    def _prompt_credentials(self):
        try:
            from pychron.ausgeochem.credentials_dialog import (
                EarthBankCredentialsDialog,
            )
        except ImportError:
            self.warning("Credentials dialog unavailable; configure via Preferences")
            return False

        names = [p.get("name", "") for p in self.profiles if p.get("name")]
        dlg = EarthBankCredentialsDialog(
            available_profiles=names,
            profile_name=self.active_profile or (names[0] if names else "default"),
            base_url=self.base_url,
            username=self.username or "",
        )
        info = dlg.edit_traits(kind="modal")
        if not info.result:
            return False
        # apply immediately to in-memory state for this session
        self.base_url = dlg.base_url or self.base_url
        self.username = dlg.username
        self.password = dlg.password
        self.active_profile = dlg.profile_name or self.active_profile
        return bool(self.username and self.password)

    # ------------------------------------------------------------------
    # POST endpoints — one per ArAr sheet
    def create_data_point(
        self,
        dto,
        data_package_id=None,
        sample_id=None,
        name=None,
        irradiation_name=None,
        setup_name=None,
    ):
        """POST an ArArDataPoint as the ``ArArDataPointLithoDTO`` wrapper the
        API requires.

        The umbrella record (package + sample link) goes in ``dataPointDTO``;
        the ArAr-specific fields go in ``extendingDataPointDTO``. Posting the
        bare ArAr fields with no ``dataPointDTO`` is rejected 500 "Package is
        not writable by user" because the server resolves the package from the
        umbrella, not from a field on the ArAr DTO. This single POST also
        creates the core data-point and links the sample inline, so no
        separate ``create_core_data_point`` call is needed.

        Returns the parsed response; its top-level ``id`` is the
        arArDataPointId (used by aliquots / measurements)."""

        core = {"dataStructure": "ARARDATAPOINT"}
        if data_package_id is not None:
            core["dataPackageId"] = int(data_package_id)
        if sample_id is not None:
            core["sampleId"] = int(sample_id)
        if name:
            core["name"] = name
        ext = self.resolve_lookups(self._cleanup(dto, DATA_POINT_FIELDS))
        wrapper = {
            "dataPointDTO": self._cleanup(core, CORE_DATA_POINT_FIELDS),
            "extendingDataPointDTO": ext,
        }
        if irradiation_name:
            wrapper["arArIrradiationName"] = irradiation_name
        if setup_name:
            wrapper["arArSetUpName"] = setup_name
        return self._post_raw("/api/arar/ArArDataPoint", wrapper)

    def create_aliquot(self, dto):
        return self._post_json("/api/arar/ArArAliquot", dto)

    def create_measurement(self, dto):
        return self._post_json("/api/arar/ArArMeasurement", dto)

    def create_age_summary(self, dto):
        return self._post_json("/api/arar/ArArAgeSummary", dto)

    def create_age_calculation(self, dto):
        return self._post_json("/api/arar/ArArAgeCalc", dto)

    def create_core_data_point(self, dto):
        """POST the umbrella DataPoint that links a Sample to the discipline
        record (ArArDataPoint, UPbDataPoint, ...)."""

        payload = self._cleanup(dto, CORE_DATA_POINT_FIELDS)
        return self._post_raw("/api/core/data-points", payload)

    def create_sample(
        self, sample_dto, location_dto=None, short_name=None, data_package_id=None
    ):
        """POST a SampleWithLocationDTO. ``sample_dto`` and ``location_dto``
        are flat dicts; their *Name fields are resolved to *Id by
        ``resolve_lookups``. Returns the parsed JSON response (containing the
        new id) or ``None``.

        ``data_package_id`` is required for write: like every EarthBank write,
        a sample without a writable dataPackageId is rejected 500 "Package is
        not writable by user". It is stamped on both the wrapper and the inner
        sampleDTO since the accepting field is not documented."""

        sample_dto = dict(sample_dto or {})
        if data_package_id is not None:
            sample_dto["dataPackageId"] = int(data_package_id)
        sample_clean = self.resolve_lookups(self._cleanup(sample_dto, SAMPLE_FIELDS))
        location_clean = self._cleanup(location_dto, LOCATION_FIELDS) if location_dto else {}
        wrapper = {
            "sampleDTO": sample_clean,
            "locationDTO": location_clean,
        }
        if data_package_id is not None:
            wrapper["dataPackageId"] = int(data_package_id)
        if short_name:
            wrapper["shortName"] = short_name
        # bypass resolve_lookups on the wrapper itself (nested)
        return self._post_raw("/api/core/sample-with-locations", wrapper)

    def find_sample_by_name(self, name, data_package_id=None):
        """Look up an existing sample by exact name. Returns its id or None.

        Every EarthBank sample belongs to exactly one DataPackage (its
        ``sampleDTO.dataPackageId``). When ``data_package_id`` is given the
        lookup is scoped to that package with a ``dataPackageId.equals``
        filter, so an upload never reuses a same-named sample that lives in a
        *different* package — reusing one would link the new ArArDataPoint
        across packages (leaving the target package's sample count at 0). Pass
        ``None`` only for an intentionally global search."""

        if not name:
            return None
        params = {"name.equals": name, "size": 5}
        if data_package_id is not None:
            params["dataPackageId.equals"] = int(data_package_id)
        resp = self._request(
            "get",
            "/api/core/sample-with-locations",
            params=params,
        )
        if resp is None:
            return None
        try:
            rows = resp.json()
        except ValueError:
            return None
        for row in rows or []:
            sample = (row or {}).get("sampleDTO") or {}
            if sample.get("name") != name:
                continue
            # Defend against a server that ignores the package filter: only
            # accept a row whose package matches the requested scope.
            if data_package_id is not None and sample.get(
                "dataPackageId"
            ) != int(data_package_id):
                continue
            return sample.get("id")
        return None

    # ------------------------------------------------------------------
    # data package discovery + creation
    #
    # EarthBank ties every ArArDataPoint to a DataPackage; a POST without a
    # writable ``dataPackageId`` is rejected 500 "Package is not writable by
    # user". The management API lives at /api/management/data-packages (NOT
    # /api/core/). Rows come back wrapped as {"dataPackageDTO": {...}, counts}.
    # Write permission is NOT exposed in the DTO (only countEditors /
    # countSupervisors), so callers pick from the institution-scoped list and
    # let the upload surface a server error on a non-writable choice.
    DATA_PACKAGES_ENDPOINT = "/api/management/data-packages"

    def get_account(self):
        """Return the authenticated user's account dict (or None)."""
        resp = self._request("get", "/api/account")
        if resp is None:
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    @staticmethod
    def _unwrap_package(row):
        """Flatten a management row to a simple dict of the fields we use."""
        dto = (row or {}).get("dataPackageDTO") or row or {}
        return {
            "id": dto.get("id") or (row or {}).get("id"),
            "name": dto.get("name") or (row or {}).get("name"),
            "distribution": dto.get("distribution"),
            "workflowState": dto.get("workflowState"),
            "institutionId": dto.get("institutionId"),
            "institutionName": dto.get("institutionName"),
            "createdById": dto.get("createdById"),
        }

    def list_data_packages(self, institution_id=None, name=None, size=500):
        """List DataPackages, optionally filtered by institution / name.

        Returns a list of flattened dicts (see ``_unwrap_package``). Uses
        JHipster criteria query params. Empty list on failure."""

        params = {"page": 0, "size": size, "sort": "name,ASC"}
        if institution_id:
            params["institutionId.equals"] = institution_id
        if name:
            params["name.contains"] = name
        resp = self._request("get", self.DATA_PACKAGES_ENDPOINT, params=params)
        if resp is None:
            return []
        try:
            rows = resp.json()
        except ValueError:
            return []
        return [self._unwrap_package(r) for r in (rows or [])]

    def create_data_package(
        self,
        name,
        institution_id=None,
        distribution="PRIVATE",
        workflow_state="IN_PROGRESS",
        license_text="Creative Commons",
        description=None,
    ):
        """Create a DataPackage and return its new id (or None).

        The creator is added as supervisor server-side from the auth token, so
        a freshly created package is always writable. The endpoint takes a
        ``DataPackageLithoDTO``: the fields must be nested under
        ``dataPackageDTO`` (a flat body is accepted but SILENTLY IGNORES the
        name and creates a default-named package), and are also mirrored at the
        top level to match the wrapper the API returns."""

        dto = {
            "name": name,
            "distribution": distribution,
            "workflowState": workflow_state,
            "licenseText": license_text,
        }
        if institution_id:
            dto["institutionId"] = int(institution_id)
        if description:
            dto["description"] = description

        body = dict(dto)
        body["dataPackageDTO"] = dto
        resp = self._request(
            "post",
            self.DATA_PACKAGES_ENDPOINT,
            json=body,
            headers={"Content-Type": "application/json"},
        )
        if resp is not None:
            try:
                data = resp.json()
            except ValueError:
                data = None
            if data:
                pkg = self._unwrap_package(data)
                if pkg.get("id"):
                    self.info("created DataPackage id={}".format(pkg["id"]))
                    return pkg["id"]
        self.warning(
            "Could not create the data package {!r} in EarthBank.\n\n{}".format(
                name, self._last_error or "See the log for details."
            )
        )
        return None

    # ------------------------------------------------------------------
    # payload builders — one per DTO
    def build_data_point_payload(self, analysis_group=None, analysis=None, **overrides):
        payload = dict(overrides)

        if analysis is None and analysis_group is not None:
            analysis = analysis_group.analyses[0] if analysis_group.analyses else None

        # arMethod is determined by the WHOLE schedule (steps + extract
        # values), not the single first analysis, so resolve it from the
        # full group when one is supplied.
        method_pool = (
            list(analysis_group.analyses)
            if analysis_group is not None and getattr(analysis_group, "analyses", None)
            else ([analysis] if analysis is not None else [])
        )
        inferred_method = _infer_ar_method(method_pool)

        # funding / literature: optional group-level overrides (set by the
        # node editor) carried through to the xlsx exporter and the API
        # link tables (funding-2-data-points / literature-2-data-points).
        if analysis_group is not None:
            funding = getattr(analysis_group, "eb_funding", None)
            literature = getattr(analysis_group, "eb_literature", None)
            if funding:
                payload.setdefault("fundingName", funding)
            if literature:
                payload.setdefault("literatureName", literature)

        if analysis is not None:
            gmin, gmax = self._parse_grain_size(
                getattr(analysis, "grainsize", None)
                or getattr(analysis_group, "grainsize", None)
            )
            payload.setdefault("analysisDate", self._format_date(analysis))
            payload.setdefault("analysisUnits", "fA")
            payload.setdefault(
                "analysisScaleName", self._analysis_scale_name(analysis_group)
            )
            payload.setdefault(
                "analyticalUncertaintyTypeName",
                getattr(analysis_group, "age_error_kind", None),
            )
            payload.setdefault("analyticalUncertaintyUnitName", "abs.")
            payload.setdefault(
                "apparentAgeUncertaintyTypeName",
                getattr(analysis_group, "age_error_kind", None),
            )
            payload.setdefault("apparentAgeUncertaintyUnitName", "abs.")
            payload.setdefault("jvalueUncertaintyUnitName", "abs.")
            payload.setdefault(
                "arMethodName",
                inferred_method
                or getattr(analysis, "experiment_type", None)
                or getattr(analysis, "analysis_type", None),
            )
            payload.setdefault("commentAnalyte", self._analysis_comment(analysis))
            payload.setdefault("grainDiameterMin", gmin)
            payload.setdefault("grainDiameterMax", gmax)
            payload.setdefault(
                "lithologyName",
                getattr(analysis_group, "lithology", None)
                or getattr(analysis, "lithology", None),
            )
            payload.setdefault(
                "mineralName",
                getattr(analysis_group, "material", None)
                or getattr(analysis, "material", None),
            )

        return self._cleanup(payload, DATA_POINT_FIELDS)

    def build_aliquot_payload(self, analysis=None, **overrides):
        payload = dict(overrides)

        if analysis is not None:
            payload.setdefault("aliquotName", self._aliquot_name(analysis))
            payload.setdefault("aliquotSize", getattr(analysis, "weight", None))
            payload.setdefault(
                "aliquotUnits", "mg" if getattr(analysis, "weight", None) else None
            )

        return self._cleanup(payload, ALIQUOT_FIELDS)

    def build_measurement_payload(self, analysis=None, **overrides):
        payload = dict(overrides)

        if analysis is None:
            return self._cleanup(payload, MEASUREMENT_FIELDS)

        # corrected isotopes (interference + blank corrected)
        for n in ("Ar40", "Ar39", "Ar38", "Ar37", "Ar36"):
            v, e = _iso_corr(analysis, n)
            payload.setdefault("ar{}Corr".format(n[2:]), v)
            payload.setdefault("ar{}CorrUncertainty".format(n[2:]), e)

        # raw / excluding interference correction
        for n in ("Ar40", "Ar39", "Ar38", "Ar37", "Ar36"):
            v, e = _iso_raw(analysis, n)
            payload.setdefault("ar{}ExcInt".format(n[2:]), v)
            payload.setdefault("ar{}ExcIntUncertainty".format(n[2:]), e)

        # blanks
        for n in ("Ar40", "Ar39", "Ar38", "Ar37", "Ar36"):
            v, e = _iso_blank(analysis, n)
            payload.setdefault("ar{}blank".format(n[2:]), v)
            payload.setdefault("ar{}blankUncertainty".format(n[2:]), e)

        # corrected ratios
        for top in ("36", "37", "38", "40"):
            v, e = _ratio(analysis, "Ar{}/Ar39".format(top))
            payload.setdefault("ratio{}Arx39ArCorr".format(top), v)
            payload.setdefault("ratio{}Arx39ArCorrUncertainty".format(top), e)

        # Ca/K, K/Ca, Cl/K — prefer ArArAge convenience properties
        cak_v, cak_e = _split_ufloat(getattr(analysis, "cak", None))
        kca_v, kca_e = _split_ufloat(getattr(analysis, "kca", None))
        clk_v, clk_e = _split_ufloat(getattr(analysis, "clk", None))
        payload.setdefault("caK", cak_v)
        payload.setdefault("caKUncertainty", cak_e)
        payload.setdefault("kCa", kca_v)
        payload.setdefault("kCaUncertainty", kca_e)
        payload.setdefault("clK", clk_v)
        payload.setdefault("clKUncertainty", clk_e)

        # 40Ar*/39ArK
        rad40 = getattr(analysis, "rad40", None)
        k39 = getattr(analysis, "k39", None)
        if rad40 is not None and k39 is not None:
            try:
                v, e = _split_ufloat(rad40 / k39)
                payload.setdefault("ratio40Arx39ArK", v)
                payload.setdefault("ratio40Arx39ArKUncertainty", e)
            except (TypeError, ZeroDivisionError):
                pass

        # radiogenic yield + j value + apparent age
        rad_yield, _ = _split_ufloat(getattr(analysis, "radiogenic_yield", None))
        payload.setdefault("radiogenicArgon", rad_yield)
        jv, je = _split_ufloat(getattr(analysis, "j", None))
        payload.setdefault("jValue", jv)
        payload.setdefault("jValueUncertainty", je)
        ua = getattr(analysis, "uage", None)
        av, ae = _split_ufloat(ua)
        payload.setdefault("apparentAge", av)
        payload.setdefault("apparentAgeUncertainty", ae)

        # 39ArK released
        k39_v, _ = _split_ufloat(getattr(analysis, "k39", None))
        payload.setdefault("ar39KReleased", k39_v)

        # extraction / heating
        payload.setdefault("aliquotName", self._aliquot_name(analysis))
        payload.setdefault("analysisTime", self._format_datetime(analysis))
        step = getattr(analysis, "step", None)
        payload.setdefault("stepNumber", self._step_to_num(step))
        payload.setdefault("analysisUnits", "fA")
        payload.setdefault("beamSize", getattr(analysis, "beam_diameter", None))
        payload.setdefault(
            "beamSizeUnits", "microns" if getattr(analysis, "beam_diameter", None) else None
        )

        extract_units = getattr(analysis, "extract_units", None)
        extract_value = getattr(analysis, "extract_value", None)
        if extract_units and "C" in str(extract_units):
            payload.setdefault("furnaceTemperature", extract_value)
        else:
            payload.setdefault("laserPower", extract_value)
            payload.setdefault("laserPowerUnits", extract_units)

        # K content (wt%)
        k2o_v, k2o_e = _split_ufloat(getattr(analysis, "k2o", None))
        payload.setdefault("kContent", k2o_v)
        payload.setdefault("kContentUncertainty", k2o_e)

        if getattr(analysis, "is_plateau_step", False):
            payload.setdefault("plateauStepName", "Yes")

        return self._cleanup(payload, MEASUREMENT_FIELDS)

    def build_age_summary_payload(self, analysis_group=None, **overrides):
        payload = dict(overrides)

        if analysis_group is None:
            return self._cleanup(payload, AGE_SUMMARY_FIELDS)

        pv = analysis_group.get_preferred_obj("age")
        calc_name = getattr(pv, "computed_kind", pv.kind)
        age_units = getattr(
            getattr(analysis_group, "arar_constants", None), "age_units", "Ma"
        )
        scaled = analysis_group.get_ma_scaled_age()
        mswd, _, _, pvalue = analysis_group.get_preferred_mswd_tuple()

        payload.setdefault("age", float(nominal_value(scaled)))
        payload.setdefault("ageUncertainty", float(std_dev(scaled)))
        payload.setdefault("ageCalcTypeName", calc_name)
        payload.setdefault("ageUncertaintyTypeName", pv.error_kind)
        payload.setdefault("calculatedAgeUncertaintyTypeName", pv.error_kind)
        # Vocab is /api/arar/LUncertaintyUnit which only contains "%" and
        # "abs."; the legacy "Ma" pull from arar_constants.age_units was a
        # wrong-vocab miss. EarthBank always reports the AgeCalc uncertainty
        # in absolute units regardless of display unit.
        payload.setdefault("calculatedAgeUncertaintyTypeUnitsName", "abs.")
        payload.setdefault("nAnalysisGrouped", analysis_group.nanalyses)
        payload.setdefault("mswd", mswd)
        payload.setdefault("agepvalue", pvalue)
        payload.setdefault("preferredAge", True)
        payload.setdefault("dataInterpretationToolName", "Pychron")
        payload.setdefault(
            "description", self._analysis_group_description(analysis_group)
        )
        payload.setdefault(
            "interpretationName",
            self._interpretation_name(analysis_group, calc_name),
        )

        return self._cleanup(payload, AGE_SUMMARY_FIELDS)

    def build_sample_payload(self, analysis=None, analysis_group=None, **overrides):  # noqa: E501
        """Build a (sample_dto, location_dto) tuple from a pychron Analysis
        and/or AnalysisGroup. Names that need lookup ids stay as ``*Name``;
        ``create_sample`` resolves them."""

        sample = dict(overrides.pop("sample", {}))
        location = dict(overrides.pop("location", {}))

        if analysis is None and analysis_group is not None:
            analysis = analysis_group.analyses[0] if analysis_group.analyses else None

        if analysis is not None:
            sample.setdefault("name", getattr(analysis, "sample", None))
            sample.setdefault("sampleID", getattr(analysis, "sample", None))
            sample.setdefault(
                "materialName",
                getattr(analysis, "material", None)
                or getattr(analysis_group, "material", None),
            )
            sample.setdefault(
                "description",
                getattr(analysis, "sample_note", None)
                or self._default_comment(analysis_group)
                if analysis_group is not None
                else getattr(analysis, "sample_note", None),
            )
            lat = _to_float(getattr(analysis, "latitude", None))
            lon = _to_float(getattr(analysis, "longitude", None))
            if lat is not None:
                location.setdefault("lat", lat)
            if lon is not None:
                location.setdefault("lon", lon)
            elev = _to_float(getattr(analysis, "elevation", None))
            if elev is not None:
                sample.setdefault("referenceElevation", elev)

        if analysis_group is not None:
            funding = getattr(analysis_group, "eb_funding", None)
            literature = getattr(analysis_group, "eb_literature", None)
            if funding:
                sample.setdefault("fundingName", funding)
            if literature:
                sample.setdefault("literatureName", literature)
        sample.update(overrides)
        return sample, location

    def build_datapoint_props(self, analysis_group=None):
        """Build a list of ``{"propName", "propValue"}`` rows describing
        pychron-specific metadata that has no first-class home in the
        ArArDataPointDTO. Used by the xlsx exporter to populate the
        "Datapoint Props" sheet and (when uploading) by
        :meth:`upload_datapoint_props`.
        """

        props = []
        if analysis_group is None:
            return props

        analyses = list(getattr(analysis_group, "analyses", None) or [])
        first = analyses[0] if analyses else None

        def _add(name, value):
            if value in (None, ""):
                return
            props.append({"propName": name, "propValue": str(value)})

        if first is not None:
            _add("pychron.experiment_type", getattr(first, "experiment_type", None))
            _add("pychron.analysis_type", getattr(first, "analysis_type", None))
            _add("pychron.irradiation", getattr(first, "irradiation", None))
            _add("pychron.irradiation_level", getattr(first, "irradiation_level", None))
            _add("pychron.irradiation_position", getattr(first, "irradiation_pos", None))
            _add("pychron.extract_device", getattr(first, "extract_device", None))
            _add("pychron.monitor_name", getattr(first, "monitor_name", None))
            _add("pychron.monitor_material", getattr(first, "monitor_material", None))
            mage = getattr(first, "monitor_age", None)
            if mage is not None:
                _add("pychron.monitor_age", "{} Ma".format(mage))

        consts = getattr(analysis_group, "arar_constants", None)
        if consts is not None:
            _add("pychron.lambda_b_citation", getattr(consts, "lambda_b_citation", None))
            _add("pychron.lambda_e_citation", getattr(consts, "lambda_e_citation", None))
            _add("pychron.atm4036_citation", getattr(consts, "atm4036_citation", None))

        _add("pychron.n_analyses", len(analyses) if analyses else None)
        try:
            pv = analysis_group.get_preferred_obj("age")
            _add("pychron.preferred_age_kind", getattr(pv, "kind", None))
            _add("pychron.preferred_age_error_kind", getattr(pv, "error_kind", None))
        except Exception:
            pass
        try:
            mswd, _, _, pvalue = analysis_group.get_preferred_mswd_tuple()
            _add("pychron.mswd", mswd)
            _add("pychron.pvalue", pvalue)
        except Exception:
            pass

        return props

    def build_sample_props(self, analysis=None, analysis_group=None):
        """Pychron-specific metadata for the Sample Props sheet."""

        props = []
        if analysis is None and analysis_group is not None:
            analyses = list(getattr(analysis_group, "analyses", None) or [])
            analysis = analyses[0] if analyses else None
        if analysis is None:
            return props

        def _add(name, value):
            if value in (None, ""):
                return
            props.append({"propName": name, "propValue": str(value)})

        _add("pychron.project", getattr(analysis, "project", None))
        _add("pychron.principal_investigator",
             getattr(analysis, "principal_investigator", None))
        _add("pychron.repository", getattr(analysis, "repository_identifier", None))
        _add("pychron.material", getattr(analysis, "material", None))
        _add("pychron.lithology", getattr(analysis, "lithology", None))
        _add("pychron.grainsize", getattr(analysis, "grainsize", None))
        _add("pychron.identifier", getattr(analysis, "labnumber", None))
        return props

    def build_age_calc_payload(self, analysis_group=None, **overrides):
        payload = dict(overrides)

        if analysis_group is not None:
            payload.setdefault("comment", self._default_comment(analysis_group))
            fm_query = self._flux_monitor_from_group(analysis_group)
            if fm_query:
                payload.setdefault("fluxMonitorName", fm_query)
            consts = getattr(analysis_group, "arar_constants", None)
            if consts is not None:
                # Pychron stores raw author/year citations on ArArConstants;
                # normalize to the EarthBank controlled-vocabulary name.
                dc_citation = (
                    getattr(consts, "lambda_b_citation", None)
                    or getattr(consts, "lambda_e_citation", None)
                )
                if dc_citation:
                    payload.setdefault(
                        "decayConstantName",
                        _normalize_decay_constant(dc_citation),
                    )
                ar_citation = getattr(consts, "atm4036_citation", None)
                if ar_citation:
                    payload.setdefault(
                        "airRatioName", _normalize_air_ratio(ar_citation)
                    )

        return self._cleanup(payload, AGE_CALC_FIELDS)

    # ------------------------------------------------------------------
    # pre-flight validation — runs against public lookup endpoints only,
    # so no upload permissions are required. Useful for catching typos in
    # mineral / decay constant / interpretation before the user hand-uploads
    # the generated xlsx (or before a real POST).
    def validate_analysis_group(self, analysis_group):
        """Build every payload an upload would produce and check that each
        ``*Name`` field resolves against its lookup endpoint. Returns a list
        of ``(sheet, field, value, endpoint)`` misses. Empty list = clean."""

        analyses = list(getattr(analysis_group, "analyses", None) or [])
        if not analyses:
            return [("(none)", "analyses", None, None)]

        sheets = [
            ("ArArDataPoint",
             self.build_data_point_payload(
                 analysis_group=analysis_group, analysis=analyses[0])),
            ("ArArAgeSummary",
             self.build_age_summary_payload(analysis_group)),
            ("ArArAgeCalc",
             self.build_age_calc_payload(analysis_group)),
        ]
        s_dto, _ = self.build_sample_payload(
            analysis=analyses[0], analysis_group=analysis_group
        )
        sheets.append(("Sample", s_dto))
        for a in analyses:
            sheets.append(
                ("ArArMeasurement[{}]".format(self._aliquot_name(a)),
                 self.build_measurement_payload(analysis=a))
            )

        misses = []
        for sheet_label, payload in sheets:
            for name_key, (endpoint, id_key) in LOOKUP_ENDPOINTS.items():
                if endpoint is None:
                    continue
                if name_key not in payload:
                    continue
                if id_key in payload and payload[id_key] is not None:
                    continue
                value = payload[name_key]
                if not value:
                    continue
                # Skip endpoints whose cache failed to load (typically because
                # they require auth and no credentials are configured) —
                # otherwise pre-flight would report false misses for every
                # name on those endpoints.
                cache = self._lookup_cache.get(endpoint)
                if cache is None:
                    cache = self._load_lookup(endpoint)
                    self._lookup_cache[endpoint] = cache
                if not cache:
                    continue
                if self.lookup_id(endpoint, value) is None:
                    misses.append((sheet_label, name_key, value, endpoint))
        return misses

    # ------------------------------------------------------------------
    # high-level orchestration
    def confirm_active_user(self):
        """Show a confirmation dialog naming the active profile and target
        base_url. Returns True if the user clicks OK / yes."""

        if not self._ensure_credentials(prompt=True):
            return False
        msg = (
            "Upload to EarthBank as:\n\n"
            "  Profile: {profile}\n"
            "  User:    {user}\n"
            "  Server:  {url}\n\n"
            "Continue?"
        ).format(
            profile=self.active_profile or "<unnamed>",
            user=self.username or "<none>",
            url=self.base_url,
        )
        try:
            return bool(self.confirmation_dialog(msg, title="EarthBank Upload"))
        except Exception:
            self.warning(msg)
            return True

    def upload_analysis_group(self, analysis_group, confirm=True, **dp_overrides):
        """Push a complete ArAr record set: DataPoint, Aliquots, Measurements,
        AgeCalc, AgeSummary. Returns the created arArDataPointId or ``None``."""

        analyses = list(getattr(analysis_group, "analyses", None) or [])
        if not analyses:
            self.warning("AnalysisGroup has no analyses; nothing to upload")
            return None

        if confirm and not self.confirm_active_user():
            self.info("EarthBank upload cancelled by user")
            return None

        # Resolve the target DataPackage. Without a writable dataPackageId the
        # ArArDataPoint POST returns 500 "Package is not writable by user" and
        # every group fails identically, so fail fast with a clear message
        # rather than firing doomed requests.
        sample_label = getattr(analyses[0], "sample", None) or getattr(
            analysis_group, "sample", None
        ) or "this sample"

        package_id = dp_overrides.pop("dataPackageId", None) or self.data_package_id
        if not package_id:
            self.warning(
                "Cannot upload {s} to EarthBank: no data package has been "
                "selected. Open the EarthBank upload node (or Preferences) and "
                "use 'Select / Create Package' to choose where the data should "
                "go, then try again.".format(s=sample_label)
            )
            return None
        try:
            package_id = int(package_id)
        except (TypeError, ValueError):
            self.warning(
                "Cannot upload {s} to EarthBank: the selected data package "
                "({p!r}) is not valid. Re-select a package with 'Select / Create "
                "Package'.".format(s=sample_label, p=package_id)
            )
            return None

        # Ensure a Sample record exists; reuse if a sample with the same
        # name already lives on the server, otherwise create one.
        sample_id = dp_overrides.pop("sampleId", None)
        if sample_id is None:
            sample_id = self.find_sample_by_name(
                sample_label, data_package_id=package_id
            )
            if sample_id is None:
                s_dto, l_dto = self.build_sample_payload(
                    analysis=analyses[0], analysis_group=analysis_group
                )
                resp = self.create_sample(
                    s_dto, l_dto, short_name=sample_label, data_package_id=package_id
                )
                sample_id = self._extract_sample_id(resp)
                if sample_id is None:
                    # _request already set a friendly _last_error
                    self.warning(
                        "Upload of {s} stopped: the sample could not be saved to "
                        "EarthBank.\n\n{why}".format(
                            s=sample_label,
                            why=self._last_error or "See the log for details.",
                        )
                    )
                    return None
                self.info("created Sample id={}".format(sample_id))

        dp_payload = self.build_data_point_payload(
            analysis_group=analysis_group, analysis=analyses[0], **dp_overrides
        )
        # The Litho POST embeds the umbrella data-point, so it carries the
        # package + sample link itself — no separate create_core_data_point.
        dp_resp = self.create_data_point(
            dp_payload,
            data_package_id=package_id,
            sample_id=sample_id,
            name=sample_label,
        )
        dp_id = self._extract_id(dp_resp)
        if dp_id is None:
            self.warning(
                "Upload of {s} stopped: the analysis data point could not be "
                "saved to EarthBank.\n\n{why}".format(
                    s=sample_label,
                    why=self._last_error or "See the log for details.",
                )
            )
            return None
        self.info("created ArArDataPoint id={}".format(dp_id))

        # Sub-records: the data point is already in EarthBank, so a failure here
        # leaves an incomplete record rather than aborting. Collect any failures
        # and report them together in plain language at the end.
        failures = []

        def _step(label, resp):
            if resp is None:
                failures.append((label, self._last_error))

        seen_aliquots = set()
        for a in analyses:
            aname = self._aliquot_name(a)
            if aname in seen_aliquots:
                continue
            seen_aliquots.add(aname)
            _step(
                "aliquot {}".format(aname),
                self.create_aliquot(
                    self.build_aliquot_payload(analysis=a, arArDataPointId=dp_id)
                ),
            )

        for a in analyses:
            _step(
                "measurement {}".format(self._aliquot_name(a)),
                self.create_measurement(
                    self.build_measurement_payload(analysis=a, arArDataPointId=dp_id)
                ),
            )

        _step(
            "age calculation",
            self.create_age_calculation(
                self.build_age_calc_payload(analysis_group, arArDataPointId=dp_id)
            ),
        )
        _step(
            "age summary",
            self.create_age_summary(
                self.build_age_summary_payload(analysis_group, arArDataPointId=dp_id)
            ),
        )

        if failures:
            items = "\n".join(
                "  • {}{}".format(lbl, ": " + why if why else "")
                for lbl, why in failures
            )
            self.warning(
                "{s} was partly uploaded to EarthBank. The main data point was "
                "saved, but {n} supporting record(s) failed, so the record in "
                "EarthBank is incomplete:\n\n{items}\n\nYou can re-run the upload "
                "to retry the missing pieces.".format(
                    s=sample_label, n=len(failures), items=items
                )
            )

        return dp_id

    # ------------------------------------------------------------------
    # lookup id resolution
    def resolve_lookups(self, payload):
        """Walk payload; for any ``*Name`` field listed in LOOKUP_ENDPOINTS
        without a corresponding ``*Id``, fetch and inject the id from the
        AusGeochem lookup endpoint. Unknown names log a warning and the
        ``*Name`` field is dropped so the server doesn't reject the row."""

        if not payload:
            return payload
        out = dict(payload)
        for name_key, (endpoint, id_key) in LOOKUP_ENDPOINTS.items():
            if name_key not in out:
                continue
            if id_key in out and out[id_key] is not None:
                continue
            name = out[name_key]
            if not name:
                continue
            if endpoint is None:
                # server-side enum / no lookup endpoint; pass name through
                continue
            lookup_id = self.lookup_id(endpoint, name)
            if lookup_id is None:
                # non-fatal: field dropped, upload continues. Not surfaced as a
                # user warning (would be modal spam); hard failures are reported
                # once at the end of upload_analysis_group.
                self.debug(
                    "EarthBank lookup miss: {} = {!r} (endpoint {})".format(
                        name_key, name, endpoint
                    )
                )
                out.pop(name_key, None)
                continue
            out[id_key] = lookup_id

        # static-vocab lookups (e.g. sigma level). Resolve name -> id from the
        # map and drop the *Name field: the id is the FK the server stores, and
        # the backing table has no list endpoint to validate a name against.
        for name_key, (vocab, id_key) in STATIC_LOOKUPS.items():
            if name_key not in out:
                continue
            if id_key in out and out[id_key] is not None:
                out.pop(name_key, None)
                continue
            name = out.pop(name_key, None)
            if not name:
                continue
            vid = vocab.get(_norm_uncertainty(name))
            if vid is None:
                self.debug(
                    "EarthBank uncertainty-type miss: {} = {!r} (dropped)".format(
                        name_key, name
                    )
                )
                continue
            out[id_key] = vid
        return out

    def lookup_id(self, endpoint, name):
        """Resolve a controlled-vocabulary name to its id.

        Order of attempts:
          1. Cached exact lookup (case-insensitive)
          2. Filtered ``?name.equals=`` query — handles huge vocabs
             (e.g. /api/core/materials with 50k+ entries) where bulk
             pagination would be wasteful
          3. Bulk-load and fuzzy match by ``author_year`` substring —
             used for verbose vocabs like FluxMonitor that bury the
             citation inside a long descriptive name
        """

        q_raw = str(name).strip()
        q = q_raw.lower()

        # 1) Pre-warmed cache
        cache = self._lookup_cache.get(endpoint)
        if cache and q in cache:
            return cache[q]

        # 2) Filtered query — cheap, exact match
        rid = self._exact_lookup(endpoint, q_raw)
        if rid is not None:
            # remember it
            self._lookup_cache.setdefault(endpoint, {})[q] = rid
            return rid

        # 3) Bulk + fuzzy fallback (only useful for small vocabs that fit in
        # a single page; otherwise the cache is partial and fuzzy hits are
        # best-effort)
        if cache is None:
            cache = self._load_lookup(endpoint)
            self._lookup_cache[endpoint] = cache
        if not cache:
            return None
        if q in cache:
            return cache[q]
        author_year = _citation_key(name)
        if not author_year or "_" not in author_year:
            return None
        author, _, year = author_year.rpartition("_")
        for label, rid in cache.items():
            if author in label and year in label:
                return rid
        return None

    def _exact_lookup(self, endpoint, name):
        """Filtered query → case-insensitive exact match. Returns id or
        ``None``.

        Strategy:
          1. ``?name.equals=<name>`` (server is case-sensitive but exact)
          2. ``?name.equals=<Capitalized>`` — common EarthBank convention
          3. ``?name.contains=<name>&size=200`` then post-filter for the
             single row whose ``name`` matches case-insensitively
        """

        require_auth = bool(self.username and self.password)
        name = name.strip()
        target = name.lower()

        def _get(params):
            resp = self._request(
                "get", endpoint, require_auth=require_auth, params=params
            )
            if resp is None:
                return None
            try:
                return resp.json()
            except ValueError:
                return None

        for candidate in (name, name[:1].upper() + name[1:].lower()):
            rows = _get({"name.equals": candidate, "size": 1})
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                rid = rows[0].get("id")
                if rid is not None and str(rows[0].get("name", "")).strip().lower() == target:
                    return rid

        rows = _get({"name.contains": name, "size": 200})
        if not isinstance(rows, list):
            return None
        for r in rows:
            if not isinstance(r, dict):
                continue
            if str(r.get("name", "")).strip().lower() == target:
                return r.get("id")
        return None

    def _load_lookup(self, endpoint):
        # Pull all rows; jhipster endpoints honor size=2000 well enough for
        # these short controlled vocabularies. ArAr lookups are public, but
        # /api/core/L* lookups need auth — use auth if we have it, otherwise
        # try anonymously so the cache still warms partially.
        require_auth = bool(self.username and self.password)
        resp = self._request(
            "get", endpoint, require_auth=require_auth, params={"size": 2000}
        )
        if resp is None:
            return None
        try:
            rows = resp.json()
        except ValueError:
            return None
        if not isinstance(rows, list):
            return None
        cache = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            rid = row.get("id")
            if rid is None:
                continue
            for key in ("name", "reference", "description"):
                val = row.get(key)
                if val:
                    cache.setdefault(str(val).strip().lower(), rid)
        return cache

    # ------------------------------------------------------------------
    # transport
    def _post_json(self, path, dto):
        payload = self._cleanup(dto)
        if not payload:
            self.warning("EarthBank payload for {} is empty; skipping".format(path))
            return None
        payload = self.resolve_lookups(payload)
        return self._post_raw(path, payload)

    def _post_raw(self, path, payload):
        if not payload:
            self.warning("EarthBank payload for {} is empty; skipping".format(path))
            return None
        resp = self._request(
            "post",
            path,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        if resp is None or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text

    # ------------------------------------------------------------------
    # human-friendly error reporting
    #
    # Path fragment -> plain-English name of the thing being saved. Used so an
    # error can say "your sample" instead of "/api/core/sample-with-locations".
    _RECORD_NAMES = (
        ("sample-with-locations", "sample"),
        ("ArArDataPoint", "analysis data point"),
        ("ArArAliquot", "aliquot"),
        ("ArArMeasurement", "measurement"),
        ("ArArAgeCalc", "age calculation"),
        ("ArArAgeSummary", "age summary"),
        ("data-packages", "data package"),
        ("data-points", "data-point link"),
    )

    def _friendly_record(self, path):
        for frag, label in self._RECORD_NAMES:
            if frag in path:
                return label
        return "record"

    @staticmethod
    def _constraint_field(detail):
        """Pull a readable field name out of a Postgres FK/constraint error."""
        m = re.search(r"Key \(([a-z0-9_]+?)(?:_id)?\)", detail)
        if not m:
            m = re.search(r"constraint \"fk_[a-z0-9]+?_([a-z0-9_]+?)_id", detail)
        if not m:
            return None
        return m.group(1).replace("_", " ").strip()

    def _humanize_error(self, status, text, path):
        """Translate an EarthBank/JHipster error body into a message a
        geochronologist (not a programmer) can act on. The raw body is still
        logged via debug for troubleshooting."""

        what = self._friendly_record(path)
        detail = ""
        try:
            j = json.loads(text)
            detail = (
                j.get("detail") or j.get("message") or j.get("title") or ""
            ).strip()
        except (ValueError, AttributeError):
            detail = (text or "").strip()
        low = detail.lower()
        pkg = self.data_package_id or "the selected package"

        if "not writable" in low or (status == 500 and "package" in low):
            return (
                "Cannot upload the {what}: your EarthBank account does not have "
                "write access to data package {pkg}. Use 'Select / Create "
                "Package' to choose a package you own or create a new one, then "
                "upload again.".format(what=what, pkg=pkg)
            )
        if status in (401, 403):
            return (
                "EarthBank rejected your login while uploading the {what}. Check "
                "your EarthBank username and password in Preferences, and that "
                "your account has permission to upload.".format(what=what)
            )
        if status == 404:
            return (
                "EarthBank could not find the upload service for the {what}. The "
                "server address is probably wrong — check the Base URL in "
                "Preferences (it should be "
                "https://ausgeochem.auscope.org.au).".format(what=what)
            )
        if (
            "constraint" in low
            or "not present in table" in low
            or "foreign key" in low
        ):
            field = self._constraint_field(detail)
            fld = " ('{}')".format(field) if field else ""
            return (
                "EarthBank did not recognise one of the values in the {what}{fld}. "
                "This is usually a term that does not match EarthBank's standard "
                "list (mineral, flux monitor, uncertainty type, etc.). Check that "
                "field and try again.".format(what=what, fld=fld)
            )
        if status >= 500:
            return (
                "EarthBank had a server problem while saving the {what}. This is on "
                "EarthBank's side — wait a moment and try again, or contact "
                "support@lithodat.com if it keeps happening.".format(what=what)
            )
        # generic 4xx: show the cleaned server detail if we have one
        clean = re.split(r";|nested exception", detail)[0].strip() if detail else ""
        if clean:
            return "EarthBank rejected the {what}: {clean}".format(
                what=what, clean=clean
            )
        return "EarthBank rejected the {what} (HTTP {status}).".format(
            what=what, status=status
        )

    def _request(self, method, path, require_auth=True, **kw):
        url = self._url(path)
        headers = kw.pop("headers", {})
        timeout = kw.pop("timeout", 30)

        if require_auth:
            token = self._ensure_token()
            if not token:
                return
            headers.setdefault("Authorization", "Bearer {}".format(token))

        try:
            resp = self._session.request(
                method, url, headers=headers, timeout=timeout, **kw
            )
        except requests.RequestException as exc:
            self.debug("EarthBank request error ({} {}): {}".format(method, path, exc))
            # set _last_error only; the calling flow surfaces one rich message
            # to the user (avoids a modal per failed request).
            self._last_error = (
                "Could not reach EarthBank at {}. Check your internet connection "
                "and the Base URL in Preferences.".format(self.base_url)
            )
            return

        if resp.status_code == 401 and require_auth:
            self.debug("Token expired, refreshing and retrying request")
            self._token = None
            token = self._ensure_token()
            if not token:
                return
            headers["Authorization"] = "Bearer {}".format(token)
            try:
                resp = self._session.request(
                    method, url, headers=headers, timeout=timeout, **kw
                )
            except requests.RequestException as exc:
                self.debug("EarthBank retry failed ({}): {}".format(path, exc))
                self._last_error = (
                    "Lost the connection to EarthBank at {} while retrying. Try "
                    "again in a moment.".format(self.base_url)
                )
                return

        if not resp.ok:
            # raw body for troubleshooting; friendly message for the user
            self.debug(
                "EarthBank {} {} -> {}: {}".format(
                    method.upper(), path, resp.status_code, resp.text
                )
            )
            self._last_error = self._humanize_error(
                resp.status_code, resp.text, path
            )
            return

        return resp

    def _ensure_token(self):
        if self._token:
            return self._token

        if not self._ensure_credentials(prompt=True):
            self.warning("EarthBank credentials are not configured")
            return

        payload = {
            "username": self.username,
            "password": self.password,
            "rememberMe": False,
        }
        url = self._url("/api/authenticate")
        try:
            resp = self._session.post(url, json=payload, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            self.warning("EarthBank authentication failed: {}".format(exc))
            return

        token = resp.json().get("id_token")
        if not token:
            self.warning("EarthBank authentication response did not include a token")
            return

        self._token = token
        return token

    def _bind_preferences(self):
        prefid = "pychron.ausgeochem"
        bind_preference(self, "profiles_json", "{}.profiles_json".format(prefid))
        bind_preference(self, "active_profile", "{}.active_profile".format(prefid))

    def _url(self, path):
        if path.startswith("http"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        return "{}{}".format(self.base_url.rstrip("/"), path)

    # ------------------------------------------------------------------
    # helpers
    @staticmethod
    def _cleanup(payload, fields=None):
        if not payload:
            return {}
        cleaned = {k: v for k, v in payload.items() if v not in (None, "")}
        # coerce any stray uncertainties (ufloat/AffineScalarFunc) to their
        # nominal float — they are not JSON serializable and must never reach
        # the request body.
        for k, v in cleaned.items():
            if isinstance(v, AffineScalarFunc):
                cleaned[k] = float(nominal_value(v))
        if fields:
            allowed = set(fields)
            cleaned = {k: v for k, v in cleaned.items() if k in allowed}
        return cleaned

    @staticmethod
    def _extract_id(resp):
        if isinstance(resp, dict):
            return resp.get("id")
        return None

    @staticmethod
    def _extract_sample_id(resp):
        if not isinstance(resp, dict):
            return None
        inner = resp.get("sampleDTO") or resp.get("sample") or {}
        return inner.get("id") if isinstance(inner, dict) else resp.get("id")

    @staticmethod
    def _aliquot_name(analysis):
        labnum = getattr(analysis, "labnumber", "") or ""
        aliquot = getattr(analysis, "aliquot", "")
        step = getattr(analysis, "step", "") or ""
        if labnum and aliquot:
            base = "{}-{:02d}".format(labnum, int(aliquot))
        else:
            base = labnum or "aliquot"
        return "{}{}".format(base, step)

    @staticmethod
    def _step_to_num(step):
        if step in (None, ""):
            return None
        try:
            return float(step)
        except (TypeError, ValueError):
            # alphabetical step: A->1, B->2, ...
            s = str(step).strip().upper()
            if len(s) == 1 and s.isalpha():
                return float(ord(s) - ord("A") + 1)
        return None

    @staticmethod
    def _format_date(analysis):
        dt = getattr(analysis, "rundate", None)
        if dt is None:
            ts = getattr(analysis, "timestamp", None)
            if isinstance(ts, datetime):
                dt = ts
            elif isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(ts)
        if dt is None:
            return None
        try:
            return dt.strftime("%Y-%m-%d")
        except (AttributeError, ValueError):
            return None

    @staticmethod
    def _format_datetime(analysis):
        dt = getattr(analysis, "analysis_timestamp", None) or getattr(
            analysis, "rundate", None
        )
        if dt is None:
            ts = getattr(analysis, "timestamp", None)
            if isinstance(ts, datetime):
                dt = ts
            elif isinstance(ts, (int, float)):
                dt = datetime.fromtimestamp(ts)
        if dt is None:
            return None
        try:
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (AttributeError, ValueError):
            return None

    @staticmethod
    def _analysis_scale_name(analysis_group):
        if analysis_group is None:
            return None
        n = analysis_group.nanalyses if analysis_group.nanalyses else 0
        if n == 1:
            return "Single Grain"
        if n > 1:
            return "Multi-Grain Aliquot"
        return None

    @staticmethod
    def _analysis_comment(analysis):
        parts = []
        for attr in ("sample_note", "sample_prep_comment"):
            val = getattr(analysis, attr, None)
            if val:
                parts.append(val)
        return "; ".join(parts) if parts else None

    @staticmethod
    def _parse_grain_size(grainsize):
        if not grainsize:
            return None, None
        values = [float(v) for v in re.findall(r"[0-9]+\.?[0-9]*", str(grainsize))]
        if not values:
            return None, None
        if len(values) == 1:
            return values[0], values[0]
        return min(values), max(values)

    @staticmethod
    def _default_comment(analysis_group):
        sample = getattr(analysis_group, "sample", None)
        project = getattr(analysis_group, "project", None)
        if sample and project:
            return "{} ({})".format(sample, project)
        return sample or None

    @staticmethod
    def _analysis_group_description(analysis_group):
        pieces = []
        sample = getattr(analysis_group, "sample", None)
        project = getattr(analysis_group, "project", None)
        comments = getattr(analysis_group, "comments", None)
        if sample:
            pieces.append("Sample {}".format(sample))
        if project:
            pieces.append("Project {}".format(project))
        if comments:
            pieces.append(comments)
        return "; ".join(pieces) if pieces else None

    @staticmethod
    def _flux_monitor_from_group(analysis_group):
        """Compose a fluxMonitor lookup query from irradiation-supplied
        monitor info on the analyses, preferring the irradiation-level
        attribution over the AnalysisGroup-level ``monitor_info`` tuple
        (which loses the monitor *name*).

        Resolution order:
          1. AnalysisGroup-level ``eb_flux_monitor`` (user override from node)
          2. First analysis with ``monitor_reference`` set -> compose
             ``"{monitor_name} {monitor_reference}"`` so fuzzy lookup can
             match an EarthBank entry like
             "Alder Creek Rhyolite Sanidine (ACs) from Phillips et al. 2022"
          3. Legacy ``analysis_group.monitor_info`` tuple
        """

        # 1) explicit override
        forced = getattr(analysis_group, "eb_flux_monitor", None)
        if forced:
            return str(forced)

        # 2) irradiation-supplied monitor info on the analyses
        analyses = getattr(analysis_group, "analyses", None) or []
        for a in analyses:
            ref = getattr(a, "monitor_reference", None)
            name = getattr(a, "monitor_name", None)
            if ref or name:
                parts = []
                if name and str(name).strip():
                    parts.append(str(name).strip())
                if ref and str(ref).strip():
                    parts.append(str(ref).strip())
                if parts:
                    return " ".join(parts)

        # 3) legacy tuple
        return _flux_monitor_query(getattr(analysis_group, "monitor_info", None))

    @staticmethod
    def _interpretation_name(analysis_group, calc_name):
        # honor explicit user override (set by AusGeochemNode editor)
        forced = getattr(analysis_group, "eb_interpretation", None)
        if forced:
            return forced
        # Default to "Unknown" — a valid LArArInterpretation entry. The
        # node editor lets the user pick a specific interp per group.
        return "Unknown"


# ============= EOF =============================================
