"""Temporary script to discover local SQL Server databases and tables."""
import pyodbc

conn = pyodbc.connect(
    r"DRIVER={ODBC Driver 17 for SQL Server};"
    r"SERVER=localhost\SQLEXPRESS;"
    r"Trusted_Connection=yes;"
    r"TrustServerCertificate=yes;",
    timeout=5,
)
cursor = conn.cursor()

for db in ["ChatAgentTest", "ExtronDemo"]:
    print(f"\n=== {db} ===")
    cursor.execute(
        f"SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE "
        f"FROM [{db}].INFORMATION_SCHEMA.TABLES ORDER BY TABLE_NAME"
    )
    tables = cursor.fetchall()
    for t in tables:
        print(f"  {t.TABLE_SCHEMA}.{t.TABLE_NAME} ({t.TABLE_TYPE})")

    # Row counts for base tables
    for t in tables:
        if t.TABLE_TYPE == "BASE TABLE":
            cursor.execute(
                f"SELECT COUNT(*) FROM [{db}].[{t.TABLE_SCHEMA}].[{t.TABLE_NAME}]"
            )
            cnt = cursor.fetchone()[0]
            print(f"    -> {cnt} rows")

conn.close()
print("\nDone.")
