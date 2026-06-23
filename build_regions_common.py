import time
from urllib.parse import urlencode

import requests
from tqdm import tqdm

from fasih_common import (
    apply_browser_cookies_to_session,
    build_authenticated_headers,
    get_random_delay,
    prompt_regions_file,
    response_json,
    save_json,
)
from login import login_with_sso


REGION_API_URL = "https://fasih-sm.bps.go.id/app/api/region/api/v1/region"
REGION_NAVIGATION_TIMEOUT_MS = 600_000
REGION_RETRY_BACKOFF_SECONDS = (1, 2, 4, 4)


def fetch_regions(
    session,
    headers,
    group_id,
    level,
    parent_full_code,
    request_timeout=30,
    max_attempts=5,
):
    parent_param = f"level{level - 1}FullCode"
    params = {"groupId": group_id, parent_param: parent_full_code}
    url = f"{REGION_API_URL}/level{level}?{urlencode(params)}"

    for attempt in range(1, max_attempts + 1):
        try:
            time.sleep(get_random_delay())
            response = session.get(url, headers=headers, timeout=request_timeout)
            data = response_json(response, f"Region level {level}")

            if not data.get("success"):
                raise RuntimeError(f"Region level {level} request failed: {data.get('message')}")
            return data.get("data") or []
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt >= max_attempts:
                raise RuntimeError(
                    f"Gagal mengambil region level {level} untuk {parent_full_code} "
                    f"setelah {max_attempts} percobaan: {e}"
                ) from e

            backoff = REGION_RETRY_BACKOFF_SECONDS[
                min(attempt - 1, len(REGION_RETRY_BACKOFF_SECONDS) - 1)
            ]
            print(
                f"Retry region level {level} untuk {parent_full_code} "
                f"(attempt {attempt + 1}/{max_attempts}) setelah error: {e}"
            )
            time.sleep(backoff)


def add_level6_path(
    level6_paths,
    *,
    level1_id,
    level1_code,
    level2_id,
    level2_code,
    level3,
    level4,
    level5,
    level6,
):
    level6_paths.append(
        {
            "level1_id": level1_id,
            "level1_fullCode": level1_code,
            "level2_id": level2_id,
            "level2_fullCode": level2_code,
            "level3_id": level3["id"],
            "level3_fullCode": level3["fullCode"],
            "level3_name": level3["name"],
            "level4_id": level4["id"],
            "level4_fullCode": level4["fullCode"],
            "level4_name": level4["name"],
            "level5_id": level5["id"],
            "level5_fullCode": level5["fullCode"],
            "level5_name": level5["name"],
            "level6_id": level6["id"],
            "level6_fullCode": level6["fullCode"],
            "level6_name": level6["name"],
        }
    )


def queue_failed_task(failed_tasks, *, level, parent_full_code, error, **context):
    failed_tasks.append(
        {
            "level": level,
            "parent_full_code": parent_full_code,
            "error": str(error),
            **context,
        }
    )
    print(
        f"Skip region level {level} untuk {parent_full_code} setelah 5 percobaan. "
        "Akan dicoba lagi di akhir."
    )


def process_level6_children(
    session,
    headers,
    *,
    group_id,
    level1_id,
    level1_code,
    level2_code,
    level2_id,
    level3,
    level4,
    level5,
    level6_paths,
    failed_tasks,
    request_timeout,
    is_retry_pass,
):
    try:
        level6_regions = fetch_regions(
            session,
            headers,
            group_id,
            6,
            level5["fullCode"],
            request_timeout=request_timeout,
        )
    except Exception as e:
        queue_failed_task(
            failed_tasks,
            level=6,
            parent_full_code=level5["fullCode"],
            error=e,
            level3=level3,
            level4=level4,
            level5=level5,
            retry_stage="final" if is_retry_pass else "initial",
        )
        return

    for level6 in level6_regions:
        add_level6_path(
            level6_paths,
            level1_id=level1_id,
            level1_code=level1_code,
            level2_id=level2_id,
            level2_code=level2_code,
            level3=level3,
            level4=level4,
            level5=level5,
            level6=level6,
        )


