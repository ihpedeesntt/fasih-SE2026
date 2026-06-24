import time
from pathlib import Path

import pandas as pd
import requests
from tqdm import tqdm

from fasih_common import (
    REGIONS_FILE,
    SessionExpiredError,
    apply_browser_cookies_to_session,
    apply_scope_to_report_payload,
    build_authenticated_headers,
    expand_scope_to_level,
    get_random_delay,
    list_region_cache_files,
    load_json,
    prompt_regions_file,
    prompt_region_scope,
    refresh_browser_session,
    response_json,
    save_json,
    scoped_output_name,
    scope_from_row,
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


def prompt_run_mode(
    failed_scopes_file,
    *,
    enable_batch=False,
    failed_batches_file=None,
):
    if enable_batch and failed_batches_file:
        try:
            failed_cache_files = load_failed_batch_context(failed_batches_file)
            if failed_cache_files:
                answer = input(
                    f"Ditemukan {len(failed_cache_files)} failed level-2 batch. "
                    "Jalankan hanya failed batch? [Y/n]: "
                ).strip().lower()
                if answer in {"", "y", "yes"}:
                    return "batch-failed"
        except Exception:
            pass

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

    if enable_batch:
        mode = input(
            "Mode fetch [single/failed/batch-all/batch-selected] "
            "(default: single): "
        ).strip().lower()
        mode_map = {
            "": "single",
            "all": "single",
            "single": "single",
            "failed": "failed",
            "batch-all": "batch-all",
            "batch all": "batch-all",
            "batch_selected": "batch-selected",
            "batch-selected": "batch-selected",
            "batch selected": "batch-selected",
        }
        resolved = mode_map.get(mode)
        if not resolved:
            raise ValueError("Mode harus single, failed, batch-all, atau batch-selected.")
        return resolved

    mode = input("Mode fetch [all/failed] (default: all): ").strip().lower()
    return "failed" if mode == "failed" else "single"


def load_failed_run_context(failed_scopes_file):
    failed_data = load_json(failed_scopes_file)
    selected_scope = failed_data.get("selected_scope")
    query_scopes = failed_data.get("failed_scopes") or []

    if not selected_scope or not query_scopes:
        raise ValueError(f"Tidak ada failed scope yang bisa dijalankan ulang di {failed_scopes_file}.")

    return selected_scope, query_scopes


def load_failed_batch_context(failed_batches_file):
    failed_data = load_json(failed_batches_file)
    cache_files = failed_data.get("failed_cache_files") or []
    if not cache_files:
        raise ValueError(f"Tidak ada failed level-2 batch di {failed_batches_file}.")
    return cache_files


def prompt_batch_regions_files(pattern):
    cache_files = list_region_cache_files(pattern)
    if not cache_files:
        raise ValueError(f"Tidak ada file cache wilayah yang cocok dengan pattern {pattern}.")

    print("File cache batch yang tersedia:")
    for index, cache_file in enumerate(cache_files, start=1):
        print(f"{index}. {cache_file}")

    selected = input(
        "Pilih file batch (nomor atau nama file, pisahkan dengan koma): "
    ).strip()
    if not selected:
        raise ValueError("Pilihan file batch wajib diisi.")

    picked_files = []
    for item in [part.strip() for part in selected.split(",") if part.strip()]:
        if item.isdigit():
            idx = int(item) - 1
            if idx < 0 or idx >= len(cache_files):
                raise ValueError(f"Nomor file batch tidak valid: {item}")
            cache_file = cache_files[idx]
        else:
            if item not in cache_files:
                raise ValueError(f"Nama file batch tidak ditemukan: {item}")
            cache_file = item

        if cache_file not in picked_files:
            picked_files.append(cache_file)

    return picked_files


def derive_level2_scope_from_regions(regions, regions_file):
    if not regions:
        raise ValueError(f"File cache wilayah kosong: {regions_file}")

    selected_scope = scope_from_row(regions[0], 2)
    if not selected_scope.get("id") or not selected_scope.get("fullCode"):
        raise ValueError(f"Tidak dapat menurunkan scope level-2 dari {regions_file}")
    return selected_scope


def build_single_report_job(
    *,
    output_prefix,
    failed_scopes_file,
    selected_scope,
    query_scopes,
    failed_only=False,
):
    raw_prefix = f"{output_prefix}_failed_only" if failed_only else output_prefix
    if failed_only:
        raw_output_file = scoped_output_name(raw_prefix, "json", selected_scope)
        excel_output_file = scoped_output_name(raw_prefix, "xlsx", selected_scope)
        failed_scopes_output_file = failed_scopes_file
    else:
        raw_output_file = scoped_output_name(output_prefix, "json", selected_scope)
        excel_output_file = scoped_output_name(output_prefix, "xlsx", selected_scope)
        failed_scopes_output_file = failed_scopes_file

    return {
        "selected_scope": selected_scope,
        "query_scopes": query_scopes,
        "raw_output_file": raw_output_file,
        "excel_output_file": excel_output_file,
        "failed_scopes_output_file": failed_scopes_output_file,
    }


def build_batch_report_jobs(
    *,
    cache_files,
    output_prefix,
    failed_scopes_file,
    expand_target_level,
):
    jobs = []
    failed_scopes_prefix = Path(failed_scopes_file).stem

    for regions_file in cache_files:
        regions = load_json(regions_file)
        selected_scope = derive_level2_scope_from_regions(regions, regions_file)
        query_scopes = expand_scope_to_level(regions, selected_scope, expand_target_level)
        jobs.append(
            {
                "regions_file": regions_file,
                "selected_scope": selected_scope,
                "query_scopes": query_scopes,
                "raw_output_file": scoped_output_name(output_prefix, "json", selected_scope),
                "excel_output_file": scoped_output_name(output_prefix, "xlsx", selected_scope),
                "failed_scopes_output_file": scoped_output_name(
                    failed_scopes_prefix,
                    "json",
                    selected_scope,
                ),
            }
        )

    return jobs


def fetch_report_with_retry(
    session,
    headers,
    payload,
    query_scope,
    report_api_url,
    max_attempts,
    retry_backoff_seconds,
    request_timeout,
    page=None,
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
        except SessionExpiredError:
            if page is None:
                raise
            refresh_browser_session(page, session, headers, REPORT_NAVIGATION_TIMEOUT_MS)
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
    page=None,
):
    raw_results = []
    rows = []
    failed_scopes = []
    empty_scopes = []

    for index, query_scope in enumerate(tqdm(query_scopes, desc=description, unit="scope")):
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
                page=page,
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
        except SessionExpiredError as e:
            e.raw_results = raw_results
            e.rows = rows
            e.failed_scopes = query_scopes[index:]
            e.empty_scopes = empty_scopes
            raise
        except Exception as e:
            failed_scopes.append(query_scope)
            print(f"\nGagal mengambil report {query_scope['fullCode']}: {e}")

    return raw_results, rows, failed_scopes, empty_scopes


def save_report_progress(job, selected_scope, raw_results, rows, failed_scopes):
    save_json(job["raw_output_file"], raw_results)
    pd.DataFrame(rows).to_excel(job["excel_output_file"], index=False)
    save_json(
        job["failed_scopes_output_file"],
        {
            "selected_scope": selected_scope,
            "failed_scopes": failed_scopes,
        },
    )


def execute_report_job(
    *,
    session,
    headers,
    payload_template,
    job,
    report_api_url,
    max_scope_level,
    expand_target_level,
    empty_is_failure,
    response_flattener,
    max_retry_attempts,
    retry_backoff_seconds,
    request_timeout,
    page=None,
):
    selected_scope = job["selected_scope"]
    query_scopes = job["query_scopes"]

    print(
        f"Mengambil report assignment untuk level{selected_scope['level']} "
        f"{selected_scope['fullCode']} {selected_scope.get('name') or ''}\n"
        f"Jumlah level-{expand_target_level} yang akan diambil: {len(query_scopes)}\n"
    )

    if not query_scopes:
        print(f"Tidak ada wilayah level-{expand_target_level} di bawah scope yang dipilih.")
        save_json(
            job["failed_scopes_output_file"],
            {
                "selected_scope": selected_scope,
                "failed_scopes": [],
            },
        )
        return {
            "selected_scope": selected_scope,
            "failed_scopes": [],
            "empty_scopes": [],
            "raw_results": [],
            "rows": [],
        }

    try:
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
            page=page,
        )
    except SessionExpiredError as e:
        save_report_progress(
            job,
            selected_scope,
            getattr(e, "raw_results", []),
            getattr(e, "rows", []),
            getattr(e, "failed_scopes", query_scopes),
        )
        print(f"Progress sementara disimpan ke {job['failed_scopes_output_file']}")
        raise

    if failed_scopes:
        print(
            f"\nMenjalankan ulang {len(failed_scopes)} failed scope "
            "dalam sesi yang sama..."
        )
        try:
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
                page=page,
            )
        except SessionExpiredError as e:
            raw_results.extend(getattr(e, "raw_results", []))
            rows.extend(getattr(e, "rows", []))
            failed_scopes = getattr(e, "failed_scopes", failed_scopes)
            save_report_progress(job, selected_scope, raw_results, rows, failed_scopes)
            print(f"Progress sementara disimpan ke {job['failed_scopes_output_file']}")
            raise
        raw_results.extend(retry_raw_results)
        rows.extend(retry_rows)
        empty_scopes.extend(retry_empty_scopes)

    save_report_progress(job, selected_scope, raw_results, rows, failed_scopes)

    print(f"Raw report saved to {job['raw_output_file']}")
    print(f"Flattened report saved to {job['excel_output_file']}")
    print(f"Total rows: {len(rows)}")
    if empty_scopes:
        print(f"Empty level-{expand_target_level} scopes: {len(empty_scopes)}")
    if failed_scopes:
        print(f"Failed level-{expand_target_level} scopes: {len(failed_scopes)}")
        print(", ".join(scope["fullCode"] for scope in failed_scopes))
        print(f"Failed scopes saved to {job['failed_scopes_output_file']}")

    return {
        "selected_scope": selected_scope,
        "failed_scopes": failed_scopes,
        "empty_scopes": empty_scopes,
        "raw_results": raw_results,
        "rows": rows,
    }


