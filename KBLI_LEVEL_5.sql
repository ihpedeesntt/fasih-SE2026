SELECT * FROM (
SELECT kbli_akhir,kategori, level_5_full_code,COUNT(*) as jumlah,
SUM(total_pengeluaran) as total_pengeluaran, 
SUM(total_pendapatan) as total_pendapatan
FROM tgr_fd68e454.T_USAHA 
WHERE level_1_full_code = '53' AND kbli_akhir IS NOT NULL
GROUP BY kbli_akhir, level_5_full_code ,kategori,kbli_value,kbli_label
order by level_5_full_code
OFFSET 1000*0 ROWS FETCH NEXT 1000 ROWS ONLY
) A ORDER BY level_5_full_code, jumlah DESC