def process_level5_children(
    session,
    headers,
    *,
    group_id,
    level1_id,
    level1_code,
    level2_code,
    level2_id,
    level3,
    level4,
    level6_paths,
    failed_tasks,
    request_timeout,
    is_retry_pass,
):
    try:
        level5_regions = fetch_regions(
            session,
            headers,
            group_id,
            5,
            level4["fullCode"],
            request_timeout=request_timeout,
        )
    except Exception as e:
        queue_failed_task(
            failed_tasks,
            level=5,
            parent_full_code=level4["fullCode"],
            error=e,
            level3=level3,
            level4=level4,
            retry_stage="final" if is_retry_pass else "initial",
        )
        return

    for level5 in level5_regions:
        process_level6_children(
            session,
            headers,
            group_id=group_id,
            level1_id=level1_id,
            level1_code=level1_code,
            level2_code=level2_code,
            level2_id=level2_id,
            level3=level3,
            level4=level4,
            level5=level5,
            level6_paths=level6_paths,
            failed_tasks=failed_tasks,
            request_timeout=request_timeout,
            is_retry_pass=is_retry_pass,
        )


def process_level4_children(
    session,
    headers,
    *,
    group_id,
    level1_id,
    level1_code,
    level2_code,
    level2_id,
    level3,
    level6_paths,
    failed_tasks,
    request_timeout,
    is_retry_pass,
):
    try:
        level4_regions = fetch_regions(
            session,
            headers,
            group_id,
            4,
            level3["fullCode"],
            request_timeout=request_timeout,
        )
    except Exception as e:
        queue_failed_task(
            failed_tasks,
            level=4,
            parent_full_code=level3["fullCode"],
            error=e,
            level3=level3,
            retry_stage="final" if is_retry_pass else "initial",
        )
        return

    for level4 in level4_regions:
        process_level5_children(
            session,
            headers,
            group_id=group_id,
            level1_id=level1_id,
            level1_code=level1_code,
            level2_code=level2_code,
            level2_id=level2_id,
            level3=level3,
            level4=level4,
            level6_paths=level6_paths,
            failed_tasks=failed_tasks,
            request_timeout=request_timeout,
            is_retry_pass=is_retry_pass,
        )


def process_level3_children(
    session,
    headers,
    *,
    group_id,
    level1_id,
    level1_code,
    level2_code,
    level2_id,
    level6_paths,
    failed_tasks,
    request_timeout,
    is_retry_pass,
):
    try:
        level3_regions = fetch_regions(
            session,
            headers,
            group_id,
            3,
            level2_code,
            request_timeout=request_timeout,
        )
    except Exception as e:
        queue_failed_task(
            failed_tasks,
            level=3,
            parent_full_code=level2_code,
            error=e,
            retry_stage="final" if is_retry_pass else "initial",
        )
        return

    iterator = level3_regions
    if not is_retry_pass:
        iterator = tqdm(level3_regions, desc="Discovering level 3-6", unit="level3")

    for level3 in iterator:
        process_level4_children(
            session,
            headers,
            group_id=group_id,
            level1_id=level1_id,
            level1_code=level1_code,
            level2_code=level2_code,
            level2_id=level2_id,
            level3=level3,
            level6_paths=level6_paths,
            failed_tasks=failed_tasks,
            request_timeout=request_timeout,
            is_retry_pass=is_retry_pass,
        )


def retry_failed_task(
    session,
    headers,
    *,
    task,
    group_id,
    level1_id,
    level1_code,
    level2_code,
    level2_id,
    level6_paths,
    remaining_failed_tasks,
    request_timeout,
):
    level = task["level"]

    if level == 3:
        process_level3_children(
            session,
            headers,
            group_id=group_id,
            level1_id=level1_id,
            level1_code=level1_code,
            level2_code=level2_code,
            level2_id=level2_id,
            level6_paths=level6_paths,
            failed_tasks=remaining_failed_tasks,
            request_timeout=request_timeout,
            is_retry_pass=True,
        )
    elif level == 4:
        process_level4_children(
            session,
            headers,
            group_id=group_id,
            level1_id=level1_id,
            level1_code=level1_code,
            level2_code=level2_code,
            level2_id=level2_id,
            level3=task["level3"],
            level6_paths=level6_paths,
            failed_tasks=remaining_failed_tasks,
            request_timeout=request_timeout,
            is_retry_pass=True,
        )
    elif level == 5:
        process_level5_children(
            session,
            headers,
            group_id=group_id,
            level1_id=level1_id,
            level1_code=level1_code,
            level2_code=level2_code,
            level2_id=level2_id,
            level3=task["level3"],
            level4=task["level4"],
            level6_paths=level6_paths,
            failed_tasks=remaining_failed_tasks,
            request_timeout=request_timeout,
            is_retry_pass=True,
        )
    elif level == 6:
        process_level6_children(
            session,
            headers,
            group_id=group_id,
            level1_id=level1_id,
            level1_code=level1_code,
            level2_code=level2_code,
            level2_id=level2_id,
            level3=task["level3"],
            level4=task["level4"],
            level5=task["level5"],
            level6_paths=level6_paths,
            failed_tasks=remaining_failed_tasks,
            request_timeout=request_timeout,
            is_retry_pass=True,
        )