def run_report_job(
    *,
    report_api_url,
    payload_file,
    failed_scopes_file,
    output_prefix,
    regions_file_default=REGIONS_FILE,
    regions_file_pattern="regions_UMKM*.json",
    enable_batch=False,
    failed_batches_file=None,
    max_scope_level=5,
    expand_target_level=5,
    empty_is_failure=False,
    response_flattener=flatten_label_values_response,
    max_retry_attempts=5,
    retry_backoff_seconds=(1, 2, 4, 4),
    request_timeout=60,
):
    run_mode = prompt_run_mode(
        failed_scopes_file,
        enable_batch=enable_batch,
        failed_batches_file=failed_batches_file,
    )

    batch_modes = {"batch-all", "batch-selected", "batch-failed"}
    batch_jobs = []

    if run_mode == "failed":
        selected_scope, query_scopes = load_failed_run_context(failed_scopes_file)
        batch_jobs = [
            build_single_report_job(
                output_prefix=output_prefix,
                failed_scopes_file=failed_scopes_file,
                selected_scope=selected_scope,
                query_scopes=query_scopes,
                failed_only=True,
            )
        ]
    elif run_mode == "single":
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
        batch_jobs = [
            build_single_report_job(
                output_prefix=output_prefix,
                failed_scopes_file=failed_scopes_file,
                selected_scope=selected_scope,
                query_scopes=query_scopes,
            )
        ]
    elif run_mode == "batch-all":
        cache_files = list_region_cache_files(regions_file_pattern)
        batch_jobs = build_batch_report_jobs(
            cache_files=cache_files,
            output_prefix=output_prefix,
            failed_scopes_file=failed_scopes_file,
            expand_target_level=expand_target_level,
        )
    elif run_mode == "batch-selected":
        cache_files = prompt_batch_regions_files(regions_file_pattern)
        batch_jobs = build_batch_report_jobs(
            cache_files=cache_files,
            output_prefix=output_prefix,
            failed_scopes_file=failed_scopes_file,
            expand_target_level=expand_target_level,
        )
    elif run_mode == "batch-failed":
        if not failed_batches_file:
            raise ValueError("failed_batches_file wajib diisi untuk mode batch-failed.")
        cache_files = load_failed_batch_context(failed_batches_file)
        batch_jobs = build_batch_report_jobs(
            cache_files=cache_files,
            output_prefix=output_prefix,
            failed_scopes_file=failed_scopes_file,
            expand_target_level=expand_target_level,
        )
    else:
        raise ValueError(f"Mode fetch tidak dikenali: {run_mode}")

    if not batch_jobs:
        print("Tidak ada job report yang akan dijalankan.")
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
        apply_browser_cookies_to_session(session, page)
        payload_template = load_json(payload_file)
        failed_batch_cache_files = []

        for job_index, job in enumerate(batch_jobs, start=1):
            selected_scope = job["selected_scope"]
            regions_file = job.get("regions_file")
            if len(batch_jobs) > 1:
                label = f"[{job_index}/{len(batch_jobs)}] level2 {selected_scope['fullCode']}"
                if regions_file:
                    label = f"{label} dari {regions_file}"
                print(f"\n{label}")

            try:
                result = execute_report_job(
                    session=session,
                    headers=headers,
                    payload_template=payload_template,
                    job=job,
                    report_api_url=report_api_url,
                    max_scope_level=max_scope_level,
                    expand_target_level=expand_target_level,
                    empty_is_failure=empty_is_failure,
                    response_flattener=response_flattener,
                    max_retry_attempts=max_retry_attempts,
                    retry_backoff_seconds=retry_backoff_seconds,
                    request_timeout=request_timeout,
                    page=page,
                )
                if regions_file and result["failed_scopes"]:
                    failed_batch_cache_files.append(regions_file)
            except SessionExpiredError as e:
                print(f"Session expired: {e}")
                print("Login ulang lalu jalankan mode failed/batch-failed untuk melanjutkan.")
                if regions_file:
                    failed_batch_cache_files.append(regions_file)
                break
            except Exception as e:
                print(
                    f"Error saat memproses level2 "
                    f"{selected_scope.get('fullCode', '-')}: {e}"
                )
                if regions_file:
                    failed_batch_cache_files.append(regions_file)

        if run_mode in batch_modes and failed_batches_file:
            deduped_failed_batch_cache_files = []
            for cache_file in failed_batch_cache_files:
                if cache_file not in deduped_failed_batch_cache_files:
                    deduped_failed_batch_cache_files.append(cache_file)

            save_json(
                failed_batches_file,
                {
                    "failed_cache_files": deduped_failed_batch_cache_files,
                },
            )
            if deduped_failed_batch_cache_files:
                print(
                    f"Failed level-2 batch saved to {failed_batches_file}: "
                    f"{len(deduped_failed_batch_cache_files)} file"
                )
            else:
                print("Semua level-2 batch selesai tanpa sisa gagal.")
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
