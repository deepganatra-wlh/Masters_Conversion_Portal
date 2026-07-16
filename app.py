import io
import zipfile
from datetime import date, datetime

from flask import (
    Flask, render_template, request, redirect, url_for,
    send_file, flash, abort,
)

from converter_core import ExcelConverter, dataframe_to_csv_bytes, dataframe_to_excel_bytes
from designation_change import (
    build_designation_change_df,
    guess_agent_code_column,
    guess_designation_column,
)
import storage

app = Flask(__name__)
app.secret_key = "change-this-secret-key"  # replace before deploying
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB upload cap


@app.before_request
def _sweep_old_sessions():
    storage.cleanup_old_sessions()


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/convert", methods=["POST"])
def convert():
    mapping_file = request.files.get("mapping_file")
    base_file = request.files.get("base_file")

    if not mapping_file or mapping_file.filename == "":
        flash("Please choose a column-mapping JSON file.")
        return redirect(url_for("index"))
    if not base_file or base_file.filename == "":
        flash("Please choose a base CSV/Excel file.")
        return redirect(url_for("index"))

    try:
        mapping_bytes = mapping_file.read()
        converter = ExcelConverter(mapping_bytes)
    except Exception as e:
        flash(f"Could not parse mapping JSON: {e}")
        return redirect(url_for("index"))

    base_name = base_file.filename.rsplit(".", 1)[0]
    file_bytes = base_file.read()

    try:
        if base_file.filename.lower().endswith(".csv"):
            try:
                output_df, warnings = converter.convert_csv_bytes(file_bytes, encoding="utf-8-sig")
            except UnicodeDecodeError:
                output_df, warnings = converter.convert_csv_bytes(file_bytes, encoding="latin-1")
        else:
            output_df, warnings = converter.convert_excel_bytes(file_bytes)
    except Exception as e:
        flash(f"Conversion failed: {e}")
        return redirect(url_for("index"))

    token = storage.new_token()
    storage.save_df(token, "output", output_df)
    storage.save_meta(token, {
        "base_name": base_name,
        "warnings": warnings,
        "n_rows": len(output_df),
        "n_cols": len(output_df.columns),
    })

    return redirect(url_for("result", token=token))


@app.route("/result/<token>", methods=["GET"])
def result(token):
    if not storage.session_exists(token):
        abort(404)

    output_df = storage.load_df(token, "output")
    meta = storage.load_meta(token) or {}

    columns = list(output_df.columns)
    guessed_agent = guess_agent_code_column(columns)
    guessed_designation = guess_designation_column(columns)

    preview_cols = columns
    preview_rows = output_df.head(15).astype(str).values.tolist()

    designation_meta = storage.load_meta(token) or {}
    has_designation = storage.load_bytes(token, "designation.xlsx") is not None
    designation_preview = None
    if has_designation:
        designation_df = storage.load_df(token, "designation")
        if designation_df is not None:
            designation_preview = {
                "cols": list(designation_df.columns),
                "rows": designation_df.head(15).astype(str).values.tolist(),
            }

    return render_template(
        "result.html",
        token=token,
        meta=meta,
        preview_cols=preview_cols,
        preview_rows=preview_rows,
        columns=columns,
        guessed_agent=guessed_agent,
        guessed_designation=guessed_designation,
        today=date.today().isoformat(),
        has_designation=has_designation,
        designation_preview=designation_preview,
    )


@app.route("/designation/<token>", methods=["POST"])
def designation(token):
    if not storage.session_exists(token):
        abort(404)

    output_df = storage.load_df(token, "output")
    if output_df is None:
        abort(404)

    agent_code_column = request.form.get("agent_code_column")
    designation_mode = request.form.get("designation_mode")
    designation_source = request.form.get("designation_source") or None
    designation_fixed_value = request.form.get("designation_fixed_value", "")
    mapping_date_str = request.form.get("mapping_date") or date.today().isoformat()
    status_value = request.form.get("status_value", "Active")

    if designation_mode == "fixed":
        designation_source = None
    else:
        designation_fixed_value = ""

    try:
        mapping_date = datetime.strptime(mapping_date_str, "%Y-%m-%d").date()
    except ValueError:
        mapping_date = date.today()

    try:
        designation_df = build_designation_change_df(
            output_df=output_df,
            agent_code_column=agent_code_column,
            designation_source=designation_source,
            designation_fixed_value=designation_fixed_value,
            mapping_date=mapping_date,
            status_value=status_value,
        )
    except Exception as e:
        flash(f"Could not build designation change file: {e}")
        return redirect(url_for("result", token=token))

    storage.save_df(token, "designation", designation_df)
    designation_bytes = dataframe_to_excel_bytes(designation_df, sheet_name="Sheet1")
    storage.save_bytes(token, "designation.xlsx", designation_bytes)

    return redirect(url_for("result", token=token))


@app.route("/download/<token>/main")
def download_main(token):
    if not storage.session_exists(token):
        abort(404)
    output_df = storage.load_df(token, "output")
    meta = storage.load_meta(token) or {}
    if output_df is None:
        abort(404)
    data = dataframe_to_csv_bytes(output_df)
    fname = f"{meta.get('base_name', 'output')}_output.csv"
    return send_file(io.BytesIO(data), mimetype="text/csv", as_attachment=True, download_name=fname)


@app.route("/download/<token>/designation")
def download_designation(token):
    if not storage.session_exists(token):
        abort(404)
    data = storage.load_bytes(token, "designation.xlsx")
    meta = storage.load_meta(token) or {}
    if data is None:
        abort(404)
    fname = f"{meta.get('base_name', 'output')}_designation_change.xlsx"
    return send_file(
        io.BytesIO(data),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=fname,
    )


@app.route("/download/<token>/zip")
def download_zip(token):
    if not storage.session_exists(token):
        abort(404)
    output_df = storage.load_df(token, "output")
    designation_bytes = storage.load_bytes(token, "designation.xlsx")
    meta = storage.load_meta(token) or {}
    if output_df is None:
        abort(404)

    base_name = meta.get("base_name", "output")
    main_bytes = dataframe_to_csv_bytes(output_df)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{base_name}_output.csv", main_bytes)
        if designation_bytes is not None:
            zf.writestr(f"{base_name}_designation_change.xlsx", designation_bytes)
    buf.seek(0)
    return send_file(
        buf, mimetype="application/zip", as_attachment=True,
        download_name=f"{base_name}_conversion_bundle.zip",
    )


if __name__ == "__main__":
    # Local dev only. On PythonAnywhere, the WSGI config file imports `app`
    # from this module instead of calling run().
    app.run(debug=True, port=5000)