def discover_level6_regions(
    session,
    headers,
    *,
    group_id,
    level1_id,
    level1_code,
    level2_code,
    level2_id,
    request_timeout=30,
):
    level6_paths = []
    failed_tasks = []

    process_level3_children(
        session,
        headers,
        group_id=group_id,
        level1_id=level1_id,
        level1_code=level1_code,
        level2_code=level2_code,
        level2_id=level2_id,
        level6_paths=level6_paths,
        failed_tasks=failed_tasks,
        request_timeout=request_timeout,
        is_retry_pass=False,
    )

    if failed_tasks:
        print(
            f"\nMencoba ulang {len(failed_tasks)} fetch wilayah yang gagal "
            "setelah pass utama selesai..."
        )
        remaining_failed_tasks = []
        for task in failed_tasks:
            retry_failed_task(
                session,
                headers,
                task=task,
                group_id=group_id,
                level1_id=level1_id,
                level1_code=level1_code,
                level2_code=level2_code,
                level2_id=level2_id,
                level6_paths=level6_paths,
                remaining_failed_tasks=remaining_failed_tasks,
                request_timeout=request_timeout,
            )

        if remaining_failed_tasks:
            print(
                f"\nMasih ada {len(remaining_failed_tasks)} fetch wilayah yang gagal "
                "setelah retry akhir."
            )
            for task in remaining_failed_tasks[:10]:
                print(
                    f"- level {task['level']} parent {task['parent_full_code']} "
                    f"({task['error']})"
                )
        else:
            print("Semua fetch wilayah yang sempat gagal berhasil diproses saat retry akhir.")

    return level6_paths


def run_build_regions_job(
    *,
    dataset_name,
    group_id,
    level1_id,
    level1_code,
    default_output_prefix,
    regions_file_pattern,
    landing_url="https://fasih-sm.bps.go.id/app/surveys",
    request_timeout=30,
):
    level2_code = input("Masukkan level2_fullCode kabupaten/kota [5371]: ").strip() or "5371"
    level2_id = input("Masukkan level2_id kabupaten/kota: ").strip()
    if not level2_id:
        print("level2_id wajib diisi.")
        return

    default_output = f"{default_output_prefix}_{level2_code}.json"
    output_file = prompt_regions_file(default=default_output, pattern=regions_file_pattern)

    print(f"Membuka browser untuk login manual {dataset_name}...\n")
    page, browser = login_with_sso()
    if not page:
        print("Login gagal. Tidak dapat mengambil wilayah.")
        return

    session = requests.Session()

    try:
        page.goto(landing_url, timeout=REGION_NAVIGATION_TIMEOUT_MS)
        page.wait_for_load_state("networkidle", timeout=REGION_NAVIGATION_TIMEOUT_MS)
        headers = build_authenticated_headers(page)
        apply_browser_cookies_to_session(session, page)

        print("Mengambil hierarki wilayah level 3 sampai level 6...")
        regions = discover_level6_regions(
            session,
            headers,
            group_id=group_id,
            level1_id=level1_id,
            level1_code=level1_code,
            level2_code=level2_code,
            level2_id=level2_id,
            request_timeout=request_timeout,
        )
        save_json(output_file, regions)
        print(f"{len(regions)} wilayah level 6 disimpan ke {output_file}")
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
