# Final 01 - Zoho Utilization Pipeline Architecture

## Purpose

This document defines the first production-ready architecture for the new utilization-data pipeline using Zoho WorkDrive, the Python Validator App, Zoho DataPrep, and Zoho Analytics.

The main goals are to:

- Validate incoming Excel files before ingestion.
- Process only new files instead of rebuilding all historical data.
- apply the transformation ruleset once to the current batch.
- Load validated data incrementally into Zoho Analytics.
- Maintain traceability, duplicate protection, and a clear audit trail.

---

## End-to-End Flow

```text
Client Upload
     |
     v
WorkDrive / 01_Incoming
     |
     v
Python Validator App
     |
     +-- Invalid ------> WorkDrive / 03_Rejected
     |                         +-- Validation report
     |
     +-- Valid --------> WorkDrive / 02_Validated
                                  |
                                  v
                         Zoho DataPrep Source
                                  |
                                  v
                         Merge Validated Files
                                  |
                                  v
                        Standard Transformation
                           and Globmed Ruleset
                                  |
                                  v
                        Data Quality Control
                                  |
                                  v
                  Append to Historical Master Dataset
                                  |
                                  v
                   Zoho Analytics Master Table
                                  |
                                  v
                  Dashboards / Client Permalinks
                                  |
                                  v
                       Archive Processed Files
```

---

## 1. Incoming Folder

Users upload original utilization files into:

```text
WorkDrive
└── Utilization Pipeline
    └── 01_Incoming
```

### Rules

- Only `.xlsx` files are accepted.
- The expected worksheet is `Sheet1`.
- No manual transformation should happen in this folder.
- The original file should remain unchanged for audit purposes.
- Zoho DataPrep should not read directly from this folder.

The Incoming folder is only a landing area.

---

## 2. Python Validator App

The validator reads each file from `01_Incoming` and validates it before Zoho DataPrep processes it.

### File-Level Validation

- Confirm the file extension is `.xlsx`.
- Confirm that the workbook is not password protected.
- Confirm that `Sheet1` exists.
- Process only the expected worksheet.
- Confirm that the file opens successfully.

### Schema Validation

- All required columns must exist.
- Required columns must appear in the correct order.
- Column names must match exactly.
- Missing required columns cause rejection.
- Additional columns generate a warning.
- Required columns must not be completely empty.

### Data Validation

- `INDIVIDUAL#` must be numeric.
- Date columns must contain valid dates.
- Text columns must be handled consistently as text.
- Invalid or unexpected values produce warnings or errors according to severity.
- Duplicate or suspicious records are flagged.

### Validation Results

Each file receives one of the following statuses:

```text
PASS
PASS WITH WARNINGS
REJECTED
```

### Validation Report

The validator should create a report containing:

- File name
- Validation date and time
- Total row count
- Error count
- Warning count
- Missing columns
- Extra columns
- Invalid values
- Final validation status

---

## 3. Validated and Rejected Folders

### Validated Files

Files that pass validation are moved to:

```text
WorkDrive / 02_Validated
```

Files with non-blocking warnings may also move to the Validated folder.

### Rejected Files

Files with blocking errors are moved to:

```text
WorkDrive / 03_Rejected
```

The validation report should accompany each rejected file or be recorded in a central validation log.

Zoho DataPrep must never import files from the Rejected folder.

---

## 4. Zoho DataPrep Source

The Zoho DataPrep source should point only to:

```text
WorkDrive / 02_Validated
```

### Recommended Source Configuration

- File type: `.xlsx`
- Worksheet: `Sheet1`
- Controlled file-name pattern where required
- Merge files: enabled when all validated files should enter one combined staging dataset

Because the validator guarantees a consistent schema and column order, DataPrep can safely merge the files.

The source should process only new validated files and must not reload every historical file during each run.

---

## 5. Merge Validated Files

Multiple validated files are vertically appended into one current-batch staging dataset.

Example:

```text
Validated_Client_A_July.xlsx
Validated_Client_B_July.xlsx
Validated_Client_C_July.xlsx
```

becomes:

```text
Current Batch Staging Dataset
```

### Recommended Lineage Columns

- Source file name
- Upload timestamp
- Pipeline run ID
- Validation status
- Client name
- Processing date

A recommended technical field is:

```text
_source_file_name
```

This makes troubleshooting and lineage analysis significantly easier.

---

## 6. Standard Transformation and Ruleset

The Globmed transformation rules should be applied once to the current incoming batch, not repeatedly to the entire historical dataset.

The reusable DataPrep ruleset should perform operations such as:

- Data-type correction
- Date standardization
- Text cleanup
- Column renaming
- Null handling
- Client-name derivation
- Age calculation
- Age-band calculation
- Service-category mapping
- Diagnosis-category mapping
- Chronic-condition identification
- Claim-date derivations
- Amount standardization

The final transformed batch must match the exact schema of the Zoho Analytics master table.

---

## 7. Data-Quality Checkpoint

Before exporting to Zoho Analytics, the pipeline should perform a final quality check.

### Required Checks

- Reconcile row counts before and after transformation.
- Confirm that no required columns disappeared.
- Confirm that no unexpected schema change occurred.
- Confirm that `Client Name` is populated.
- Confirm that claim dates are valid.
- Confirm that amount fields are numeric.
- Confirm that required identifiers are populated.
- Confirm that no unintended duplicate rows were generated.
- Confirm that final column order matches the destination.

