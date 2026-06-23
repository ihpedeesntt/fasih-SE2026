import time
from urllib.parse import urlencode

import requests
from tqdm import tqdm

from fasih_common import (
    build_authenticated_headers,
    get_random_delay,
    prompt_regions_file,
    response_json,
    save_json,
)
from login import login_with_sso


REGION_API_URL = "https://fasih-sm.bps.go.id/app/api/region/api/v1/region"
REGION_NAVIGATION_TIMEOUT_MS = 600_000


def fetch_regions(session, headers, group_id, level, parent_full_code, request_timeout=30):
    parent_param = f"level{level - 1}FullCode"
    params = {"groupId": group_id, parent_param: parent_full_code}
    url = f"{REGION_API_URL}/level{level}?{urlencode(params)}"

    time.sleep(get_random_delay())
    response = session.get(url, headers=headers, timeout=request_timeout)
    data = response_json(response, f"Region level {level}")

    if not data.get("success"):
        raise RuntimeError(f"Region level {level} request failed: {data.get('message')}")
    return data.get("data") or []


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
    level3_regions = fetch_regions(
        session,
        headers,
        group_id,
        3,
        level2_code,
        request_timeout=request_timeout,
    )

    for level3 in tqdm(level3_regions, desc="Discovering level 3-6", unit="level3"):
        level4_regions = fetch_regions(
            session,
            headers,
            group_id,
            4,
            level3["fullCode"],
            request_timeout=request_timeout,
        )

        for level4 in level4_regions:
            level5_regions = fetch_regions(
                session,
                headers,
                group_id,
                5,
                level4["fullCode"],
                request_timeout=request_timeout,
            )

            for level5 in level5_regions:
                level6_regions = fetch_regions(
                    session,
                    headers,
                    group_id,
                    6,
                    level5["fullCode"],
                    request_timeout=request_timeout,
                )

                for level6 in level6_regions:
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
