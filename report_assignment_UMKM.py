from report_common import run_report_job


REPORT_API_URL = (
    "https://fasih-sm.bps.go.id/app/api/analytic/api/v2/assignment/"
    "report-progress-assignment"
)
PAYLOAD_FILE = "payload_report_assignment.json"
FAILED_SCOPES_FILE = "failed_report_scopes.json"
FAILED_BATCHES_FILE = "failed_level2_batches_UMKM.json"
OUTPUT_PREFIX = "report_assignment_UMKM"


def main():
    run_report_job(
        report_api_url=REPORT_API_URL,
        payload_file=PAYLOAD_FILE,
        failed_scopes_file=FAILED_SCOPES_FILE,
        output_prefix=OUTPUT_PREFIX,
        regions_file_default="regions_UMKM.json",
        regions_file_pattern="regions_UMKM*.json",
        enable_batch=True,
        failed_batches_file=FAILED_BATCHES_FILE,
        max_scope_level=5,
        expand_target_level=5,
        empty_is_failure=False,
        max_retry_attempts=5,
        retry_backoff_seconds=(1, 2, 4, 4),
        request_timeout=60,
    )


if __name__ == "__main__":
    main()
