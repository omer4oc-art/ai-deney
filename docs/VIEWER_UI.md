# Viewer UI

Thin local UI for browsing existing Truth Pack and Inbox Run artifacts. This tool is read-only and does not generate reports.

## What It Shows

- `outputs/_truth_pack` as **Truth Pack (current)**.
- `outputs/inbox_runs/*` run history (newest first).
- `data/raw/**/manifest.json` audit manifests.

Supported file views:

- `index.md` and any `.md` file (rendered to HTML).
- `.html` files (served as-is).
- `.txt` and `.json` files (pretty `<pre>` view).
- Common run artifacts like `bundle.txt`, `gate_report.json`, `manifest.json`.

## Run It

```bash
bash scripts/run_viewer.sh
```

Default URL:

- `http://127.0.0.1:8010/`

Optional browser helper (macOS):

```bash
bash scripts/open_viewer.sh
```

## Compare View

Use the homepage compare form or open directly:

```text
/compare?run_a=<id>&run_b=<id>
```

Compare output includes:

- Files only in A.
- Files only in B.
- Files in both with different `sha256`.

For `.md`, `.txt`, `.json`, select a changed file to see a bounded unified diff.

## Safety

The server only reads from these roots:

- `outputs/_truth_pack`
- `outputs/inbox_runs`
- `data/raw` (`manifest.json` files only)

Path traversal and absolute paths are rejected.
