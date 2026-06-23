from build_regions_common import run_build_regions_job


UB_GROUP_ID = "6b0b053f-aa43-4855-ac8f-26857b735c93"
UB_LEVEL_1_ID = "18661d4d-ffa9-4fd7-83d9-e17a9a8c8d17"
UB_LEVEL_1_CODE = "53"


def main():
    run_build_regions_job(
        dataset_name="UB",
        group_id=UB_GROUP_ID,
        level1_id=UB_LEVEL_1_ID,
        level1_code=UB_LEVEL_1_CODE,
        default_output_prefix="regions_UB",
        regions_file_pattern="regions_UB*.json",
    )


if __name__ == "__main__":
    main()
