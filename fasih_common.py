from copy import deepcopy
import json
import random
from pathlib import Path


GROUP_ID = "a45adac1-e711-4c15-b3f9-1f30fc151565"
LEVEL_1_CODE = "53"
LEVEL_2_CODE = "5371"
LEVEL_1_ID = "af72fb31-23ff-4346-8a0c-332e6f9c5d0d"
LEVEL_2_ID = "2c28f605-5d75-4b91-b4fd-52092a7f8e45"
REGIONS_FILE = "regions_UMKM.json"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": "https://fasih-sm.bps.go.id/",
}


def get_random_delay(min_sec=0.2, max_sec=0.7):
    return random.uniform(min_sec, max_sec)


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def prompt_regions_file(default=REGIONS_FILE, pattern="regions_UMKM*.json"):
    matches = sorted(Path(".").glob(pattern))
    if matches:
        print("File cache wilayah yang tersedia:")
        for match in matches[:10]:
            print(f"- {match.name}")
    else:
        print("Belum ada file cache wilayah yang cocok.")

    chosen = input(f"File cache wilayah [{default}]: ").strip()
    return chosen or default


def nested_get(data, path, default=None):
    current = data
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def build_authenticated_headers(page):
    cookies = page.context.cookies()
    cookie_string = "; ".join(f"{cookie['name']}={cookie['value']}" for cookie in cookies)
    xsrf_token = next(
        (cookie["value"] for cookie in cookies if cookie["name"] == "XSRF-TOKEN"),
        None,
    )

    headers = DEFAULT_HEADERS.copy()
    headers["Cookie"] = cookie_string
    if xsrf_token:
        headers["X-XSRF-TOKEN"] = xsrf_token
    return headers


def response_json(response, description):
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as e:
        content_type = response.headers.get("Content-Type", "")
        preview = response.text[:500].replace("\n", " ").replace("\r", " ")
        raise RuntimeError(
            f"{description} returned invalid JSON: {e}; "
            f"status={response.status_code}; content-type={content_type}; "
            f"preview={preview}"
        ) from e


def sample_region_ids(regions, level, limit=5):
    id_key = f"level{level}_id"
    code_key = f"level{level}_fullCode"
    name_key = f"level{level}_name"
    samples = []
    seen = set()

    for region in regions:
        region_id = region.get(id_key)
        if not region_id or region_id in seen:
            continue
        seen.add(region_id)
        samples.append(
            f"{region_id} | {region.get(code_key, '')} | {region.get(name_key, '')}"
        )
        if len(samples) >= limit:
            break

    return samples


def find_region_scope(regions, level, region_id):
    if level not in {2, 3, 4, 5, 6}:
        raise ValueError("Level harus 2, 3, 4, 5, atau 6.")

    id_key = f"level{level}_id"
    code_key = f"level{level}_fullCode"
    selected_row = next(
        (
            region
            for region in regions
            if region.get(id_key) == region_id or region.get(code_key) == region_id
        ),
        None,
    )

    if selected_row is None:
        samples = "\n".join(sample_region_ids(regions, level))
        raise ValueError(
            f"Region ID tidak ditemukan untuk level {level}: {region_id}\n"
            f"Contoh ID level {level}:\n{samples}"
        )

    scope = {
        "level": level,
        "id": selected_row[f"level{level}_id"],
        "fullCode": selected_row[f"level{level}_fullCode"],
        "name": selected_row.get(f"level{level}_name"),
        "row": selected_row,
    }

    for current_level in range(1, 7):
        scope[f"region{current_level}Id"] = selected_row.get(f"level{current_level}_id")
        scope[f"level{current_level}_fullCode"] = selected_row.get(
            f"level{current_level}_fullCode"
        )
        scope[f"level{current_level}_name"] = selected_row.get(f"level{current_level}_name")

    return scope


def scope_from_row(row, level):
    scope = {
        "level": level,
        "id": row[f"level{level}_id"],
        "fullCode": row[f"level{level}_fullCode"],
        "name": row.get(f"level{level}_name"),
        "row": row,
    }

    for current_level in range(1, 7):
        scope[f"region{current_level}Id"] = row.get(f"level{current_level}_id")
        scope[f"level{current_level}_fullCode"] = row.get(f"level{current_level}_fullCode")
        scope[f"level{current_level}_name"] = row.get(f"level{current_level}_name")

    return scope


def expand_scope_to_level(regions, selected_scope, target_level):
    selected_level = selected_scope["level"]
    selected_id = selected_scope["id"]
    selected_key = f"level{selected_level}_id"
    target_id_key = f"level{target_level}_id"

    expanded = []
    seen_target_ids = set()

    for row in regions:
        if row.get(selected_key) != selected_id:
            continue

        target_id = row.get(target_id_key)
        if not target_id or target_id in seen_target_ids:
            continue

        seen_target_ids.add(target_id)
        scope = scope_from_row(row, target_level)
        scope["selected_level"] = selected_level
        scope["selected_fullCode"] = selected_scope["fullCode"]
        scope["selected_name"] = selected_scope.get("name")
        expanded.append(scope)

    return expanded


def expand_scope_to_level6(regions, selected_scope):
    return expand_scope_to_level(regions, selected_scope, 6)


def expand_scope_to_level5(regions, selected_scope):
    return expand_scope_to_level(regions, selected_scope, 5)


def prompt_region_scope(regions, regions_file=REGIONS_FILE, max_level=6):
    level_options = "/".join(str(level) for level in range(2, max_level + 1))
    level_text = input(f"Pilih level wilayah yang ingin diambil ({level_options}): ").strip()
    level = int(level_text)
    if level < 2 or level > max_level:
        raise ValueError(f"Level harus antara 2 dan {max_level}.")

    print(f"Masukkan level{level}_id atau level{level}_fullCode dari {regions_file}.")
    for sample in sample_region_ids(regions, level, limit=3):
        print(f"Contoh: {sample}")

    region_id = input(f"level{level}_id/fullCode: ").strip()
    return find_region_scope(regions, level, region_id)


def apply_scope_to_datatable_payload(payload_template, scope, start, length):
    payload = deepcopy(payload_template)
    payload["start"] = start
    payload["length"] = length

    extra = payload.setdefault("assignmentExtraParam", {})
    for level in range(1, 7):
        key = f"region{level}Id"
        extra[key] = scope[key] if level <= scope["level"] else None
    return payload


def apply_scope_to_report_payload(payload_template, scope, max_level=5):
    payload = deepcopy(payload_template)
    for level in range(1, max_level + 1):
        key = f"region{level}Id"
        payload[key] = scope[key] if level <= scope["level"] else None
    for level in range(max_level + 1, 7):
        payload.pop(f"region{level}Id", None)
    payload["regionId"] = None
    return payload


def scoped_output_name(prefix, extension, scope):
    return f"{prefix}_level{scope['level']}_{scope['fullCode']}.{extension}"
