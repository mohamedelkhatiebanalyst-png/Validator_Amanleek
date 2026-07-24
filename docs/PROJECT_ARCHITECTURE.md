# Amanleek Excel Validator Architecture

## Purpose

This Streamlit application validates client-utilization Excel workbooks before
they are uploaded to WorkDrive. All uploaded and generated files are processed
in memory. The application does not automatically store user files on the
server.

## Application structure

```text
app.py
config/schema.json
amanleek_validator/
├── application/
│   ├── batch.py
│   ├── ports.py
│   └── single_file.py
├── domain/
│   ├── models.py
│   ├── schema.py
│   └── validation.py
├── infrastructure/
│   ├── config.py
│   └── excel.py
└── ui/
    ├── batch_page.py
    ├── guide_page.py
    └── single_file_page.py
```

- The UI layer renders Streamlit widgets and download actions.
- The application layer coordinates validation, repair, and batch operations.
- The domain layer contains schema rules and pure validation logic.
- The infrastructure layer reads and creates XLSX and CSV content in memory.
- `config/schema.json` is the runtime source of truth for sheet and column policy.

## Navigation and guide

`app.py` renders a left sidebar with three pages: Guide, Single-file
validation, and Batch check. Guide is the default page and explains both
workflows with short visual steps. Changing the selected page does not write
any uploaded or generated content to disk.

## Single-file workflow

1. The user uploads one `.xlsx` workbook.
2. The user enters a Techsheet name.
3. The workbook archive and worksheet structure are validated.
4. Safe repair actions are offered when applicable:
   - rename the single worksheet to `sheet1`;
   - add configured repairable columns;
   - remove extra columns;
   - reorder approved columns.
5. Empty rows are removed and the configured row rules are evaluated.
6. The entered Techsheet name fills `TECSHEET NAME` in every retained row.
7. The app displays warnings and configured row-level issues.
8. The user may download:
   - the validated workbook as `.xlsx`;
   - the validated data as Excel-safe UTF-8 CSV;
   - a separate `.xlsx` validation report when row issues exist.

Rejected uploads are not stored. Pending repaired content is held only in the
current Streamlit session.

## Row-level issue policy

`row_issue_columns` in `config/schema.json` controls which columns produce empty-cell
warnings and row-level report entries. The current columns are:

- `INDIVIDUAL#`
- `TECSHEET NAME`
- `INDIVIDUAL NAME`
- `DATE OF BIRTH`
- `GENDER`
- `VISA/SOAP#`
- `PROVIDER`

Additional checks confirm that `INDIVIDUAL#` is numeric and `DATE OF BIRTH`
uses a four-digit year. Duplicate provisional keys generate a summary warning.

## Batch workflow

The Batch check tab is available to every app user and has no separate password
gate.

1. The user uploads between two and 50 `.xlsx` workbooks.
2. The first readable workbook becomes the structural reference.
3. Every workbook is compared by worksheet name, sequence, column count,
   header spelling, and header order.
4. Differences and unreadable files are reported.
5. The app reports whether all uploaded workbooks match the reference.

The batch workflow is comparison-only. It does not combine, modify, download,
or store the uploaded workbooks.

## File safety

- Only valid XLSX ZIP archives are accepted.
- Compressed size, uncompressed size, member count, and encryption are checked.
- CSV formula prefixes are escaped to reduce spreadsheet formula injection.
- Unexpected failures are logged without exposing internal exception details in
  the browser.
- Generated files are saved to a user's computer only through browser download
  actions.

## Deployment

Install Python 3.11 or newer and the pinned dependency ranges from
`requirements.txt`, then run:

```bash
streamlit run app.py
```

For a client-hosted deployment:

- terminate HTTPS at a reverse proxy or managed platform;
- protect the whole application with the client's identity/access layer when
  workbooks contain confidential data;
- restrict network access and server logs;
- configure upload/request limits at both Streamlit and the reverse proxy;
- monitor memory because uploaded and generated workbooks are intentionally
  held in each active user's session;
- run the regression suite with `python -m unittest discover -s tests -v`.

The batch tab itself has no application-level password. Any required access
control should protect the complete application at the hosting layer.
