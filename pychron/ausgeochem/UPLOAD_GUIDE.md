# Uploading ⁴⁰Ar/³⁹Ar data to EarthBank

A step-by-step guide for getting your analysis results from Pychron into
**EarthBank** (the AuScope data platform at
<https://ausgeochem.auscope.org.au>). No programming needed.

There are two ways to publish:

- **Direct upload** — Pychron sends your data straight to EarthBank over the
  internet. Needs an EarthBank account with upload permission. This is the
  main path and the rest of this guide.
- **Export to spreadsheet** — Pychron writes AusGeochem's Excel templates and
  you upload them yourself through the EarthBank website. Needs no account in
  Pychron. See [Export to a spreadsheet instead](#export-to-a-spreadsheet-instead).

---

## Before you start

You need three things:

1. **An EarthBank account** (username + password). If you don't have one,
   request it from **support@lithodat.com**.
2. **Upload (write) permission** on at least one **data package**. A data
   package is the folder your data lives in on EarthBank. Your account must
   be an *editor* or *supervisor* of it. You can also create a new package
   from inside Pychron (you automatically become its supervisor).
3. **Your institution id** (a number). University of Melbourne is `193203`.
   If you don't know yours, ask your EarthBank administrator — it's only
   used to filter the package list and to stamp new packages.

> **What is a data package?** Everything you upload — samples, data points,
> ages — is stored inside one data package. You must choose a package you are
> allowed to write to. If you pick one you don't own, EarthBank will refuse
> the upload with a clear message.

---

## One-time setup

Do this once per computer (or per EarthBank account).

1. Open **Preferences → AusGeochem → EarthBank Credentials**.
2. Click **Add Profile**. Fill in:
   - **Profile** — any name you like (e.g. `umelb`).
   - **Base URL** — leave as `https://ausgeochem.auscope.org.au`.
   - **Username** / **Password** — your EarthBank login.
   - **Institution Id** — e.g. `193203` for the University of Melbourne.
   - **Data Package Id** — leave blank for now; you'll set it in the next
     step.
3. Set **Active Profile** to the profile name you just created.
4. Click **Test Selected**. You should see `[OK]`. If you see `[FAIL]`,
   re-check the username and password.
5. Click **Select / Create Package**. A window lists the data packages at
   your institution. Either:
   - **pick an existing package** you have permission to write to, or
   - type a name in the **New name** box and click **Create Package** — you
     become its supervisor, so it is always writable.

   Click **OK**. The chosen package is saved as your profile's default.

Your password is stored securely by your operating system (Keychain on
macOS, Credential Locker on Windows) — never in plain text.

---

## Uploading from a pipeline

1. Build or open a pipeline and select the analyses you want to publish.
2. Add the **AusGeochem EarthBank** node.
3. In the node window:
   - Set **Action** to **Upload to EarthBank**.
   - Check the **Data package** shown at the top. If it's wrong or missing,
     click **Select / Create Package** to choose one for this run.
   - In the **Analysis Groups** table, review each sample and set:
     - **Interpretation** (e.g. age of crystallization) — required.
     - **Flux Monitor** override — optional.
     - **Funding** / **Literature** — optional.
   - Leave **Confirm active user before upload** ticked if you want a final
     "upload as <you>?" prompt.
4. Click **OK** to run.

Pychron groups your selected analyses by sample. For each sample it uploads,
in order:

- the **sample** record (created once, or reused if it already exists in
  that package),
- the **analysis data point**,
- one **aliquot** per aliquot and one **measurement** per analysis,
- the **age calculation** and **age summary**.

When it finishes, the log shows the new EarthBank id for each data point.

---

## Choosing or creating a data package

You can set the package in two places:

- **Preferences** (see setup above) — sets your *default* package, used
  every time unless you override it.
- **The upload node** — click **Select / Create Package** to choose a
  package just for that run.

The picker only lists packages at your configured institution. Write
permission isn't shown in the list, so if you choose a package you don't own,
the upload will stop with a message telling you to pick another. Creating a
new package always gives you write access.

---

## If something goes wrong

Pychron shows a plain-language message and keeps the details in the log.
The common ones:

| Message | What it means | What to do |
|---|---|---|
| "…does not have write access to data package …" | You picked a package you can't write to. | Use **Select / Create Package** to choose one you own, or create a new one. |
| "…no data package has been selected." | No package is set. | Set one in Preferences or the node via **Select / Create Package**. |
| "…rejected your login…" | Wrong username/password, or your account lacks upload rights. | Re-check credentials in Preferences (**Test Selected**). If they're right, ask support@lithodat.com about upload permission. |
| "…could not find the upload service… check the Base URL…" | The server address is wrong. | In Preferences, set Base URL to `https://ausgeochem.auscope.org.au`. |
| "…did not recognise one of the values… (e.g. mineral, flux monitor, uncertainty type)…" | A Pychron term doesn't match EarthBank's standard list. | Check that field (often the flux monitor or mineral name) and try again. Run **Pre-flight check** to find these in advance. |
| "…was partly uploaded… supporting record(s) failed…" | The data point saved but some aliquots/measurements/ages didn't. | Read the listed items, fix the cause, and **re-run the upload** — it retries the missing pieces. |
| "Could not reach EarthBank…" | No connection to the server. | Check your internet and the Base URL. |

---

## Check before you upload (Pre-flight)

To catch problems without writing anything to EarthBank, set the node's
**Action** to **Pre-flight check (no write)** and run it. Pychron builds the
same data and checks every controlled term (mineral, interpretation, flux
monitor, decay constant, …) against EarthBank's lists, then reports anything
it couldn't match. Fix those, then switch back to **Upload**.

---

## Export to a spreadsheet instead

If you'd rather upload through the EarthBank website (or don't have an upload
account yet):

1. In the node, set **Action** to **Export to xlsx (no upload)**.
2. Choose an output folder and options (one workbook per sample, include the
   Sample workbook, etc.).
3. Click **OK**. Pychron writes the AusGeochem `ArArDataPoint` and `Sample`
   template workbooks.
4. Log in to <https://ausgeochem.auscope.org.au> and import the workbooks
   through the website.

---

## Getting help

- **Account or permissions** (login, write access, packages): your EarthBank
  administrator, or **support@lithodat.com**.
- **Pychron behaviour** (the node, errors, exports): your local Pychron
  maintainer. When reporting a problem, copy the message shown and, if you
  can, the extra detail from the Pychron log.
