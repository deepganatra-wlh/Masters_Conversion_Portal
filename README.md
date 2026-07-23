# Conversion Pipeline (Flask edition)

Same tool as before — upload a column-mapping JSON + a base CSV/Excel file,
get a converted CSV, and optionally a second "Designation Change"
bulk-upload file — rebuilt on **Flask** so it runs on PythonAnywhere's free
tier (which serves plain WSGI apps only; it doesn't support Streamlit,
since Streamlit needs a persistent websocket connection).

## Files

- `app.py` — Flask app: routes for upload, conversion, the designation-change
  form, and downloads.
- `converter_core.py` — the conversion engine (unchanged from before).
- `designation_change.py` — builds the optional second file.
- `storage.py` — tiny disk-backed session store (each conversion run gets
  its own folder under `sessions/`, auto-cleaned after 2 hours). Needed
  because plain WSGI has no in-memory state to rely on between requests.
- `templates/` — `base.html`, `index.html` (upload), `result.html`
  (preview + designation form + downloads).
- `static/style.css` — styling.

## How the flow works (no websockets needed)

1. `GET /` — upload form.
2. `POST /convert` — reads the two uploaded files, runs the conversion,
   stores the result on disk under a random token, redirects to
   `/result/<token>`.
3. `GET /result/<token>` — shows the preview table + the optional
   designation-change form.
4. `POST /designation/<token>` — builds the second file from your choices,
   redisplays the page with its preview and download links.
5. `/download/<token>/main|designation|zip` — serves the files.

Every step is a normal HTTP request/response, which is exactly what
PythonAnywhere's free WSGI tier supports.

## Run locally

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Visit `http://localhost:5000`.

## Deploy on PythonAnywhere (free tier)

1. **Sign up / log in** at pythonanywhere.com.
2. **Upload the code.** Easiest: zip this folder, then in the PythonAnywhere
   "Files" tab upload the zip into your home directory and unzip it via a
   Bash console:
   ```bash
   unzip conversion_pipeline_flask.zip -d conversion_pipeline
   ```
   (Or `git clone` if you push this folder to a repo first.)
3. **Create a virtualenv** (Bash console):
   ```bash
   cd ~/conversion_pipeline
   python3.10 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
4. **Web tab → Add a new web app** → choose **Manual configuration** (not
   the Flask wizard, since your code already exists) → pick the same Python
   version as your venv.
5. **Set the virtualenv path** in the Web tab to
   `/home/<yourusername>/conversion_pipeline/venv`.
6. **Edit the WSGI configuration file** (linked from the Web tab) — delete
   the boilerplate and replace it with:
   ```python
   import sys
   path = '/home/<yourusername>/conversion_pipeline'
   if path not in sys.path:
       sys.path.insert(0, path)

   from app import app as application
   ```
7. **Set a real secret key.** Open `app.py` and replace
   `"change-this-secret-key"` with something random before your first
   deploy.
8. Click **Reload** on the Web tab. Your app is live at
   `<yourusername>.pythonanywhere.com`.

### Free-tier specifics to keep in mind

- **No custom domain / HTTPS is on `*.pythonanywhere.com`** by default —
  fine for internal use.
- **512 MB disk quota** — the `sessions/` folder auto-cleans entries older
  than 2 hours, but if you expect heavy use, lower `MAX_AGE_SECONDS` in
  `storage.py`.
- **CPU seconds are capped** on free accounts; large files will just be
  slower, not broken, but very large spreadsheets may hit the daily quota.
- **No "Always-on tasks"** on free tier — not needed here, since this app
  has no background jobs, only request/response.
- `app.config["MAX_CONTENT_LENGTH"]` in `app.py` caps uploads at 20 MB;
  raise/lower it to match what you expect to upload.

## Mapping JSON format

Each entry in `columns` supports `source_column`, `target_column`,
`datatype` (`string` / `integer` / `float` / `date`), and optional
`transformation` (`prepend`, `static`, `conditional_value`, `value_map`).

### `value_map` (swap specific values for other values)

Use this when certain cell values need to become different values on
output — e.g. codes to labels, old designations to new ones.

```json
{
  "source_column": "Gender",
  "target_column": "Gender",
  "datatype": "string",
  "transformation": "value_map",
  "value_map": {
    "M": "Male",
    "F": "Female"
  },
  "unmapped": "keep"
}
```

- `value_map` — dictionary of exact source value → replacement value.
  Matching is done on the string value *after* the `datatype` conversion
  (so for a `string` column, whitespace-trimmed values).
- `unmapped` — what happens to a value that isn't in `value_map`:
  - `"keep"` (default) — leave the original value as-is
  - `"blank"` — output an empty string
  - any other string — used as a literal fallback value, e.g.
    `"unmapped": "OTHER"`
