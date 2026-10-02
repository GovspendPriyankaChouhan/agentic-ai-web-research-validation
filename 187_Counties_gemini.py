import os
import json
import time
import random

import gspread
from google.genai import Client
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1
from dotenv import load_dotenv

# ------------------- ENVIRONMENT CONFIGURATION -------------------
load_dotenv()

CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE")
SHEET_ID = os.getenv("COUNTY_GOOGLE_SHEET_ID")
WORKSHEET_NAME = os.getenv(
    "COUNTY_GEMINI_WORKSHEET_NAME",
    "counties_gemini"
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = os.getenv(
    "GEMINI_MODEL_NAME",
    "gemini-3.5-flash"
)

BATCH_SIZE = 50
START_ROW = 2
STOP_ROW = 200
# -----------------------------------------------------------------


# ------------------- COLUMN MAP -------------------
COL_ACCOUNT_NAME = 4
COL_STATE = 7

COL_NAME = 13
COL_CITY = 14
COL_STATE_OUT = 15
COL_FISCAL_YEAR = 16
COL_COUNTY_NAME = 17
COL_ADDRESS = 18
COL_STATUS = 19
COL_TOKEN_USED = 20
COL_TIME_TAKEN = 21
# --------------------------------------------------


PROMPT_TEMPLATE = """
Find the fiscal year start month for the given US government entity and extract key details from the same source.

ENTITY: {account_name}, {state}

CRITICAL: You MUST use BOTH the exact agency name ({account_name}) AND the state ({state}) when searching for the fiscal year. Do not search for a different entity or assume the fiscal year without verifying it matches this specific agency in this specific state.

TASK:
1. Find the official fiscal year start month (the month when their fiscal year BEGINS, e.g., July 1 = 7, October 1 = 10, January 1 = 1) for {account_name} in {state}
2. From the SAME SOURCE, extract: official name, city, state abbreviation, county (optional), and address (optional)

SOURCES: Use ACFR/CAFR, official government websites, audit reports, or budget documents.

RULES:
- Search using the exact agency name ({account_name}) and state ({state}) provided
- Only use explicitly stated information - do NOT fabricate or infer
- name, city, state, fiscal_year_start_month are MANDATORY
- county and address are OPTIONAL - leave blank if not found
- VERIFY the entity is in the correct state ({state}) before extracting fiscal year data
- Do not provide fiscal year data for a different entity or different state
- Use most recent data if multiple records exist

OUTPUT: Return ONLY a minified JSON object with these keys:
"name", "city", "state", "fiscal_year_start_month", "county", "address"
"""


def google_sheet_connection(sheet_id):
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(
        CREDENTIALS_FILE,
        scopes=scopes
    )
    client = gspread.authorize(creds)
    return client.open_by_key(sheet_id)


def safe_batch_update(ws, requests_list, retries=5):
    for attempt in range(retries):
        try:
            ws.batch_update(requests_list)
            return
        except Exception as e:
            if "429" in str(e):
                sleep_time = (2 ** attempt) + random.random()
                print(
                    f"Rate limited. Sleeping "
                    f"{sleep_time:.2f}s ..."
                )
                time.sleep(sleep_time)
            else:
                raise


def parse_result(raw_text: str) -> dict:
    text = raw_text.strip()

    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        ).strip()

    return json.loads(text)


def main():
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not configured.")

    if not CREDENTIALS_FILE:
        raise ValueError("GOOGLE_CREDENTIALS_FILE is not configured.")

    if not SHEET_ID:
        raise ValueError(
            "COUNTY_GOOGLE_SHEET_ID is not configured."
        )

    client = Client(api_key=GEMINI_API_KEY)

    print("Connecting to Google Sheets ...")
    sheet = google_sheet_connection(SHEET_ID)
    ws = sheet.worksheet(WORKSHEET_NAME)

    print("Fetching sheet data ...")
    all_values = ws.get_all_values()

    start_index = START_ROW - 2
    stop_index = STOP_ROW - 2
    total_data_rows = len(all_values) - 1
    effective_stop = min(stop_index, total_data_rows - 1)

    print(
        f"Processing rows {START_ROW} → "
        f"{min(STOP_ROW, total_data_rows + 1)}"
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
            batch_start + 1 : batch_end + 2
        ]

        sheet_updates = []

        for offset, row in enumerate(batch_rows):
            sheet_row_number = batch_start + offset + 2

            def cell(col_idx):
                idx = col_idx - 1
                return row[idx].strip() if idx < len(row) else ""

            if cell(COL_STATUS).lower() == "done":
                continue

            account_name = cell(COL_ACCOUNT_NAME)
            state = cell(COL_STATE)

            if not account_name or not state:
                continue

            print(
                f"Row {sheet_row_number}: "
                f"{account_name} / {state}"
            )

            start_time = time.time()

            try:
                prompt = PROMPT_TEMPLATE.format(
                    account_name=account_name,
                    state=state
                )

                response = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=prompt
                )

                raw_text = response.text.strip()
                elapsed = round(time.time() - start_time, 2)

                token_used = (
                    response.usage_metadata.total_token_count
                    if hasattr(response, "usage_metadata")
                    and response.usage_metadata
                    else 0
                )

                result = parse_result(raw_text)

                fy_raw = str(
                    result.get("fiscal_year_start_month", "")
                ).strip()

                try:
                    fiscal_year = (
                        str(int(float(fy_raw)))
                        if fy_raw else ""
                    )
                except ValueError:
                    fiscal_year = fy_raw

                update_map = {
                    COL_NAME: result.get("name", ""),
                    COL_CITY: result.get("city", ""),
                    COL_STATE_OUT: result.get("state", ""),
                    COL_FISCAL_YEAR: fiscal_year,
                    COL_COUNTY_NAME: result.get("county", ""),
                    COL_ADDRESS: result.get("address", ""),
                    COL_STATUS: "Done",
                    COL_TOKEN_USED: token_used,
                    COL_TIME_TAKEN: elapsed,
                }

                print(
                    f"FY: {fiscal_year} | "
                    f"Tokens: {token_used} | {elapsed}s"
                )

            except Exception as e:
                elapsed = round(time.time() - start_time, 2)

                print(
                    f"Error row {sheet_row_number}: {e}"
                )

                update_map = {
                    COL_STATUS: "Error",
                    COL_TOKEN_USED: 0,
                    COL_TIME_TAKEN: elapsed,
                }

            for col, val in update_map.items():
                sheet_updates.append({
                    "range": rowcol_to_a1(
                        sheet_row_number,
                        col
                    ),
                    "values": [[val]],
                })

        if sheet_updates:
            safe_batch_update(ws, sheet_updates)
            time.sleep(3)

    print("Completed.")


if __name__ == "__main__":
    main()
