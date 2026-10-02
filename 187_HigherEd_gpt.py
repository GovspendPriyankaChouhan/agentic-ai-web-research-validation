import os
import json
import time
import random

import gspread
from google.oauth2.service_account import Credentials
from openai import OpenAI
from gspread.utils import rowcol_to_a1
from pathlib import Path
from dotenv import load_dotenv


# ============================================================
# ENVIRONMENT CONFIGURATION
# ============================================================

ROOT_DIR = Path(__file__).resolve().parent

load_dotenv(ROOT_DIR / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME")

CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE")
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
WORKSHEET_NAME = os.getenv("GOOGLE_WORKSHEET_NAME")

BATCH_SIZE = 50

START_ROW = 4828
STOP_ROW = 5820


# ============================================================
# COLUMN MAP
# ============================================================

# INPUT
COL_ACCOUNT_NAME = 4       # Column D
COL_CITY_IN = 6            # Column F
COL_STATE = 7              # Column G

# OUTPUT
COL_NAME = 13              # Column M
COL_CITY = 14              # Column N
COL_STATE_OUT = 15         # Column O
COL_FISCAL_YEAR = 16       # Column P
COL_COUNTY_NAME = 17       # Column Q
COL_ADDRESS = 18           # Column R
COL_STATUS = 19            # Column S
COL_TOKEN_USED = 20        # Column T
COL_TIME_TAKEN = 21        # Column U


# ============================================================
# PROMPT
# ============================================================

PROMPT_TEMPLATE = """
Find the fiscal year start month for the given US higher education institution and extract key details from the same source.

ENTITY: {account_name}, {city}, {state}

CRITICAL: Many higher education institutions share similar names across different states (e.g., "Community College", "State University" exist in multiple states). A university system may have multiple distinct campuses (e.g., "University of Colorado Denver" is distinct from "University of Colorado Boulder") — each campus is a separate entity with its own financials and potentially its own fiscal year. You MUST verify the entity is in the correct state ({state}) and correct city ({city}) before extracting any data.

TASK:
1. Find the official fiscal year start month (the month when their fiscal year BEGINS, e.g., July 1 = 7, October 1 = 10, January 1 = 1)
2. From the SAME SOURCE, extract: official name, city, state abbreviation, county (optional), address (optional - typically the main administrative office address), and IPEDS Unit ID if available

SOURCES (in priority order):
1. IPEDS (Integrated Postsecondary Education Data System) — https://nces.ed.gov/ipeds/ — PRIMARY source, like IMLS for libraries
2. Official institution website (About, Finance, or Administration pages)
3. ACFR/CAFR annual financial reports
4. State higher education board or system financial documents
5. Audit reports or actuarial valuation reports

RULES:
- Only use explicitly stated information - do NOT fabricate or infer
- name, city, state, fiscal_year_start_month are MANDATORY
- county, address, and ipeds_unit_id are OPTIONAL - leave blank if not found
- VERIFY the entity is in the correct state ({state}) and correct city ({city})
- Public university systems (e.g., "University of California System") are distinct from individual campuses (e.g., "UC Berkeley", "UCLA") — verify the fiscal year for the SPECIFIC institution named
- Community colleges, technical colleges, BOCES, and vocational institutions are distinct entities even if they share a district — do NOT merge or swap their data
- A BOCES (Board of Cooperative Educational Services) is a regional educational service agency in New York State — treat as a distinct higher ed/vocational entity
- Do not confuse with similarly named institutions in other states or cities
- Most public universities follow their state's fiscal year (July 1) but exceptions exist — always verify explicitly, do not assume
- Use most recent data if multiple records exist

EXAMPLE OUTPUT:
{{"name":"Cerritos College","city":"Norwalk","state":"CA","fiscal_year_start_month":7,"county":"Los Angeles County","address":"11110 Alondra Blvd, Norwalk, CA 90650","ipeds_unit_id":"110486"}}

OUTPUT: Return ONLY a minified JSON object with these keys:
"name", "city", "state", "fiscal_year_start_month", "county", "address", "ipeds_unit_id"
"""


# ============================================================
# GOOGLE SHEETS CONNECTION
# ============================================================

def google_sheet_connection(sheet_id):
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets"
    ]

    creds = Credentials.from_service_account_file(
        CREDENTIALS_FILE,
        scopes=scopes
    )

    client = gspread.authorize(creds)

    return client.open_by_key(sheet_id)


# ============================================================
# SAFE BATCH UPDATE
# ============================================================

def safe_batch_update(ws, requests_list, retries=5):
    for attempt in range(retries):
        try:
            ws.batch_update(requests_list)
            return

        except Exception as e:
            if "429" in str(e):
                sleep_time = (2 ** attempt) + random.random()

                print(
                    f"Rate limited by Sheets API. "
                    f"Sleeping {sleep_time:.2f}s ..."
                )

                time.sleep(sleep_time)

            else:
                raise


# ============================================================
# PARSE JSON FROM MODEL OUTPUT
# ============================================================

def parse_result(raw_text: str) -> dict:
    """Strip accidental markdown fences and parse JSON."""

    text = raw_text.strip()

    if text.startswith("```"):
        lines = text.splitlines()

        text = "\n".join(
            line
            for line in lines
            if not line.strip().startswith("```")
        ).strip()

    return json.loads(text)


# ============================================================
# MAIN
# ============================================================

