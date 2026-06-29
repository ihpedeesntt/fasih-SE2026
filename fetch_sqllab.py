#!/usr/bin/env python3
import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any


BASE_URL = "https://fasih-dashboard.bps.go.id"
SQLLAB_URL = BASE_URL + "/superset/sqllab/"
RESULTS_URL_FRAGMENT = "/api/v1/sqllab/results/"
OFFSET_RE = re.compile(
    r"OFFSET\s+(?:\d+\s*\*\s*\d+|\d+)\s+ROWS\s+FETCH\s+NEXT\s+\d+\s+ROWS\s+ONLY",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sql", default="T_USAHA_RAW.sql")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--page-size", type=int, default=1000)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--delay", type=float, default=3)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--save-json", action="store_true")
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--show-browser", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--chrome-profile")
    parser.add_argument("--no-sandbox", action="store_true")
    parser.add_argument("--self-check", action="store_true")
    return parser.parse_args()


def load_env(path: str) -> dict[str, str]:
    env = dict(os.environ)
    env_path = Path(path)
    if not env_path.exists():
        return env
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def read_sql(path: str) -> str:
    return Path(path).read_text().strip()


def set_offset_sql(sql: str, page_index: int, page_size: int) -> str:
    matches = list(OFFSET_RE.finditer(sql))
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one OFFSET/FETCH clause, found {len(matches)}")
    clause = f"OFFSET {page_size}*{page_index} ROWS FETCH NEXT {page_size} ROWS ONLY"
    return OFFSET_RE.sub(clause, sql, count=1)


def output_paths(output_dir: str, sql_path: str) -> tuple[Path, Path, Path]:
    run_dir = Path(output_dir) / Path(sql_path).stem
    pages_dir = run_dir / "pages"
    checkpoint = run_dir / "checkpoint.json"
    pages_dir.mkdir(parents=True, exist_ok=True)
    return run_dir, pages_dir, checkpoint


def load_checkpoint(path: Path, resume: bool) -> dict[str, Any]:
    if resume and path.exists():
        return json.loads(path.read_text())
    return {"next_page_index": 0, "total_rows": 0}


def save_checkpoint(path: Path, checkpoint: dict[str, Any]) -> None:
    path.write_text(json.dumps(checkpoint, indent=2))


def rows_from_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    if response.get("errors"):
        first = response["errors"][0] if response["errors"] else {}
        message = first.get("message", "SQL Lab API error") if isinstance(first, dict) else str(first)
        raise RuntimeError(message)
    rows = response.get("data")
    if not isinstance(rows, list):
        raise RuntimeError("Results JSON does not contain a data array")
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                columns.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: normalize_cell(row.get(key)) for key in columns})


def normalize_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def set_editor_sql(page: Any, sql: str) -> None:
    ok = page.evaluate(
        """(sql) => {
            const aceEl = document.querySelector(".ace_editor");
            if (aceEl && aceEl.env && aceEl.env.editor) {
                aceEl.env.editor.setValue(sql, -1);
                aceEl.env.editor.focus();
                return true;
            }

            const cmEl = document.querySelector(".CodeMirror");
            if (cmEl && cmEl.CodeMirror) {
                cmEl.CodeMirror.setValue(sql);
                cmEl.CodeMirror.focus();
                return true;
            }

            const textarea = Array.from(document.querySelectorAll("textarea"))
                .find((item) => item.offsetWidth > 0 && item.offsetHeight > 0);
            if (textarea) {
                textarea.focus();
                textarea.value = sql;
                textarea.dispatchEvent(new Event("input", { bubbles: true }));
                textarea.dispatchEvent(new Event("change", { bubbles: true }));
                return true;
            }

            return false;
        }""",
        sql,
    )
    if ok:
        return

    editor = page.locator(".ace_text-input, .CodeMirror textarea, textarea").first
    editor.click(timeout=20_000, force=True)
    page.keyboard.press("Control+A")
    page.keyboard.insert_text(sql)


def click_run_and_wait_results(page: Any, timeout_ms: int) -> dict[str, Any]:
    run_button = page.locator("button.ant-btn.superset-button.cta:has(span:has-text('Run'))").first
    run_button.wait_for(state="visible", timeout=45_000)
    run_button.scroll_into_view_if_needed(timeout=10_000)

    with page.expect_response(
        lambda response: response.request.method.upper() == "GET" and RESULTS_URL_FRAGMENT in response.url,
        timeout=timeout_ms,
    ) as result_info:
        run_button.click(timeout=20_000, force=True)

    response = result_info.value
    try:
        return response.json()
    except Exception as exc:
        raise RuntimeError(f"Results returned non-JSON HTTP {response.status}") from exc


