# ---- Standard library imports ----
import json
import os
import html
from datetime import datetime
from collections.abc import Callable
from typing import Any

# ---- Third-party imports ----
# pip install pandas openai python-dotenv tqdm openpyxl pyodbc
import pandas as pd
import openpyxl  # required by pandas for Excel write
import pyodbc    # required for SQL Server connectivity
import openai
from dotenv import load_dotenv
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Environment + Azure OpenAI client setup
# ---------------------------------------------------------------------------
# Loads variables from .env file in the current directory (see .env.example)
load_dotenv(override=True)

# REQUIRES in .env:
#   AZURE_OPENAI_ENDPOINT        → e.g. https://your-resource.openai.azure.com/
#   AZURE_OPENAI_CHAT_DEPLOYMENT → your deployment name
#   AZURE_OPENAI_API_KEY         → your API key from Azure portal
client = openai.AzureOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    api_version="2024-12-01-preview",
)
MODEL_NAME = os.environ["AZURE_OPENAI_CHAT_DEPLOYMENT"]

print(f"Using model={MODEL_NAME}")

# ---------------------------------------------------------------------------
# Text cleanup
# ---------------------------------------------------------------------------
TAG_RE = __import__("re").compile(r"<[^>]+>")   # matches any HTML tag
WS_RE  = __import__("re").compile(r"\s+")       # matches runs of whitespace

def clean_text(raw: str) -> str:
    """Strip HTML tags, unescape entities, collapse whitespace."""
    if not raw:
        return ""
    no_tags = TAG_RE.sub(" ", str(raw))
    unescaped = html.unescape(no_tags)
    return WS_RE.sub(" ", unescaped).strip()

# ---------------------------------------------------------------------------
# Tool definition — OpenAI function-calling schema
# The LLM "calls" this function; we capture the structured arguments as output.
# ---------------------------------------------------------------------------
def record_extraction(
    replacement_intent: bool,
    replacement_pairs: list[dict[str, Any]],
    rationale: str,
    confidence: float,
) -> dict[str, Any]:
    return {"ok": True}

tool_mapping: dict[str, Callable[..., Any]] = {
    "record_extraction": record_extraction,
}

tools = [
    {
        "type": "function",
        "function": {
            "name": "record_extraction",
            "description": "Structured extraction of part replacement intent and mappings",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "replacement_intent": {"type": "boolean"},
                    "replacement_pairs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "old_part": {"type": "string"},
                                "new_part": {"type": "string"},
                                "cue_phrase": {"type": "string"},
                            },
                            "required": [
                                "old_part",
                                "new_part",
                                "cue_phrase",
                            ],
                        },
                    },
                    "rationale": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "replacement_intent",
                    "replacement_pairs",
                    "rationale",
                    "confidence",
                ],
            },
            "strict": True,
        },
    }
]

# EDIT THIS prompt to adjust extraction behavior, cues, or rules
SYSTEM_PROMPT = """
You are a technical extraction engine for part-number replacement analysis.

Given a comment, determine whether it expresses replacement, transition,
retirement, or alternative-selection intent between part numbers, and
identify the old and new parts.

Replacement cues include (not exhaustive):
- replaced by, retiring, transition to, path forward, alternative,
  focused on, under evaluation, current consideration, no longer viable,
  phasing out, in favor of, shifted toward, movement away from,
  sourcing review introduced, provisional replacement

Rules:
- Identify part numbers directly from the text (alphanumeric codes with
  possible dots, slashes, underscores, dashes).
- old_part = the part being replaced/retired/phased out.
- new_part = the part replacing it / being adopted.
- cue_phrase = the phrase in the text that signals the replacement.
- If the text mentions two parts but the direction is ambiguous,
  set replacement_intent=true and leave replacement_pairs empty.
- If no replacement intent exists, set replacement_intent=false
  and leave replacement_pairs empty.
- Provide a short rationale (1–2 sentences).
- Provide confidence 0.0–1.0.

Examples:

INPUT: "Prior configuration referenced H70SQ5R and a potential path forward now includes 5G8MBJII1"
OUTPUT: replacement_intent=true,
        replacement_pairs=[{old_part="H70SQ5R", new_part="5G8MBJII1", cue_phrase="path forward now includes"}],
        confidence=0.85,
        rationale="H70SQ5R is the prior configuration and 5G8MBJII1 is presented as the path forward, indicating a transition."

INPUT: "Manufacturing feedback suggests phasing out V18NLT4L5 in favor of R1KEWIQ74RNA-7R"
OUTPUT: replacement_intent=true,
        replacement_pairs=[{old_part="V18NLT4L5", new_part="R1KEWIQ74RNA-7R", cue_phrase="phasing out...in favor of"}],
        confidence=0.95,
        rationale="Explicit phase-out language with a direct old-to-new mapping."

INPUT: "Engineering review notes PA_IHJ2 with provisional replacement identified as 6FATN_SPGV"
OUTPUT: replacement_intent=true,
        replacement_pairs=[{old_part="PA_IHJ2", new_part="6FATN_SPGV", cue_phrase="provisional replacement identified as"}],
        confidence=0.9,
        rationale="The text directly identifies 6FATN_SPGV as a provisional replacement for PA_IHJ2."

INPUT: "Material availability constraints around B.R9J1TO and 9LA8XRP surfaced during review"
OUTPUT: replacement_intent=false,
        replacement_pairs=[],
        confidence=0.7,
        rationale="Both parts are mentioned together but no directional replacement language is present."
"""

def build_user_payload(raw: str) -> str:
    """Build the user message sent to the LLM: raw + cleaned text."""
    cleaned = clean_text(raw)
    return (
        "TEXT:\n"
        f"{cleaned}"
    )

