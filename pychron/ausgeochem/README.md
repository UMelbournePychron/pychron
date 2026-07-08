# pychron.ausgeochem — EarthBank integration

Pychron plugin for publishing ⁴⁰Ar/³⁹Ar data to **EarthBank** (the
public-facing brand for the AusGeochem / LithoSurfer data platform). The
active AuScope host is <https://ausgeochem.auscope.org.au>.

> **Uploading data?** End-user, step-by-step instructions live in
> [UPLOAD_GUIDE.md](UPLOAD_GUIDE.md). This README is the developer reference.

Two output paths are supported and share a common payload-building core:

| Mode | What happens | Auth required |
|---|---|---|
| **Upload** | POSTs payloads directly to the EarthBank v2 REST API | yes, write perms + a writable `dataPackageId` |
| **Export xlsx** | Writes the AusGeochem-supplied `ArArDataPoint` + `Sample` template workbooks; user uploads via the web UI | no |
| **Pre-flight** | Builds the same payloads and probes every `*Name` vocab against the public lookup endpoints, reports unresolved values | no (auth helpful for `/api/core/L*`) |

A standalone `EarthBank Login...` action and per-profile **Test Selected**
button (in the AusGeochem preferences pane) let you validate credentials
before running anything.

---

## Quick start

1. Open **Preferences → AusGeochem → EarthBank Credentials**.
2. Click **Add Profile**, fill in `name`, `base_url`
   (`https://ausgeochem.auscope.org.au`), `username`, `password`,
   `institution_id` (e.g. `193203` = University of Melbourne), and
   `data_package_id`.
