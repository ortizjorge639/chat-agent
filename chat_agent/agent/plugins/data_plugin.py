"""Data access tools for the Microsoft Agent Framework.

Each function is a plain callable passed to Agent(tools=[...]).
The AF infers the tool schema from type hints, Annotated metadata, and docstrings.
"""

import json
import logging
import os
from typing import Annotated
from uuid import uuid4

import pandas as pd
from pydantic import Field

from data.loader import DataLoader, CHUNK_SIZE

logger = logging.getLogger(__name__)

GENERATED_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "generated")


def _rows_to_chunks(rows: list[dict], columns: list[str]) -> list[str]:
    """Split rows into markdown table chunks of CHUNK_SIZE rows each."""
    if not rows:
        return []

    chunks = []
    total = len(rows)
    for i in range(0, total, CHUNK_SIZE):
        chunk_rows = rows[i : i + CHUNK_SIZE]
        df = pd.DataFrame(chunk_rows, columns=columns)
        md_table = df.to_markdown(index=False)
        header = f"**Rows {i + 1}–{min(i + CHUNK_SIZE, total)} of {total}**\n\n"
        chunks.append(header + md_table)

    return chunks


def _generate_excel(rows: list[dict], columns: list[str], table_name: str) -> dict:
    """Save rows to an Excel file and return file metadata."""
    os.makedirs(GENERATED_DIR, exist_ok=True)
    filename = f"{table_name}_{uuid4().hex[:8]}.xlsx"
    filepath = os.path.join(GENERATED_DIR, filename)
    df = pd.DataFrame(rows, columns=columns)
    df.to_excel(filepath, index=False)
    logger.info("Generated Excel: %s (%d rows)", filename, len(rows))
    return {"name": filename, "path": f"/api/files/{filename}"}


def create_data_tools(loader: DataLoader, data_buffer: list, file_buffer: list) -> list:
    """Factory that returns tool callables bound to *loader*.
    *data_buffer* collects markdown chunks for direct delivery to the user.
    *file_buffer* collects generated file metadata for download links.
    Both bypass the LLM to save tokens."""

    def list_tables() -> str:
        """List every available data table together with its column names and
        data types. Call this first to discover what data is available."""
        tables = loader.list_tables()
        schemas = {t: loader.get_schema(t) for t in tables}
        return json.dumps(schemas, indent=2, default=str)

    def get_schema(
        table_name: Annotated[str, Field(description="Name of the table to inspect")],
    ) -> str:
        """Get column names and data types for a specific table."""
        schema = loader.get_schema(table_name)
        return json.dumps(schema, indent=2)

    def count_rows(
        table_name: Annotated[str, Field(description="Name of the table")],
        filter_column: Annotated[str, Field(description="Column to filter by (optional)")] = "",
        filter_value: Annotated[str, Field(description="Value to match (optional)")] = "",
    ) -> str:
        """Count the total number of rows in a table. Optionally filter by a
        single column value. Always returns the exact count."""
        fc = filter_column or None
        fv = filter_value or None
        count = loader.count_rows(table_name, fc, fv)
        return json.dumps(
            {"table": table_name, "count": count, "filter_column": fc, "filter_value": fv}
        )

    def get_rows(
        table_name: Annotated[str, Field(description="Name of the table")],
        filter_column: Annotated[str, Field(description="Column to filter by (optional)")] = "",
        filter_value: Annotated[str, Field(description="Value to match (optional)")] = "",
    ) -> str:
        """Return rows from a table with optional single-column filter.
        The full data is sent directly to the user as inline messages and a
        downloadable Excel file. This tool returns only a summary for your
        reference — do NOT fabricate or repeat the data."""
        fc = filter_column or None
        fv = filter_value or None
        result = loader.get_rows(table_name, fc, fv)
        chunks = _rows_to_chunks(result["rows"], result["columns"])
        data_buffer.extend(chunks)
        file_info = _generate_excel(result["rows"], result["columns"], table_name)
        file_buffer.append(file_info)
        cols = ", ".join(result["columns"])
        return (
            f"Retrieved {result['total']} rows from table '{table_name}' "
            f"(columns: {cols}). Data has been sent directly to the user "
            f"as inline messages and a downloadable Excel file."
        )

    def get_distinct_values(
        table_name: Annotated[str, Field(description="Name of the table")],
        column: Annotated[str, Field(description="Column to get distinct values from")],
    ) -> str:
        """Get every unique value in a column (sorted, nulls excluded)."""
        values = loader.get_distinct_values(table_name, column)
        return json.dumps(values, default=str)

    def query_table(
        table_name: Annotated[str, Field(description="Name of the table")],
        query_expr: Annotated[str, Field(description="Pandas DataFrame.query() expression")],
    ) -> str:
        """Run a pandas query expression on a table.
        Examples: 'Age > 30', 'Status == "Active"',
        'Salary > 50000 and Department == "Engineering"'.
        The full data is sent directly to the user as inline messages and a
        downloadable Excel file. This tool returns only a summary for your
        reference — do NOT fabricate or repeat the data."""
        result = loader.query_table(table_name, query_expr)
        chunks = _rows_to_chunks(result["rows"], result["columns"])
        data_buffer.extend(chunks)
        file_info = _generate_excel(result["rows"], result["columns"], table_name)
        file_buffer.append(file_info)
        cols = ", ".join(result["columns"])
        return (
            f"Retrieved {result['total']} rows from table '{table_name}' "
            f"(columns: {cols}). Data has been sent directly to the user "
            f"as inline messages and a downloadable Excel file."
        )

    def group_by(
        table_name: Annotated[str, Field(description="Name of the table")],
        group_column: Annotated[str, Field(description="Column to group by")],
        agg_column: Annotated[str, Field(description="Column to aggregate (optional — omit to count rows)")] = "",
        agg_func: Annotated[str, Field(description="Aggregation: count, sum, mean, min, max (default count)")] = "count",
    ) -> str:
        """Group rows by a column and aggregate. Use for summaries, breakdowns,
        and category counts. If agg_column is omitted, counts rows per group."""
        ac = agg_column or None
        result = loader.group_by(table_name, group_column, ac, agg_func)
        return json.dumps(result, indent=2, default=str)

    return [list_tables, get_schema, count_rows, get_rows,
            get_distinct_values, query_table, group_by]
