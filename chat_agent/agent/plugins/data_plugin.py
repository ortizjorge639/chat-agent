"""Data access tools for the Microsoft Agent Framework.

Each function is a plain callable passed to Agent(tools=[...]).
The AF infers the tool schema from type hints, Annotated metadata, and docstrings.
"""

import json
import logging
from typing import Annotated

import pandas as pd
from pydantic import Field

from data.loader import DataLoader

logger = logging.getLogger(__name__)


def _rows_to_markdown(result: dict) -> str:
    """Convert a paged result dict to a compact markdown table + metadata line.
    This keeps token usage low — GPT relays the table instead of re-formatting."""
    rows = result["rows"]
    if not rows:
        return f"No rows found. (total: {result['total']})"

    df = pd.DataFrame(rows)
    # Truncate long cell values to save tokens
    for col in df.columns:
        df[col] = df[col].astype(str).str[:120]

    md_table = df.to_markdown(index=False)
    meta = f"\n\nShowing page {result['page']} ({len(rows)} rows). Total matching: {result['total']}."
    if result["has_more"]:
        meta += " **More rows available** — user can reply 'more' for the next page."
    return md_table + meta


def create_data_tools(loader: DataLoader) -> list:
    """Factory that returns tool callables bound to *loader*."""

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
        page: Annotated[int, Field(description="Page number, 1-based (default 1)")] = 1,
        filter_column: Annotated[str, Field(description="Column to filter by (optional)")] = "",
        filter_value: Annotated[str, Field(description="Value to match (optional)")] = "",
    ) -> str:
        """Return rows from a table with optional single-column filter.
        Returns up to 50 rows per page as a pre-formatted markdown table.
        Set page > 1 for more rows."""
        fc = filter_column or None
        fv = filter_value or None
        result = loader.get_rows(table_name, page, fc, fv)
        return _rows_to_markdown(result)

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
        page: Annotated[int, Field(description="Page number, 1-based (default 1)")] = 1,
    ) -> str:
        """Run a pandas query expression on a table.
        Examples: 'Age > 30', 'Status == "Active"',
        'Salary > 50000 and Department == "Engineering"'.
        Results are paged at 50 rows. Returns a pre-formatted markdown table."""
        result = loader.query_table(table_name, query_expr, page)
        return _rows_to_markdown(result)

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
