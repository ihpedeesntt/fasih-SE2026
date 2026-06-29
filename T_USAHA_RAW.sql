SELECT * FROM (
SELECT * 
FROM tgr_fd68e454.T_USAHA 
WHERE level_1_full_code = '53' AND assignment_status_id = '2'
order by level_2_code,level_3_code,level_4_code,level_5_code, assignment_id, code_identity
OFFSET 1000*0 ROWS FETCH NEXT 1000 ROWS ONLY ) a ORDER BY level_1_code, level_2_code, level_3_code, level_4_code, level_5_code, assignment_id, code_identity
