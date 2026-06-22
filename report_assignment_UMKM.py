import time

import pandas as pd
import requests
from tqdm import tqdm

from fasih_common import (
    REGIONS_FILE,
    apply_scope_to_report_payload,
    build_authenticated_headers,
    expand_scope_to_level5,
    get_random_delay,
    load_json,
    prompt_regions_file,
    prompt_region_scope,
    response_json,
    save_json,
    scoped_output_name,
)
from login import login_with_sso


REPORT_API_URL = (
    "https://fasih-sm.bps.go.id/app/api/analytic/api/v2/assignment/"
    "report-progress-assignment"
)
PAYLOAD_FILE = "payload_report_assignment.json"
FAILED_SCOPES_FILE = "failed_report_scopes.json"
REPORT_NAVIGATION_TIMEOUT_MS = 600_000
MAX_RETRY_ATTEMPTS = 5
RETRY_BACKOFF_SECONDS = (1, 2, 4, 4)


def flatten_report_response(data, selected_scope, query_scope):
    rows = []

    for region_item in data or []:
        region_label = region_item.get("label")
        for status_item in region_item.get("values") or []:
            rows.append(
                {
                    "selected_level": selected_scope["level"],
                    "selected_fullCode": selected_scope["fullCode"],
                    "query_level": query_scope["level"],
                    "query_fullCode": query_scope["fullCode"],
                    "region_label": region_label,
                    "status_label": status_item.get("label"),
                    "value": status_item.get("value"),
                }
            )

    return rows


def prompt_run_mode():
    try:
        failed_data = load_json(FAILED_SCOPES_FILE)
        failed_scopes = failed_data.get("failed_scopes") or []
        if failed_scopes:
            answer = input(
                f"Ditemukan {len(failed_scopes)} failed scope. "
                "Jalankan hanya failed_report_scopes? [Y/n]: "
            ).strip().lower()
            if answer in {"", "y", "yes"}:
                return "failed"
    except Exception:
        pass

    mode = input("Mode fetch [all/failed] (default: all): ").strip().lower()
    return mode or "all"


def load_failed_run_context():
    failed_data = load_json(FAILED_SCOPES_FILE)
    selected_scope = failed_data.get("selected_scope")
    query_scopes = failed_data.get("failed_scopes") or []

    if not selected_scope or not query_scopes:
        raise ValueError(f"Tidak ada failed scope yang bisa dijalankan ulang di {FAILED_SCOPES_FILE}.")

    return selected_scope, query_scopes


def fetch_report_with_retry(session, headers, payload, query_scope, max_attempts=MAX_RETRY_ATTEMPTS):
    for attempt in range(1, max_attempts + 1):
        try:
            response = session.post(
                REPORT_API_URL,
                json=payload,
                headers=headers,
                timeout=60,
            )
            return response_json(
                response,
                f"Report for level5 {query_scope['fullCode']}",
            )
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt >= max_attempts:
                raise

            backoff = RETRY_BACKOFF_SECONDS[min(attempt - 1, len(RETRY_BACKOFF_SECONDS) - 1)]
            print(
                f"\nRetry report {query_scope['fullCode']} "
                f"(attempt {attempt + 1}/{max_attempts}) after error: {e}"
            )
            time.sleep(backoff)


def run_report_scopes(session, headers, payload_template, selected_scope, query_scopes, description):
    raw_results = []
    rows = []
    failed_scopes = []

    for query_scope in tqdm(query_scopes, desc=description, unit="scope"):
        try:
            payload = apply_scope_to_report_payload(payload_template, query_scope, max_level=5)
            time.sleep(get_random_delay())
            data = fetch_report_with_retry(
                session,
                headers,
                payload,
                query_scope,
            )
            raw_results.append(
                {
                    "selected_level": selected_scope["level"],
                    "selected_fullCode": selected_scope["fullCode"],
                    "query_level": query_scope["level"],
                    "query_fullCode": query_scope["fullCode"],
                    "response": data,
                }
            )
            rows.extend(flatten_report_response(data, selected_scope, query_scope))
        except Exception as e:
            failed_scopes.append(query_scope)
            print(f"\nGagal mengambil report {query_scope['fullCode']}: {e}")

    return raw_results, rows, failed_scopes


def main():
    run_mode = prompt_run_mode()
    if run_mode == "failed":
        selected_scope, query_scopes = load_failed_run_context()
        raw_output_file = scoped_output_name("report_assignment_UMKM_failed_only", "json", selected_scope)
        excel_output_file = scoped_output_name("report_assignment_UMKM_failed_only", "xlsx", selected_scope)
    else:
        regions_file = prompt_regions_file(default=REGIONS_FILE)
        regions = load_json(regions_file)
        selected_scope = prompt_region_scope(regions, regions_file=regions_file, max_level=5)
        query_scopes = expand_scope_to_level5(regions, selected_scope)
        raw_output_file = scoped_output_name("report_assignment_UMKM", "json", selected_scope)
        excel_output_file = scoped_output_name("report_assignment_UMKM", "xlsx", selected_scope)

    print(
        f"Mengambil report assignment untuk level{selected_scope['level']} "
        f"{selected_scope['fullCode']} {selected_scope.get('name') or ''}\n"
        f"Jumlah level-5 yang akan diambil: {len(query_scopes)}\n"
    )

    if not query_scopes:
        print("Tidak ada wilayah level-5 di bawah scope yang dipilih.")
        return

    page, browser = login_with_sso()
    if not page:
        print("Login gagal. Tidak dapat mengambil report.")
        return

    session = requests.Session()

    try:
        page.goto("https://fasih-sm.bps.go.id/app/surveys", timeout=REPORT_NAVIGATION_TIMEOUT_MS)
        page.wait_for_load_state("networkidle", timeout=REPORT_NAVIGATION_TIMEOUT_MS)
        headers = build_authenticated_headers(page)
        payload_template = load_json(PAYLOAD_FILE)

        raw_results, rows, failed_scopes = run_report_scopes(
            session,
            headers,
            payload_template,
            selected_scope,
            query_scopes,
            "Fetching report level-5 scopes",
        )

        if failed_scopes:
            print(
                f"\nMenjalankan ulang {len(failed_scopes)} failed scope "
                "dalam sesi yang sama..."
            )
            retry_raw_results, retry_rows, failed_scopes = run_report_scopes(
                session,
                headers,
                payload_template,
                selected_scope,
                failed_scopes,
                "Retrying failed report scopes",
            )
            raw_results.extend(retry_raw_results)
            rows.extend(retry_rows)

        save_json(raw_output_file, raw_results)
        pd.DataFrame(rows).to_excel(excel_output_file, index=False)
        save_json(
            FAILED_SCOPES_FILE,
            {
                "selected_scope": selected_scope,
                "failed_scopes": failed_scopes,
            },
        )

        print(f"Raw report saved to {raw_output_file}")
        print(f"Flattened report saved to {excel_output_file}")
        print(f"Total rows: {len(rows)}")
        if failed_scopes:
            print(f"Failed level-5 scopes: {len(failed_scopes)}")
            print(", ".join(scope["fullCode"] for scope in failed_scopes))
            print(f"Failed scopes saved to {FAILED_SCOPES_FILE}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        session.close()
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
