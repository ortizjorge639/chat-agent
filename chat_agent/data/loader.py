"""Data access layer — loads from Excel or SQL Server based on DATASOURCE flag."""

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from config.settings import Settings

logger = logging.getLogger(__name__)

CHUNK_SIZE: int = 60


class DataLoader:
    """Loads tabular data from Excel files or SQL Server and exposes query helpers."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._tables: dict[str, pd.DataFrame] = {}
        self._load()

    # ── loaders ──────────────────────────────────────────

    def _load(self) -> None:
        source = self._settings.datasource.lower()
        if source == "excel":
            self._load_excel()
        elif source == "sql":
            self._load_sql()
        else:
            raise ValueError(f"Unknown DATASOURCE: {self._settings.datasource!r}")

    def _load_excel(self) -> None:
        folder = Path(self._settings.excel_folder_path)
        if not folder.exists():
            raise FileNotFoundError(f"Excel folder not found: {folder}")

        for fp in sorted(folder.glob("*.xlsx")):
            xls = pd.ExcelFile(fp)
            for sheet in xls.sheet_names:
                table_name = (
                    f"{fp.stem}__{sheet}" if len(xls.sheet_names) > 1 else fp.stem
                )
                df = pd.read_excel(xls, sheet_name=sheet)
                df.columns = [str(c).strip() for c in df.columns]
                self._tables[table_name] = df
                logger.info(
                    "Loaded table '%s' (%d rows, %d cols)",
                    table_name,
                    len(df),
                    len(df.columns),
                )

    def _load_sql(self) -> None:
        import pyodbc  # deferred import — only needed for production

        s = self._settings
        if s.sql_trusted_connection.lower() == "yes":
            conn_str = (
                f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                f"SERVER={s.sql_server};"
                f"DATABASE={s.sql_database};"
                f"Trusted_Connection=yes;"
            )
        else:
            conn_str = (
                f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                f"SERVER={s.sql_server};"
                f"DATABASE={s.sql_database};"
                f"UID={s.sql_username};"
                f"PWD={s.sql_password};"
            )

        conn = pyodbc.connect(conn_str)
        table = s.sql_table
        df = pd.read_sql(f"SELECT * FROM [{table}]", conn)
        df.columns = [str(c).strip() for c in df.columns]
        self._tables[table] = df
        conn.close()
        logger.info(
            "Loaded SQL table '%s' (%d rows, %d cols)",
            table,
            len(df),
            len(df.columns),
        )

    # ── public query API ─────────────────────────────────

    def list_tables(self) -> list[str]:
        """Return names of all loaded tables."""
        return list(self._tables.keys())

    def get_schema(self, table_name: str) -> dict[str, str]:
        """Return {column_name: dtype} for a table."""
        df = self._get_table(table_name)
        return {col: str(df[col].dtype) for col in df.columns}

    def count_rows(
        self,
        table_name: str,
        filter_column: str | None = None,
        filter_value: str | None = None,
    ) -> int:
        """Exact row count, with optional single-column filter."""
        df = self._get_table(table_name)
        if filter_column and filter_value is not None:
            df = self._apply_filter(df, filter_column, filter_value)
        return len(df)

    def get_rows(
        self,
        table_name: str,
        filter_column: str | None = None,
        filter_value: str | None = None,
    ) -> dict[str, Any]:
        """Return ALL matching rows with metadata."""
        df = self._get_table(table_name)
        if filter_column and filter_value is not None:
            df = self._apply_filter(df, filter_column, filter_value)
        return {
            "table": table_name,
            "rows": df.to_dict(orient="records"),
            "total": len(df),
            "columns": list(df.columns),
        }

    def get_distinct_values(self, table_name: str, column: str) -> list[str]:
        """All unique non-null values in a column, sorted."""
        df = self._get_table(table_name)
        self._check_column(df, column, table_name)
        return sorted(df[column].dropna().unique().astype(str).tolist())

    def query_table(self, table_name: str, query_expr: str) -> dict[str, Any]:
        """Run a pandas DataFrame.query() expression and return all matching rows."""
        df = self._get_table(table_name)
        try:
            result = df.query(query_expr)
        except Exception as exc:
            raise ValueError(f"Invalid query expression: {exc}") from exc
        return {
            "table": table_name,
            "rows": result.to_dict(orient="records"),
            "total": len(result),
            "columns": list(result.columns),
        }

    def group_by(
        self,
        table_name: str,
        group_column: str,
        agg_column: str | None = None,
        agg_func: str = "count",
    ) -> list[dict[str, Any]]:
        """Group by a column with optional aggregation."""
        df = self._get_table(table_name)
        self._check_column(df, group_column, table_name)

        if agg_column:
            self._check_column(df, agg_column, table_name)
            result = (
                df.groupby(group_column)[agg_column]
                .agg(agg_func)
                .reset_index()
            )
            result.columns = [group_column, f"{agg_func}_{agg_column}"]
        else:
            result = df.groupby(group_column).size().reset_index(name="count")

        return result.to_dict(orient="records")

    # ── helpers ──────────────────────────────────────────

    def _get_table(self, table_name: str) -> pd.DataFrame:
        if table_name not in self._tables:
            available = ", ".join(self._tables.keys()) or "(none)"
            raise ValueError(
                f"Table '{table_name}' not found. Available tables: {available}"
            )
        return self._tables[table_name]

    @staticmethod
    def _apply_filter(df: pd.DataFrame, column: str, value: str) -> pd.DataFrame:
        if column not in df.columns:
            raise ValueError(
                f"Column '{column}' not found. Available: {list(df.columns)}"
            )
        # Use numeric comparison for numeric columns to avoid "0.8" != "0.80"
        if pd.api.types.is_numeric_dtype(df[column]):
            try:
                num_val = float(value)
                return df[df[column] == num_val]
            except (ValueError, TypeError):
                pass
        return df[df[column].astype(str).str.lower() == value.lower()]

    @staticmethod
    def _check_column(df: pd.DataFrame, column: str, table_name: str) -> None:
        if column not in df.columns:
            raise ValueError(
                f"Column '{column}' not found in table '{table_name}'. "
                f"Available: {list(df.columns)}"
            )

