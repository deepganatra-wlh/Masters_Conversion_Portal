"""
designation_change.py
----------------------
Builds the second output file - the "Designation Change" bulk-upload file -
from the already-converted output DataFrame. Column layout mirrors the
sample template `designation_change-BulkuploadFile.xlsx`:

    AgentCode | DesignationMap | DesignationMappingDate | MappingStatus_designationchange(Active)
"""

import pandas as pd

TEMPLATE_COLUMNS = [
    "AgentCode",
    "DesignationMap",
    "DesignationMappingDate",
    "MappingStatus_designationchange(Active)",
]


def guess_agent_code_column(columns):
    """Best-effort guess at which output column holds the agent/relationship code."""
    priority_keywords = [
        "RELATIONSHIP_CODE",
        "INTERMEDIARY_CD",
        "INTERMEDIARY_CODE",
        "AGENTCODE",
        "AGENT_CODE",
    ]
    for kw in priority_keywords:
        for col in columns:
            if kw in col.upper().replace(" ", "_"):
                return col
    # fallback: first column containing "CODE" or "CD"
    for col in columns:
        upper = col.upper()
        if "CODE" in upper or upper.endswith("_CD"):
            return col
    return columns[0] if columns else None


def guess_designation_column(columns):
    for col in columns:
        if "DESIGNATION" in col.upper():
            return col
    return None


def build_designation_change_df(
    output_df,
    agent_code_column,
    designation_source,          # either a column name, or None if using a fixed value
    designation_fixed_value,     # used when designation_source is None
    mapping_date,                # a datetime.date / datetime.datetime, applied to every row
    status_value="Active",
):
    """
    Returns a DataFrame with the 4 template columns, one row per row of
    output_df.
    """
    n = len(output_df)

    if agent_code_column not in output_df.columns:
        raise ValueError(f"Agent code column '{agent_code_column}' not found in converted output.")

    if designation_source:
        if designation_source not in output_df.columns:
            raise ValueError(f"Designation column '{designation_source}' not found in converted output.")
        designation_series = output_df[designation_source].astype(str)
    else:
        designation_series = pd.Series([designation_fixed_value] * n)

    date_str = pd.Timestamp(mapping_date).strftime("%d-%m-%Y")

    result = pd.DataFrame({
        "AgentCode": output_df[agent_code_column],
        "DesignationMap": designation_series.values,
        "DesignationMappingDate": [date_str] * n,
        "MappingStatus_designationchange(Active)": [status_value] * n,
    })

    return result