def main():

    # Validate required environment configuration
    required_config = {
        "OPENAI_API_KEY": OPENAI_API_KEY,
        "MODEL_NAME": MODEL_NAME,
        "GOOGLE_CREDENTIALS_FILE": CREDENTIALS_FILE,
        "GOOGLE_SHEET_ID": SHEET_ID,
        "GOOGLE_WORKSHEET_NAME": WORKSHEET_NAME,
    }

    missing = [
        name
        for name, value in required_config.items()
        if not value
    ]

    if missing:
        raise RuntimeError(
            "Missing required environment variables: "
            + ", ".join(missing)
        )

    client = OpenAI(
        api_key=OPENAI_API_KEY
    )

    print("Connecting to Google Sheets ...")

    sheet = google_sheet_connection(
        SHEET_ID
    )

    ws = sheet.worksheet(
        WORKSHEET_NAME
    )

    print("Fetching all sheet data ...")

    all_values = ws.get_all_values()

    start_index = START_ROW - 2
    stop_index = STOP_ROW - 2

    total_data_rows = len(all_values) - 1

    effective_stop = min(
        stop_index,
        total_data_rows - 1
    )

    print(
        f"Processing sheet rows "
        f"{START_ROW} → "
        f"{min(STOP_ROW, total_data_rows + 1)} "
        f"({effective_stop - start_index + 1} rows) ..."
    )

    for batch_start in range(
        start_index,
        effective_stop + 1,
        BATCH_SIZE
    ):

        batch_end = min(
            batch_start + BATCH_SIZE - 1,
            effective_stop
        )

        batch_rows = all_values[
            batch_start + 1:
            batch_end + 2
        ]

        sheet_updates = []

        print(
            f"\nBatch: sheet rows "
            f"{batch_start + 2} → "
            f"{batch_end + 2}"
        )

        for offset, row in enumerate(
            batch_rows
        ):

            sheet_row_number = (
                batch_start + offset + 2
            )

            def cell(col_idx):
                idx = col_idx - 1

                return (
                    row[idx].strip()
                    if idx < len(row)
                    else ""
                )

            # Skip already processed rows
            if cell(COL_STATUS).lower() == "done":
                print(
                    f"Row {sheet_row_number}: "
                    f"already Done, skipping."
                )
                continue

            account_name = cell(
                COL_ACCOUNT_NAME
            )

            city_in = cell(
                COL_CITY_IN
            )

            state = cell(
                COL_STATE
            )

            if not account_name or not state:
                print(
                    f"Row {sheet_row_number}: "
                    f"missing AccountName or State, skipping."
                )
                continue

            print(
                f"Row {sheet_row_number}: "
                f"'{account_name}' / "
                f"'{city_in}' / "
                f"'{state}' ..."
            )

            start_time = time.time()

            try:

                prompt = PROMPT_TEMPLATE.format(
                    account_name=account_name,
                    city=city_in,
                    state=state
                )

                response = client.responses.create(
                    model=MODEL_NAME,
                    tools=[
                        {"type": "web_search"}
                    ],
                    input=prompt
                )

                raw_text = (
                    response.output_text.strip()
                )

                token_used = (
                    response.usage.total_tokens
                )

                elapsed = round(
                    time.time() - start_time,
                    2
                )

                result = parse_result(
                    raw_text
                )

                # Normalize fiscal year
                # to a clean integer string
                fy_raw = str(
                    result.get(
                        "fiscal_year_start_month",
                        ""
                    )
                ).strip()

                try:
                    fiscal_year = (
                        str(int(float(fy_raw)))
                        if fy_raw
                        else ""
                    )

                except ValueError:
                    fiscal_year = fy_raw

                update_map = {

                    COL_NAME:
                        result.get(
                            "name",
                            ""
                        ),

                    COL_CITY:
                        result.get(
                            "city",
                            ""
                        ),

                    COL_STATE_OUT:
                        result.get(
                            "state",
                            ""
                        ),

                    COL_FISCAL_YEAR:
                        fiscal_year,

                    COL_COUNTY_NAME:
                        result.get(
                            "county",
                            ""
                        ),

                    COL_ADDRESS:
                        result.get(
                            "address",
                            ""
                        ),

                    COL_STATUS:
                        "Done",

                    COL_TOKEN_USED:
                        token_used,

                    COL_TIME_TAKEN:
                        elapsed,
                }

                print(
                    f"{result.get('name')} | "
                    f"FY start month: "
                    f"{fiscal_year} | "
                    f"{token_used} tokens | "
                    f"{elapsed}s"
                )

            except Exception as e:

                elapsed = round(
                    time.time() - start_time,
                    2
                )

                print(
                    f"Row {sheet_row_number} "
                    f"error: {e}"
                )

                update_map = {

                    COL_STATUS:
                        "Error",

                    COL_TOKEN_USED:
                        0,

                    COL_TIME_TAKEN:
                        elapsed,
                }

            for col, val in update_map.items():

                sheet_updates.append({
                    "range": rowcol_to_a1(
                        sheet_row_number,
                        col
                    ),
                    "values": [[val]],
                })

        # Write entire batch in one
        # Sheets API call
        if sheet_updates:

            print(
                f"Writing "
                f"{len(sheet_updates)} cells "
                f"to sheet ..."
            )

            safe_batch_update(
                ws,
                sheet_updates
            )

            time.sleep(3)

    print(
        f"\nCompleted! "
        f"Processed sheet rows "
        f"{START_ROW} → {STOP_ROW}."
    )


if __name__ == "__main__":
    main()
