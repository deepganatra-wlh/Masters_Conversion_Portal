"""
converter_core.py
------------------
In-memory version of the original converter.py logic. No file paths, no
print statements, no tqdm - everything works on DataFrames / bytes so it can
be plugged into a web UI (Streamlit) or reused from the command line.
"""

import io
import json
import numpy as np
import pandas as pd


class ConversionWarning(Exception):
    """Raised for recoverable, user-facing warnings (missing columns etc.)."""
    pass


def load_mapping(mapping_file_or_bytes):
    """Load a mapping JSON from a path, a file-like object, or raw bytes/str."""
    if isinstance(mapping_file_or_bytes, (bytes, bytearray)):
        return json.loads(mapping_file_or_bytes.decode("utf-8"))
    if hasattr(mapping_file_or_bytes, "read"):
        content = mapping_file_or_bytes.read()
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        return json.loads(content)
    if isinstance(mapping_file_or_bytes, str):
        # Could be a path or raw JSON text
        try:
            with open(mapping_file_or_bytes, "r") as f:
                return json.load(f)
        except (FileNotFoundError, OSError):
            return json.loads(mapping_file_or_bytes)
    raise TypeError("Unsupported mapping input type")


class ExcelConverter:
    def __init__(self, mapping):
        """`mapping` can be a dict already, or anything load_mapping() accepts."""
        if isinstance(mapping, dict):
            self.mapping = mapping
        else:
            self.mapping = load_mapping(mapping)

    # ---------- column-level vectorized transforms (unchanged logic) ----------

    def convert_date_vectorized(self, series, date_format="%d-%m-%Y"):
        series = series.replace("", np.nan)
        date_series = pd.to_datetime(series, errors="coerce", dayfirst=True)
        return date_series.dt.strftime(date_format).fillna("")

    def convert_integer_vectorized(self, series):
        series = series.replace("", np.nan)
        numeric_series = pd.to_numeric(series, errors="coerce")
        return numeric_series.fillna(0).astype(np.int64)

    def convert_float_vectorized(self, series):
        series = series.replace("", np.nan)
        numeric_series = pd.to_numeric(series, errors="coerce")
        return numeric_series.fillna(0.0).astype(np.float64)

    def convert_string_vectorized(self, series):
        return series.fillna("").astype(str).str.strip()

    def process_column_vectorized(self, series, config):
        dtype = config.get("datatype", "string").lower()

        if dtype == "date":
            date_format = config.get("format", "%d-%m-%Y")
            result = self.convert_date_vectorized(series, date_format)
        elif dtype == "integer":
            result = self.convert_integer_vectorized(series)
        elif dtype == "float":
            result = self.convert_float_vectorized(series)
        else:
            result = self.convert_string_vectorized(series)

        transformation = config.get("transformation", "").lower()
        if transformation == "prepend":
            prepend_value = str(config.get("prepend_value", ""))
            result = prepend_value + result.astype(str)
        elif transformation == "static":
            static_value = str(config.get("static_value", ""))
            result = pd.Series([static_value] * len(result), index=result.index)
        elif transformation == "conditional_value":
            condition = config.get("condition", "").lower()
            condition_value = config.get("condition_value", "")
            true_value = config.get("true_value", "")
            false_value = config.get("false_value", "")

            if condition == "startswith":
                mask = result.astype(str).str.startswith(condition_value)
            elif condition == "endswith":
                mask = result.astype(str).str.endswith(condition_value)
            elif condition == "contains":
                mask = result.astype(str).str.contains(condition_value, na=False)
            elif condition == "equals":
                mask = result.astype(str) == condition_value
            else:
                mask = pd.Series([False] * len(result), index=result.index)

            result = mask.map({True: true_value, False: false_value})

        return result

    # ---------- main entry point used by the portal ----------

    def convert_dataframe(self, df):
        """
        Convert a raw DataFrame (all columns read as object/str) according to
        self.mapping. Returns (output_df, warnings_list).
        """
        warnings = []
        output_df = pd.DataFrame(index=df.index)

        for mapping_config in self.mapping["columns"]:
            source_col = mapping_config.get("source_column")
            target_col = mapping_config["target_column"]
            transformation = mapping_config.get("transformation", "").lower()

            if transformation == "static":
                output_df[target_col] = mapping_config.get("static_value", "")
                continue

            if not source_col or source_col not in df.columns:
                warnings.append(
                    f"Source column '{source_col}' not found for target "
                    f"'{target_col}'. Column skipped (left blank)."
                )
                output_df[target_col] = ""
                continue

            output_df[target_col] = self.process_column_vectorized(
                df[source_col], mapping_config
            )

        return output_df, warnings

    def convert_csv_bytes(self, csv_bytes, encoding="latin-1"):
        """Read CSV bytes into a DataFrame and convert it."""
        df = pd.read_csv(io.BytesIO(csv_bytes), dtype=object, encoding=encoding)
        return self.convert_dataframe(df)

    def convert_excel_bytes(self, excel_bytes, sheet_name=0):
        """Read Excel bytes into a DataFrame and convert it."""
        df = pd.read_excel(io.BytesIO(excel_bytes), sheet_name=sheet_name, dtype=object)
        return self.convert_dataframe(df)


def dataframe_to_csv_bytes(df, encoding="utf-8-sig"):
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode(encoding)


def dataframe_to_excel_bytes(df, sheet_name="Sheet1"):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return buf.getvalue()
