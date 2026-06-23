from build_regions_common import run_build_regions_job
from fasih_common import (
    GROUP_ID,
    LEVEL_1_CODE,
    LEVEL_1_ID,
)


def main():
    run_build_regions_job(
        dataset_name="UMKM",
        group_id=GROUP_ID,
        level1_id=LEVEL_1_ID,
        level1_code=LEVEL_1_CODE,
        default_output_prefix="regions_UMKM",
        regions_file_pattern="regions_UMKM*.json",
    )


if __name__ == "__main__":
    main()