# ---------------------------------------------------------------------------
# SQL Server pipeline — connects to SQL Server, calls LLM per row, writes Excel
# ---------------------------------------------------------------------------
# SET THESE in .env:
#   SQL_SERVER             → SQL Server hostname or IP
#   SQL_DATABASE           → database name
#   SQL_QUERY              → SELECT query to pull comments
#   SQL_DRIVER             → ODBC driver (default: ODBC Driver 18 for SQL Server)
#   SQL_TRUSTED_CONNECTION → yes = Windows auth, no = SQL auth
#   SQL_USERNAME           → only needed if SQL_TRUSTED_CONNECTION=no
#   SQL_PASSWORD           → only needed if SQL_TRUSTED_CONNECTION=no
#   OUTPUT_XLSX            → base name for the results file (default: sql_output.xlsx)
#   TEXT_COLUMN            → column name containing the text (default: Comments)

SQL_SERVER   = os.environ["SQL_SERVER"]
SQL_DATABASE = os.environ["SQL_DATABASE"]
SQL_QUERY    = os.environ["SQL_QUERY"]
TRUSTED_CONN = os.getenv("SQL_TRUSTED_CONNECTION", "no").lower() == "yes"

# Auto-detect the best available SQL Server ODBC driver
def detect_odbc_driver() -> str:
    preferred = ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"]
    available = [d for d in pyodbc.drivers() if "SQL Server" in d]
    for driver in preferred:
        if driver in available:
            return driver
    if available:
        return available[0]
    raise RuntimeError(
        "No SQL Server ODBC driver found. "
        "Install 'ODBC Driver 17 for SQL Server' or 'ODBC Driver 18 for SQL Server'."
    )

SQL_DRIVER = os.getenv("SQL_DRIVER") or detect_odbc_driver()
print(f"Using ODBC driver: {SQL_DRIVER}")

OUTPUT_XLSX  = os.getenv("OUTPUT_XLSX", "sql_output.xlsx")
TEXT_COLUMN  = os.getenv("TEXT_COLUMN", "Comments")

# Build connection string
if TRUSTED_CONN:
    conn_str = (
        f"DRIVER={{{SQL_DRIVER}}};"
        f"SERVER={SQL_SERVER};"
        f"DATABASE={SQL_DATABASE};"
        f"Trusted_Connection=yes;"
        f"TrustServerCertificate=yes;"
    )
else:
    SQL_USERNAME = os.environ["SQL_USERNAME"]
    SQL_PASSWORD = os.environ["SQL_PASSWORD"]
    conn_str = (
        f"DRIVER={{{SQL_DRIVER}}};"
        f"SERVER={SQL_SERVER};"
        f"DATABASE={SQL_DATABASE};"
        f"UID={SQL_USERNAME};"
        f"PWD={SQL_PASSWORD};"
        f"TrustServerCertificate=yes;"
    )

print(f"Connecting to {SQL_SERVER}/{SQL_DATABASE} ...")
conn = pyodbc.connect(conn_str)
df = pd.read_sql(SQL_QUERY, conn)
conn.close()
print(f"Pulled {len(df)} rows from SQL Server")

# Validate that the expected text column exists
if TEXT_COLUMN not in df.columns:
    raise KeyError(
        f"Column '{TEXT_COLUMN}' not found in SQL results. "
        f"Available columns: {list(df.columns)}"
    )

# Timestamp the output file (e.g. 20260312145800_sql_output.xlsx)
script_dir = os.path.dirname(os.path.abspath(__file__))
timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
directory, filename = os.path.split(os.path.join(script_dir, OUTPUT_XLSX))
OUTPUT_PATH = os.path.join(directory, f"{timestamp}_{filename}")

# Add output columns if they don't already exist
for col in [
    "replacement_intent",
    "old_part",
    "new_part",
    "cue_phrase",
    "confidence",
    "rationale",
    "error",
]:
    if col not in df.columns:
        df[col] = None

# ---- Main loop: iterate over every row and call the LLM ----
for idx, row in tqdm(df.iterrows(), total=len(df), desc="Extracting"):
    raw_text = row.get(TEXT_COLUMN)

    # Skip empty / non-string rows
    if not isinstance(raw_text, str) or not raw_text.strip():
        continue

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_payload(raw_text)},
    ]

    try:
        # Force the LLM to always call record_extraction (not optional)
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            tools=tools,
            tool_choice={"type": "function", "function": {"name": "record_extraction"}},
            parallel_tool_calls=False,
        )

        msg = resp.choices[0].message

        if not msg.tool_calls:
            raise RuntimeError("No tool call returned")

        # Parse the structured arguments the LLM returned
        args = json.loads(msg.tool_calls[0].function.arguments)

        # Write results into the DataFrame row
        df.at[idx, "replacement_intent"] = int(args["replacement_intent"])
        pairs = args["replacement_pairs"]
        if pairs:
            # Flatten the first replacement pair into separate columns
            df.at[idx, "old_part"] = pairs[0].get("old_part", "")
            df.at[idx, "new_part"] = pairs[0].get("new_part", "")
            df.at[idx, "cue_phrase"] = pairs[0].get("cue_phrase", "")
        df.at[idx, "confidence"] = args["confidence"]
        df.at[idx, "rationale"] = args["rationale"]
        df.at[idx, "error"] = None

    except Exception as e:
        # Log the error in the row so you can spot failures in the output
        df.at[idx, "error"] = str(e)

# Write the final results to Excel
df.to_excel(OUTPUT_PATH, index=False, engine="openpyxl")
print(f"\nSaved results to: {OUTPUT_PATH}")