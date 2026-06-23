from copy import deepcopy
import json
import random
import time

import pandas as pd
import requests
from tqdm import tqdm

from login import login_with_sso


API_URL = "https://fasih-sm.bps.go.id/analytic/api/v2/assignment/datatable-all-user-survey-periode"
PAYLOAD_FILE = "payload_UB.json"
OUTPUT_FILE = "scraped_data.xlsx"
PAGE_LENGTH = 100

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    "Connection": "keep-alive",
}


def get_random_delay(min_sec=1, max_sec=3):
    return random.uniform(min_sec, max_sec)


def load_payload_template(path=PAYLOAD_FILE):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def nested_get(data, path, default=None):
    current = data
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def build_payload(payload_template, start, length):
    payload = deepcopy(payload_template)
    payload["start"] = start
    payload["length"] = length
    return payload


def extract_record(record):
    return {
        "data1": record.get("data1"),
        "data2": record.get("data2"),
        "data3": record.get("data3"),
        "data4": record.get("data4"),
        "data5": record.get("data5"),
        "data6": record.get("data6"),
        "data7": record.get("data7"),
        "email": record.get("email"),
        "assignmentStatusAlias": record.get("assignmentStatusAlias"),
        "currentUserFullname": record.get("currentUserFullname"),
        "currentUserUsername": record.get("currentUserUsername"),
        "currentUserSurveyRoleName": record.get("currentUserSurveyRoleName"),
        "level5_fullCode": nested_get(
            record,
            ["region", "level1", "level2", "level3", "level4", "level5", "fullCode"],
        ),
    }


def fetch_all_pages(session, headers, payload_template):
    all_records = []
    total_hit = None
    page = 0
    pbar = None

    while True:
        start = page * PAGE_LENGTH
        payload = build_payload(payload_template, start=start, length=PAGE_LENGTH)

        try:
            time.sleep(get_random_delay())
            response = session.post(API_URL, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            try:
                data = response.json()
            except ValueError as e:
                content_type = response.headers.get("Content-Type", "")
                snippet = response.text[:500].replace("\n", " ").replace("\r", " ")
                print(f"Invalid JSON response on page {page + 1}: {e}")
                print(f"Status code: {response.status_code}")
                print(f"Content-Type: {content_type}")
                print(f"Response preview: {snippet}")
                break

            if total_hit is None:
                total_hit = data.get("totalHit", 0)
                pbar = tqdm(total=total_hit, desc="Fetching records", unit="record")

            search_data = data.get("searchData") or []
            if not search_data:
                break

            for record in search_data:
                all_records.append(extract_record(record))

            if pbar is not None:
                pbar.update(len(search_data))

            if total_hit and len(all_records) >= total_hit:
                break

            page += 1

        except requests.exceptions.Timeout:
            print(f"Timeout on page {page + 1}, retrying after delay...")
            time.sleep(get_random_delay(3, 5))
        except requests.exceptions.RequestException as e:
            print(f"Request error on page {page + 1}: {e}")
            break

    if pbar is not None:
        pbar.close()

    return all_records, total_hit


def build_authenticated_headers(page):
    cookies = page.context.cookies()
    cookie_string = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
    xsrf_token = next((c["value"] for c in cookies if c["name"] == "XSRF-TOKEN"), None)

    headers = DEFAULT_HEADERS.copy()
    headers["Cookie"] = cookie_string
    headers["Referer"] = "https://fasih-sm.bps.go.id/"
    if xsrf_token:
        headers["X-XSRF-TOKEN"] = xsrf_token

    return headers


def main():
    print("Melakukan login otomatis...\n")

    payload_template = load_payload_template()
    page, browser = login_with_sso()

    if not page:
        print("Login gagal. Tidak dapat melanjutkan scraping.")
        return

    try:
        page.goto("https://fasih-sm.bps.go.id/app/surveys", timeout=60000)
        page.wait_for_load_state("networkidle")
        headers = build_authenticated_headers(page)
        print("Cookies diperoleh\n")
    except Exception as e:
        print(f"Error saat login atau ekstraksi cookies: {e}")
        return

    session = requests.Session()

    try:
        records, total_hit = fetch_all_pages(session, headers, payload_template)
        if not records:
            print("Tidak ada data yang disimpan karena tidak ada record yang berhasil diambil.")
            return

        df = pd.DataFrame(
            records,
            columns=[
                "data1",
                "data2",
                "data3",
                "data4",
                "data5",
                "data6",
                "data7",
                "email",
                "assignmentStatusAlias",
                "currentUserFullname",
                "currentUserUsername",
                "currentUserSurveyRoleName",
                "level5_fullCode",
            ],
        )
        df.to_excel(OUTPUT_FILE, index=False)

        print(f"Data saved to {OUTPUT_FILE}")
        print(f"Total records fetched: {len(records)}")
        if total_hit is not None and len(records) != total_hit:
            print(f"Warning: API totalHit is {total_hit}, but fetched {len(records)} records.")
    except Exception as e:
        print(f"Error saving data: {e}")
    finally:
        session.close()
        if browser:
            try:
                input("Tekan Enter untuk menutup browser...")
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