def fetch_page(page: Any, sql: str, page_index: int, page_size: int, timeout: int) -> dict[str, Any]:
    set_editor_sql(page, set_offset_sql(sql, page_index, page_size))
    time.sleep(0.5)
    return click_run_and_wait_results(page, timeout * 1000)


def open_sqllab(page: Any, timeout_error: Any) -> None:
    page.goto(SQLLAB_URL, wait_until="domcontentloaded", timeout=120_000)
    try:
        page.wait_for_load_state("networkidle", timeout=120_000)
    except timeout_error:
        pass


def run(args: argparse.Namespace) -> int:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is not installed. Run `uv sync` first.") from exc

    env = load_env(args.env)
    profile = args.chrome_profile or env.get("SQLLAB_CHROME_PROFILE") or ".chrome-sqllab-profile"
    sql = read_sql(args.sql)
    run_dir, pages_dir, checkpoint_path = output_paths(args.output_dir, args.sql)
    checkpoint = load_checkpoint(checkpoint_path, args.resume)
    print(f"sql={args.sql}")
    print(f"output={run_dir}")
    print(f"pages={pages_dir}")
    print(f"checkpoint={checkpoint_path}")
    print(f"start_page={checkpoint['next_page_index']}")

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=profile,
            channel="chrome",
            headless=not args.show_browser,
            args=["--no-sandbox"] if args.no_sandbox else [],
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            open_sqllab(page, PlaywrightTimeoutError)

            while True:
                page_index = int(checkpoint["next_page_index"])
                if args.max_pages is not None and page_index >= args.max_pages:
                    print(f"Reached max-pages={args.max_pages}.")
                    return 0

                response = retry_page(
                    args,
                    lambda: fetch_page(page, sql, page_index, args.page_size, args.timeout),
                    page_index,
                    lambda: open_sqllab(page, PlaywrightTimeoutError),
                )
                rows = rows_from_response(response)
                page_base = pages_dir / f"page-{page_index:04d}"
                write_csv(page_base.with_suffix(".csv"), rows)
                if args.save_json:
                    page_base.with_suffix(".json").write_text(json.dumps(response, ensure_ascii=False, indent=2))

                checkpoint = {
                    "next_page_index": page_index + 1,
                    "last_completed_page_index": page_index,
                    "last_completed_offset": page_index * args.page_size,
                    "last_page_rows": len(rows),
                    "total_rows": int(checkpoint["total_rows"]) + len(rows),
                }
                save_checkpoint(checkpoint_path, checkpoint)
                print(f"page={page_index} offset={page_index * args.page_size} rows={len(rows)} total={checkpoint['total_rows']}")
                time.sleep(args.delay)

                if len(rows) < args.page_size:
                    print("Last page reached.")
                    return 0
        finally:
            context.close()


def retry_page(args: argparse.Namespace, task: Any, page_index: int, on_retry: Any = None) -> dict[str, Any]:
    for attempt in range(1, args.max_retries + 1):
        try:
            return task()
        except Exception as exc:
            error_text = str(exc).lower()
            non_retry = "create failed" in error_text or "syntax" in error_text
            if non_retry or attempt >= args.max_retries:
                print(f"Page {page_index} failed: {exc}", file=sys.stderr)
                raise
            sleep_seconds = min(30, attempt * 3)
            print(f"Page {page_index} attempt {attempt} failed: {exc}. Retrying in {sleep_seconds}s...", file=sys.stderr)
            if on_retry:
                on_retry()
            time.sleep(sleep_seconds)
    raise RuntimeError("Retry loop exhausted")


def self_check() -> int:
    sql = "select * from t OFFSET 1000*0 ROWS FETCH NEXT 1000 ROWS ONLY"
    assert set_offset_sql(sql, 0, 1000).endswith("OFFSET 1000*0 ROWS FETCH NEXT 1000 ROWS ONLY")
    assert set_offset_sql(sql, 9, 1000).endswith("OFFSET 1000*9 ROWS FETCH NEXT 1000 ROWS ONLY")
    try:
        set_offset_sql(sql + " " + sql, 0, 1000)
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate offsets should fail")
    try:
        rows_from_response({"errors": [{"message": "Create failed"}]})
    except RuntimeError as exc:
        assert "Create failed" in str(exc)
    else:
        raise AssertionError("api errors should fail")
    print("self-check passed")
    return 0


if __name__ == "__main__":
    parsed_args = parse_args()
    try:
        raise SystemExit(self_check() if parsed_args.self_check else run(parsed_args))
    except KeyboardInterrupt:
        raise SystemExit(130)