The batch should fail or be quarantined when a critical quality rule fails.

---

## 8. Historical Baseline and Incremental Append

The current complete utilization file should be loaded once as the historical baseline.

```text
Historical Master Dataset
        +
New Transformed Batch
        =
Updated Master Dataset
```

The pipeline should not rebuild the master dataset from hundreds of historical Excel files during every run.

After the initial baseline load, only new validated batches should be processed and appended.

This is the main expected performance improvement in the new architecture.

---

## 9. Zoho Analytics Destination

The first destination should be the duplicated testing workspace.

```text
Zoho Analytics Testing Workspace
└── Utilization Master
```

### Normal Export Mode

```text
Append rows
```

### Replace Mode Should Be Reserved For

- Initial historical baseline loading
- Controlled full refreshes
- Recovery from corrupted data
- Major schema redesigns

Normal daily or periodic processing should use incremental append.

---

## 10. Duplicate Prevention

Before appending, the pipeline needs a reliable duplicate-control key.

Using only `Claim Number` may not be sufficient because one claim can contain several service lines.

A candidate composite key is:

```text
Client Name
+ Claim Number
+ Individual#
+ Claim Date
+ Provider
+ Amount
+ Service Category
```

The exact key must be tested against actual production data.

A generated record hash can then be created:

```text
record_hash = HASH(
    Client Name,
    Claim Number,
    Individual#,
    Claim Date,
    Provider,
    Amount,
    Service Category
)
```

Before append, rows whose hash already exists should be skipped, quarantined, or logged for review.

This makes reruns safer and helps make the pipeline idempotent.

---

## 11. Processed Archive

After a successful pipeline run, source files should move from `02_Validated` to:

```text
WorkDrive / 04_Processed
```

### Recommended Archive Structure

```text
04_Processed
└── 2026
    └── 07
        ├── Client_A
        ├── Client_B
        └── Client_C
```

A file should move to Processed only after:

1. Validation succeeds.
2. DataPrep transformation succeeds.
3. Export to Zoho Analytics succeeds.
4. Row-count reconciliation succeeds.

Moving files before all four checks pass creates a risk of data loss.

The movement may be automated using Zoho Flow, a custom Deluge function, a Zoho API process, or a controlled manual step, depending on the available Zoho configuration.

---

## 12. Dashboard Layer

All reports and dashboards should connect to the same master utilization table.

```text
Utilization Master
       |
       +-- Client A Dashboard
       +-- Client B Dashboard
       +-- Client C Dashboard
       +-- Master Internal Dashboard
```

The preferred design is one reusable dashboard with client filtering through permalink criteria, rather than physically duplicating the dashboard for every client.

A separate dashboard is justified only when:

- The layout differs by client.
- The KPIs differ by client.
- The access model requires physically separated reports.
- Client-specific customization cannot be handled through filters.

---

## Recommended WorkDrive Folder Structure

```text
Utilization Pipeline
|
+-- 01_Incoming
|
+-- 02_Validated
|
+-- 03_Rejected
|   +-- Validation Reports
|
+-- 04_Processed
|   +-- Year / Month / Client
|
+-- 05_Pipeline Logs
```

The numbered naming convention makes the workflow easier for operational users to understand.

---

## Pipeline Control Table

A small control table should track every uploaded file and pipeline run.

| Run ID | File Name | Client | Rows Received | Rows Loaded | Errors | Warnings | Status | Processed At |
|---|---|---|---:|---:|---:|---:|---|---|
| RUN-001 | Client_A_July.xlsx | Client A | 12,500 | 12,500 | 0 | 3 | Success | 2026-07-14 |
| RUN-002 | Client_B_July.xlsx | Client B | 8,200 | 0 | 12 | 5 | Rejected | 2026-07-14 |

This table can later feed an internal pipeline-monitoring dashboard.

---

## Component Responsibilities

| Component | Responsibility |
|---|---|
| WorkDrive Incoming | Receive and preserve original files |
| Python Validator App | Perform file, schema, and data validation |
| Validated Folder | Hold DataPrep-ready files |
| Rejected Folder | Hold invalid files and validation reports |
| Zoho DataPrep | Merge, transform, map, and quality-check new batches |
| Historical Master | Preserve accumulated utilization data |
| Zoho Analytics | Store the reporting table and serve dashboards |
| Processed Archive | Preserve successfully loaded source files |
| Control Log | Track every file and pipeline run |

---

## Critical Architecture Decisions

1. Do not apply the 29-step ruleset to the full historical dataset during every run.
2. Do not download the final Excel file locally and manually upload it again.
3. Do not allow Zoho DataPrep to ingest unvalidated files.
4. Use the current final combined sheet once as the historical baseline.
5. Process and append only new files after the baseline load.
6. Archive files after a successful load so they are not imported again.
7. Add duplicate protection before enabling automated append.
8. Test the full flow in the duplicated Zoho Analytics workspace before changing production.

---

## Final Architecture Summary

The Final 01 architecture separates file intake, validation, transformation, storage, reporting, and archiving into clear stages. It removes repeated historical processing, reduces manual work, improves traceability, and creates a safer path toward full automation.

The remaining implementation decision is how to automate moving a file from `02_Validated` to `04_Processed` only after the Zoho Analytics export and reconciliation checks succeed.
