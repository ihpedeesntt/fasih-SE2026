import time

import pandas as pd
import requests
from tqdm import tqdm

from fasih_common import (
    REGIONS_FILE,
    apply_scope_to_report_payload,
    build_authenticated_headers,
    expand_scope_to_level,
    get_random_delay,
    load_json,
    prompt_regions_file,
    prompt_region_scope,
    response_json,
    save_json,
    scoped_output_name,
)
from login import login_with_sso


REPORT_NAVIGATION_TIMEOUT_MS = 600_000


def flatten_label_values_response(data, selected_scope, query_scope):
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


def prompt_run_mode(failed_scopes_file):
    try:
        failed_data = load_json(failed_scopes_file)
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


def load_failed_run_context(failed_scopes_file):
    failed_data = load_json(failed_scopes_file)
    selected_scope = failed_data.get("selected_scope")
    query_scopes = failed_data.get("failed_scopes") or []

    if not selected_scope or not query_scopes:
        raise ValueError(f"Tidak ada failed scope yang bisa dijalankan ulang di {failed_scopes_file}.")

    return selected_scope, query_scopes


def fetch_report_with_retry(
    session,
    headers,
    payload,
    query_scope,
    report_api_url,
    max_attempts,
    retry_backoff_seconds,
    request_timeout,
):
    for attempt in range(1, max_attempts + 1):
        try:
            response = session.post(
                report_api_url,
                json=payload,
                headers=headers,
                timeout=request_timeout,
            )
            return response_json(
                response,
                f"Report for level{query_scope['level']} {query_scope['fullCode']}",
            )
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt >= max_attempts:
                raise

            backoff = retry_backoff_seconds[min(attempt - 1, len(retry_backoff_seconds) - 1)]
            print(
                f"\nRetry report {query_scope['fullCode']} "
                f"(attempt {attempt + 1}/{max_attempts}) after error: {e}"
            )
            time.sleep(backoff)


def run_report_scopes(
    session,
    headers,
    payload_template,
    selected_scope,
    query_scopes,
    description,
    report_api_url,
    max_scope_level,
    empty_is_failure,
    response_flattener,
    max_retry_attempts,
    retry_backoff_seconds,
    request_timeout,
):
    raw_results = []
    rows = []
    failed_scopes = []
    empty_scopes = []

    for query_scope in tqdm(query_scopes, desc=description, unit="scope"):
        try:
            payload = apply_scope_to_report_payload(
                payload_template,
                query_scope,
                max_level=max_scope_level,
            )
            time.sleep(get_random_delay())
            data = fetch_report_with_retry(
                session,
                headers,
                payload,
                query_scope,
                report_api_url,
                max_retry_attempts,
                retry_backoff_seconds,
                request_timeout,
            )
            flattened_rows = response_flattener(data, selected_scope, query_scope)
            raw_results.append(
                {
                    "selected_level": selected_scope["level"],
                    "selected_fullCode": selected_scope["fullCode"],
                    "query_level": query_scope["level"],
                    "query_fullCode": query_scope["fullCode"],
                    "response": data,
                }
            )
            if not flattened_rows:
                if empty_is_failure:
                    failed_scopes.append(query_scope)
                else:
                    empty_scopes.append(query_scope)
                continue

            rows.extend(flattened_rows)
        except Exception as e:
            failed_scopes.append(query_scope)
            print(f"\nGagal mengambil report {query_scope['fullCode']}: {e}")

    return raw_results, rows, failed_scopes, empty_scopes


def run_report_job(
    *,
    report_api_url,
    payload_file,
    failed_scopes_file,
    output_prefix,
    regions_file_default=REGIONS_FILE,
    regions_file_pattern="regions_UMKM*.json",
    max_scope_level=5,
    expand_target_level=5,
    empty_is_failure=False,
    response_flattener=flatten_label_values_response,
    max_retry_attempts=5,
    retry_backoff_seconds=(1, 2, 4, 4),
    request_timeout=60,
):
    run_mode = prompt_run_mode(failed_scopes_file)
    if run_mode == "failed":
        selected_scope, query_scopes = load_failed_run_context(failed_scopes_file)
        raw_output_file = scoped_output_name(f"{output_prefix}_failed_only", "json", selected_scope)
        excel_output_file = scoped_output_name(f"{output_prefix}_failed_only", "xlsx", selected_scope)
    else:
        regions_file = prompt_regions_file(
            default=regions_file_default,
            pattern=regions_file_pattern,
        )
        regions = load_json(regions_file)
        selected_scope = prompt_region_scope(
            regions,
            regions_file=regions_file,
            max_level=max_scope_level,
        )
        query_scopes = expand_scope_to_level(regions, selected_scope, expand_target_level)
        raw_output_file = scoped_output_name(output_prefix, "json", selected_scope)
        excel_output_file = scoped_output_name(output_prefix, "xlsx", selected_scope)

    print(
        f"Mengambil report assignment untuk level{selected_scope['level']} "
        f"{selected_scope['fullCode']} {selected_scope.get('name') or ''}\n"
        f"Jumlah level-{expand_target_level} yang akan diambil: {len(query_scopes)}\n"
    )

    if not query_scopes:
        print(f"Tidak ada wilayah level-{expand_target_level} di bawah scope yang dipilih.")
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
        payload_template = load_json(payload_file)

        raw_results, rows, failed_scopes, empty_scopes = run_report_scopes(
            session,
            headers,
            payload_template,
            selected_scope,
            query_scopes,
            f"Fetching report level-{expand_target_level} scopes",
            report_api_url,
            max_scope_level,
            empty_is_failure,
            response_flattener,
            max_retry_attempts,
            retry_backoff_seconds,
            request_timeout,
        )

        if failed_scopes:
            print(
                f"\nMenjalankan ulang {len(failed_scopes)} failed scope "
                "dalam sesi yang sama..."
            )
            retry_raw_results, retry_rows, failed_scopes, retry_empty_scopes = run_report_scopes(
                session,
                headers,
                payload_template,
                selected_scope,
                failed_scopes,
                f"Retrying failed report level-{expand_target_level} scopes",
                report_api_url,
                max_scope_level,
                empty_is_failure,
                response_flattener,
                max_retry_attempts,
                retry_backoff_seconds,
                request_timeout,
            )
            raw_results.extend(retry_raw_results)
            rows.extend(retry_rows)
            empty_scopes.extend(retry_empty_scopes)

        save_json(raw_output_file, raw_results)
        pd.DataFrame(rows).to_excel(excel_output_file, index=False)
        save_json(
            failed_scopes_file,
            {
                "selected_scope": selected_scope,
                "failed_scopes": failed_scopes,
            },
        )

        print(f"Raw report saved to {raw_output_file}")
        print(f"Flattened report saved to {excel_output_file}")
        print(f"Total rows: {len(rows)}")
        if empty_scopes:
            print(f"Empty level-{expand_target_level} scopes: {len(empty_scopes)}")
        if failed_scopes:
            print(f"Failed level-{expand_target_level} scopes: {len(failed_scopes)}")
            print(", ".join(scope["fullCode"] for scope in failed_scopes))
            print(f"Failed scopes saved to {failed_scopes_file}")
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
