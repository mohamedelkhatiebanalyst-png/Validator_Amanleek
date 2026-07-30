
# Amanleek Utilization File Validator

A Streamlit app that validates client-utilization Excel files before they are uploaded to Zoho WorkDrive.

## Project structure

```text
app.py                         Main Streamlit application
amanleek_validator/            Application source package
config/schema.json             Validation schema and column rules
tests/                         Automated regression tests
scripts/single_validator.py    Optional single-file-only entrypoint
docs/                          Architecture and client documentation
data/                          Local reference data (ignored by Git)
requirements.txt               Runtime dependencies
```

The app uses a left sidebar with three pages:

- **Guide:** simple instructions and visual workflows for new users.
- **Single-file validation:** validation, repair, and in-memory download workflow.
- **Batch check:** an open comparison of multiple workbooks' sheet structures
  and exact column order.

The **Single-file validation** page includes an `All_in_one_2026` download
button. It generates `All_in_one_2026.xlsx` with one worksheet named `sheet1`
and all 40 approved columns in their exact canonical order.

For batch mismatches, the app reports missing and unexpected column names. If all names exist but their sequence differs, it reports the first incorrect column position.

## What the batch validator checks

The first readable uploaded workbook becomes the reference. Every other workbook is checked for:

- whether it can be opened as an `.xlsx` workbook;
- worksheet count;
- worksheet names;
- worksheet sequence and order;
- column count in every worksheet;
- first-row column names;
- exact column spelling and capitalization;
- exact column order;
- missing columns;
- unexpected or extra columns;
- repeated missing-column occurrences caused by duplicate headers;
- the first incorrect position when all column names exist but are reordered.

The batch validator does **not**:

- validate individual cell values or data rows;
- check whether the reference workbook follows the approved Amanleek schema;
- repair, rename, or reorder uploaded batch files;
- store original batch files on the server;
- modify uploaded workbooks.

The batch page is comparison-only. It reports whether every uploaded workbook
has the same worksheet structure and does not combine or modify files.

## Validation rules

- Accepts `.xlsx` only.
- Requires exactly one worksheet named `sheet1`.
- Offers a pending repair button when a single worksheet needs to be renamed to `sheet1`.
- Requires the header on row 1.
- Requires all 40 approved columns in their exact relative order.
- If any required column is missing, keeps the workbook pending and offers a button to add every missing required column in its approved position with null values.
- Trims leading and trailing spaces from headers.
- Rejects duplicated required headers because they must be resolved manually before missing columns can be added safely. Renamed headers remain flagged as extras while their missing approved counterparts can be added with null values.
- Keeps safely renameable or reorderable files in a pending state.
- Warns about columns outside the approved schema.
- Offers a **Delete extra columns** button that removes only unapproved columns and preserves approved data.
- Removes completely empty rows.
- Warns about empty values in required columns.
- Prompts the user for a Techsheet name and fills `TECSHEET NAME` in every
  validated data row with that value.
- Limits empty-cell warnings and row-level issue records to `INDIVIDUAL#`,
  `TECSHEET NAME`, `INDIVIDUAL NAME`, `DATE OF BIRTH`, `GENDER`,
  `VISA/SOAP#`, and `PROVIDER`.
- Checks that `INDIVIDUAL#` is numeric.
- Checks that `DATE OF BIRTH` is a four-digit year.
- Reports duplicate rows using `VISA/SOAP# + INDIVIDUAL#`.
- Produces optional `.xlsx` and CSV validated downloads and a separate `.xlsx`
  validation-report download.

Uploads and generated files are processed in memory and are never
automatically stored on the server. The browser saves a generated file only
after the user clicks its download button.

## Run locally

1. Install Python 3.11 or newer. Python 3.10 is not supported because current
   dependencies use `enum.StrEnum`, which was added in Python 3.11.
2. Open a terminal in this folder.
3. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

On Windows:

```powershell
python -m venv .venv
.venv\Scripts\activate
```

4. Install the requirements:

```bash
pip install -r requirements.txt
```

5. Start the app:

```bash
streamlit run app.py
```

6. Open the local address shown by Streamlit, usually `http://localhost:8501`.

## Current behavior

Structural errors reject the entire file. Row-level data problems generate warnings in version 1 and do not remove records. Duplicate claim/member keys are reported only.