3. Set **Active Profile** to the profile name.
4. (Optional) Click **Test Selected** to verify the credentials. The
   password is stored in the OS keyring (or an encrypted file fallback —
   see [Credential storage](#credential-storage)).
5. Click **Select / Create Package** to pick or create the writable data
   package uploads go into (sets `data_package_id`). Every write must target
   a package the account can write, or the server returns
   `500 "Package is not writable by user."`.
6. In a pipeline, add the **AusGeochem EarthBank** node. Confirm the data
   package (or set it per-run with **Select / Create Package**), configure
   per-group `interpretation`, optional `flux_monitor` override, and
   choose **Upload**, **Export xlsx**, or **Pre-flight check**.

---

## Module layout

| File | Purpose |
|---|---|
| `earthbank_service.py` | HTTP client, payload builders, lookup-id resolver, orchestration |
| `xlsx_exporter.py` | Render payloads into the bundled AusGeochem templates |
| `credentials_store.py` | Three-layer credential storage (keyring → Fernet file → memory) |
| `credentials_dialog.py` | Modal login dialog with profile picker |
| `data_package_dialog.py` | Select-or-create data package picker (institution-scoped) |
| `templates/` | Bundled AusGeochem `ArArDataPoint_Template2026.xlsx` and `Sample_Template_v2025-04-16.xlsx` |
| `tasks/preferences.py` | Multi-profile preferences pane |
| `tasks/actions.py` | Menu actions (Login, Test Connection) |
| `tasks/node.py` | `AusGeochemNode` — pipeline node with editor for per-group overrides |
| `tasks/ausgeochem_plugin.py` | Envisage plugin wiring |
| `tests/integration_test.py` | Smoke + full integration tests against the live API |
| `tests/xlsx_export_test.py` | Verifies exported workbooks match the HW reference structure |
| `tests/find_sample_scope_test.py` | Offline: sample lookup is scoped to the target package |
| `tests/packages_probe.py` | Diagnostic: list packages / account / writable candidates |
| `tests/live_upload_test.py` | Full-chain live upload of a fixture AnalysisGroup |
| `tests/arar_post_probe.py` | Diagnostic: how the ArArDataPoint POST accepts its package |

---

## Credential storage

The service NEVER serializes the password into `pychron.ausgeochem.ini`.
Profiles persist `name`, `base_url`, `username`, `data_package_id`, and
`institution_id` there (all non-secret); the password lives in the most
secure backend available on the host:

1. **OS keyring** (macOS Keychain, Windows Credential Locker, Linux
   Secret Service) when the `keyring` package finds a real backend.
2. **Encrypted file** (`cryptography.fernet`) at
   `<pychron-appdata>/.appdata/earthbank_credentials.enc` with key in
   `earthbank.key`, both chmod 0600. Used when no OS keyring is
   available (headless Linux, CI).
3. **Process memory** (last resort, warns the user).

`credentials_store.backend_name()` returns a diagnostic label
(`keyring:keyring.backends.macOS`, `file:fernet`, `memory`).

---

## EarthBank API surface

Endpoints used (all under `https://ausgeochem.auscope.org.au`):

| Path | Verb | Purpose |
|---|---|---|
| `/api/authenticate` | POST | Username/password → JWT id_token |
| `/api/account` | GET | Auth ping (test_connection) + current user |
| `/api/arar/ArArDataPoint` | POST | Create ArAr datapoint as an `ArArDataPointLithoDTO` wrapper — see below (returns id) |
| `/api/arar/ArArMeasurement` | POST | Per-analysis measurement row (flat DTO) |
| `/api/arar/ArArAliquot` | POST | Per-aliquot row (flat DTO) |
| `/api/arar/ArArAgeSummary` | POST | Group-level age summary (flat DTO) |
| `/api/arar/ArArAgeCalc` | POST | Decay constant / air ratio / flux monitor refs (flat DTO) |
| `/api/core/sample-with-locations` | POST/GET | Sample + Location wrapper (carries `dataPackageId`) |
| `/api/management/data-packages` | GET/POST/DELETE | List / create (`DataPackageLithoDTO`) / delete data packages |
| `/api/arar/L*`, `/api/core/l-*`, `/api/core/materials` | GET | Controlled-vocabulary lookups |

**ArArDataPoint POST shape.** The body is an `ArArDataPointLithoDTO`:
`dataPointDTO` (the umbrella record — carries `dataPackageId`, `sampleId`,
`dataStructure="ARARDATAPOINT"`, `name`) plus `extendingDataPointDTO` (the
ArAr fields). Posting the flat ArAr DTO with no `dataPointDTO` is rejected
`500 "Package is not writable by user."` because the server resolves the
package from the umbrella. This one POST also creates the core data-point and
links the sample — there is **no** separate `/api/core/data-points` call.
Its top-level `id` is the `arArDataPointId` used by aliquots/measurements.

Swagger requires a bearer token and a group: `GET /swagger-resources` lists
the groups, then e.g.
`GET /v2/api-docs?group=16 ArAr` (or `02 Management`, `03 Core Model`).

---

## Payload pipeline

Per `AnalysisGroup`, in order (aborts early with a friendly message if the
`dataPackageId` is missing/invalid or the sample/data-point POST fails):

```
resolve dataPackageId (override → active profile)
                              │
find_sample_by_name(sample, dataPackageId) ──┐   # scoped to the package
                              ▼
       create_sample(..., dataPackageId) ── sampleId   # created or reused
                              │
       create_data_point(ext, dataPackageId, sampleId, name) ─ arArDataPointId
         └─ POSTs the ArArDataPointLithoDTO wrapper; the embedded
            dataPointDTO creates the core data-point + sample link inline
                              │
       create_aliquot()   x N (unique aliquot names)
       create_measurement() x N (one per analysis)
       create_age_calculation()
       create_age_summary()
```

Sub-record failures (after the data point exists) don't abort — they're
collected and reported together as a "partly uploaded" message; re-running
retries the missing pieces.

For xlsx export, the same builders run but the payloads are written into
the corresponding template sheets using each row's apiField as the column
map. Foreign keys flow through `datapointName` instead of integer ids
(EarthBank resolves them server-side on import).

---

## Lookup-ID resolution

Any `*Name` field listed in `LOOKUP_ENDPOINTS` is converted to its
`*Id` before submission via three strategies, in order:

1. **Cached exact** — pre-warmed dict, case-insensitive
2. **Filtered query** — `?name.equals=<name>`, then `?name.equals=<Capitalized>`,
   then `?name.contains=<name>&size=200` with case-insensitive
   exact post-filter (handles the 50k-entry `materials` table without
   bulk-paginating)
3. **Bulk fuzzy** — load all entries, parse `author_year` from the
   query, return the first entry whose `name`/`reference` contains both
   tokens. Useful for verbose vocabs like `FluxMonitor` whose entries
   look like *"Alder Creek Rhyolite Sanidine (ACs) from Phillips et al.
   2022 (1.1834 Ma)"*.

Unresolved `*Name` values trigger a `warning` and the field is dropped
from the outgoing payload (so the server doesn't 400 on the row).

---

## Pychron → EarthBank value mapping

A handful of pychron attributes are remapped to EarthBank vocabulary:

| Pychron source | EarthBank field | Logic |
|---|---|---|
| `analysis.step` + `extract_value` | `arMethodName` | step suffix + extract ≤ 50 → `Step-heating - laser`; step + ≥ 300 → `Step-heating - furnace`; no step → `Total fusion - laser` |
| `arar_constants.lambda_b_citation` | `decayConstantName` | normalized via `DECAY_CONSTANT_VOCAB` (e.g. `Min (2008)` → `Min et al. 2000`) |
| `arar_constants.atm4036_citation` | `airRatioName` | normalized via `AIR_RATIO_VOCAB` (`Nier (1950)` → `Nier 1950`) |
| `analysis.monitor_name` + `analysis.monitor_reference` | `fluxMonitorName` | composed `"{name} {ref}"`; fuzzy-resolved against FluxMonitor vocab |
| `analysis.is_plateau_step` | `plateauStep` | `"Yes"` when true |
| `analysis.grainsize` | `grainDiameterMin/Max` | parsed via regex (`"75-150 um"` → 75 / 150) |
| `analysis.rundate` / `analysis_timestamp` | `analysisDate` / `analysisTime` | `YYYY-MM-DD` / `YYYY-MM-DDTHH:MM:SSZ` |
| `analysis_group.eb_interpretation` | `interpretationName` | user override from node editor; default `"Unknown"` |
| `analysis_group.eb_flux_monitor` | `fluxMonitorName` | user override from node editor |
| error-kind (`SE`/`SEM`/`SD`/`MSEM`, `1 sigma`, …) | `*UncertaintyTypeId` | resolved by the static `UNCERTAINTY_TYPE_VOCAB` → `l_uncertainty` id (all 1-sigma-level estimators → `1`, `2 sigma` → `2`). NOT `/api/core/l-error-types` (wrong table — its ids violate the ArArDataPoint FK). Unit (`abs.`/`%`) still resolves via `/api/arar/LUncertaintyUnit`. |

---

## xlsx exporter

```python
from pychron.ausgeochem.xlsx_exporter import EarthBankXlsxExporter

exp = EarthBankXlsxExporter()                       # bind=False, no network
exp.export_analysis_group(ag, "out.xlsx")           # single group
exp.export_analysis_groups([(ag1, None), (ag2, "datapoint-2")], "batch.xlsx")
exp.export_sample(ag, "sample.xlsx")
exp.export_samples([ag1, ag2], "samples_batch.xlsx")
```

The bundled templates carry the AusGeochem header rows (description /
type / human label / apiField); data rows start at spreadsheet row 5.
Each builder runs through the same `_resolve_value` translator so
service `*Name` fields land in the right `*` template column.

Template column structure is verified against the lab's HW reference
upload files in `tests/xlsx_export_test.py`.

---

## Pre-flight check

```python
svc = AusGeochemEarthBankService(bind=False)
misses = svc.validate_analysis_group(ag)
for sheet, field, value, endpoint in misses:
    print(f"{sheet}: {field} = {value!r} (vs {endpoint})")
```

Runs every payload builder and probes the lookup endpoints (skipping any
endpoint whose cache fails to load — typical for the auth-only
`/api/core/L*` ones when no credentials are set, to avoid false misses).

Available as **Pre-flight check (no write)** in the AusGeochem node.

---

## Integration tests

Anonymous smoke (no creds, public lookups only):
```bash
python -m pychron.ausgeochem.tests.integration_test --smoke
```

Full live test (requires write perms; no sandbox host is advertised by the
vendor). Credentials can go in a gitignored `pychron/ausgeochem/.env`
(`EARTHBANK_USER`, `EARTHBANK_PASS`, `EARTHBANK_DATA_PACKAGE_ID`) — the tests
load it automatically — or as environment variables:
```bash
EARTHBANK_USER=... EARTHBANK_PASS=... \
EARTHBANK_DATA_PACKAGE_ID=... \
EARTHBANK_URL=https://ausgeochem.auscope.org.au \
python -m pychron.ausgeochem.tests.integration_test
```

Offline unit test (no network) for package-scoped sample lookup:
```bash
python -m pychron.ausgeochem.tests.find_sample_scope_test
```

xlsx-export verification (compares output column structure against HW
reference files on user's Google Drive):
```bash
python -m pychron.ausgeochem.tests.xlsx_export_test
```

---

## Known limitations

- **No sandbox** — vendor does not publish a non-production host.
  Production writes require credentials + a writable data package, granted
  via `support@lithodat.com` / your EarthBank administrator.
- **Write permission is not visible via the API** — a data package's DTO
  exposes only editor/supervisor *counts*, and `/api/account.id` differs
  from `dataPackageDTO.createdById`. The package picker therefore scopes by
  institution and lets the server reject a non-writable choice at upload.
- **`funding` / `literature`** template columns are not yet populated
  (`/api/core/fundings` and `/api/core/literature` lookups would need
  wiring).
- **`Datapoint Props` / `Sample Props`** template sheets are left blank.
- **Materials lookup** uses single-shot filtered queries instead of
  caching all 53k rows; fuzzy matches there are not supported (only
  case-insensitive exact).
- **Pychron AnalysisGroup batching** — pipeline state arrives as a flat
  analysis list. The node groups by `analysis.sample` to form
  AnalysisGroups; mixed-sample selections produce one ArArDataPoint per
  sample.

---

## Vendor docs

- API license: <https://docs.google.com/document/d/e/2PACX-1vTyOIVPHtIUBJIuaMCkm9gG31GPEaKiIRW4GibzfgDGG-6JCh1rf8cX7CA6WYBJqUmCNST03-ORt680/pub>
- Swagger UI: <https://ausgeochem.auscope.org.au/v2/swagger-ui/swagger-ui.html>
  (requires login; grouped — see the API-surface note above)
- Support / write access: `support@lithodat.com`
