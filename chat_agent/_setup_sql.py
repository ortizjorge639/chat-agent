"""Step 1: Configure SQLEXPRESS for static TCP port 1433 and create a SQL login.

Run this as Administrator (elevated) because it restarts the SQL Server service.
"""
import subprocess
import pyodbc

# --- 1. Set static TCP port via registry ---
import winreg

reg_path = r"SOFTWARE\Microsoft\Microsoft SQL Server\MSSQL17.SQLEXPRESS\MSSQLServer\SuperSocketNetLib\Tcp\IPAll"
try:
    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path, 0, winreg.KEY_SET_VALUE)
    winreg.SetValueEx(key, "TcpPort", 0, winreg.REG_SZ, "1433")
    winreg.SetValueEx(key, "TcpDynamicPorts", 0, winreg.REG_SZ, "")  # clear dynamic
    winreg.CloseKey(key)
    print("[OK] Set TCP static port to 1433, cleared dynamic port")
except PermissionError:
    print("[ERROR] Run this script as Administrator (elevated PowerShell)")
    raise SystemExit(1)
except FileNotFoundError:
    print("[ERROR] Registry path not found — is MSSQL17.SQLEXPRESS correct?")
    raise SystemExit(1)

# --- 2. Enable TCP/IP protocol ---
proto_path = r"SOFTWARE\Microsoft\Microsoft SQL Server\MSSQL17.SQLEXPRESS\MSSQLServer\SuperSocketNetLib\Tcp"
try:
    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, proto_path, 0, winreg.KEY_SET_VALUE)
    winreg.SetValueEx(key, "Enabled", 0, winreg.REG_DWORD, 1)
    winreg.CloseKey(key)
    print("[OK] TCP/IP protocol enabled")
except Exception as e:
    print(f"[WARN] Could not enable TCP: {e}")

# --- 3. Enable mixed-mode authentication (SQL + Windows) ---
instance_path = r"SOFTWARE\Microsoft\Microsoft SQL Server\MSSQL17.SQLEXPRESS\MSSQLServer"
try:
    key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, instance_path, 0, winreg.KEY_SET_VALUE)
    winreg.SetValueEx(key, "LoginMode", 0, winreg.REG_DWORD, 2)  # 2 = mixed mode
    winreg.CloseKey(key)
    print("[OK] Authentication set to mixed mode (SQL + Windows)")
except Exception as e:
    print(f"[WARN] Could not set mixed mode: {e}")

# --- 4. Restart SQL Server ---
print("\nRestarting SQL Server (SQLEXPRESS)...")
subprocess.run(["net", "stop", "MSSQL$SQLEXPRESS"], capture_output=True)
result = subprocess.run(["net", "start", "MSSQL$SQLEXPRESS"], capture_output=True, text=True)
if result.returncode == 0:
    print("[OK] SQL Server restarted")
else:
    print(f"[ERROR] Could not restart: {result.stderr}")
    raise SystemExit(1)

# --- 5. Create SQL login ---
import time
time.sleep(2)  # give SQL a moment to fully start

conn = pyodbc.connect(
    r"DRIVER={ODBC Driver 17 for SQL Server};"
    r"SERVER=localhost\SQLEXPRESS;"
    r"Trusted_Connection=yes;"
    r"TrustServerCertificate=yes;",
    timeout=10,
    autocommit=True,
)
cursor = conn.cursor()

login_name = "extron_bot"
login_pass = "BotRead0nly!2026"  # change in production
db_name = "ExtronDemo"

# Create login if not exists
cursor.execute(f"IF NOT EXISTS (SELECT 1 FROM sys.server_principals WHERE name='{login_name}') "
               f"CREATE LOGIN [{login_name}] WITH PASSWORD='{login_pass}', DEFAULT_DATABASE=[{db_name}]")
print(f"[OK] SQL login '{login_name}' created (or already exists)")

# Create user in ExtronDemo
cursor.execute(f"USE [{db_name}]")
cursor.execute(f"IF NOT EXISTS (SELECT 1 FROM sys.database_principals WHERE name='{login_name}') "
               f"CREATE USER [{login_name}] FOR LOGIN [{login_name}]")
cursor.execute(f"ALTER ROLE db_datareader ADD MEMBER [{login_name}]")
print(f"[OK] User '{login_name}' has db_datareader on [{db_name}]")

conn.close()

# --- 6. Test TCP connection with SQL auth ---
print("\nTesting TCP connection on port 1433 with SQL auth...")
try:
    test_conn = pyodbc.connect(
        f"DRIVER={{ODBC Driver 17 for SQL Server}};"
        f"SERVER=localhost,1433;"
        f"DATABASE={db_name};"
        f"UID={login_name};"
        f"PWD={login_pass};"
        f"TrustServerCertificate=yes;",
        timeout=5,
    )
    cursor = test_conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM operations.Obsolescence_Results")
    count = cursor.fetchone()[0]
    print(f"[OK] Connected! Table has {count} rows.")
    test_conn.close()
except Exception as e:
    print(f"[ERROR] TCP connection failed: {e}")
    print("  You may need to allow port 1433 in Windows Firewall.")
    raise SystemExit(1)

print("\n=== All done! ===")
print(f"Connection string for .env:")
print(f"  SQL_SERVER=localhost,1433")
print(f"  SQL_DATABASE={db_name}")
print(f"  SQL_TABLE=operations.Obsolescence_Results")
print(f"  SQL_TRUSTED_CONNECTION=no")
print(f"  SQL_USERNAME={login_name}")
print(f"  SQL_PASSWORD={login_pass}")
