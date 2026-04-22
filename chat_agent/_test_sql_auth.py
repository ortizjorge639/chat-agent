"""Quick test: verify DataLoader works with TCP + SQL auth."""
from config.settings import Settings
from data.loader import DataLoader

s = Settings()
print(f"Datasource: {s.datasource}")
print(f"SQL Server: {s.sql_server}")
print(f"Trusted: {s.sql_trusted_connection}")
print(f"User: {s.sql_username}")

loader = DataLoader(s)
print(f"Tables loaded: {loader.list_tables()}")
print(f"Schema: {loader.get_schema('operations.Obsolescence_Results')}")
print(f"Row count: {loader.count_rows('operations.Obsolescence_Results')}")

rows = loader.get_rows("operations.Obsolescence_Results")
print(f"Got {rows['total']} rows")
print(f"First row: {rows['rows'][0]}")
print("\nAll good!")
