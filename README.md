# FASIH UMKM / UB Tools

Kumpulan script untuk:
- membangun cache wilayah per kabupaten/kota
- mengambil assignment UMKM
- mengambil report progress assignment

## Instalasi

Requirement:
- Python 3.11+
- `uv`
- Pastikan di PC lokal sudah terinstall uv. Tata cara instalasi UV dapat diakses di tautan berikut:
https://docs.astral.sh/uv/getting-started/installation/#installation-methods



Install dependency:

```powershell
uv sync
```

Install browser Playwright:

```powershell
uv run playwright install
```

## File Utama

- `build_regions_UMKM.py`
  - ambil struktur wilayah level 3 sampai level 6
  - hasil disimpan ke file seperti `regions_UMKM_5371.json`
- `report_assignment_UMKM.py`
  - ambil report progress assignment
  - bisa full run atau hanya rerun scope yang gagal

## ALUR

### Build cache wilayah

Jalankan:

```powershell
uv run python build_regions_UMKM.py
```

Input yang diminta:
- `level2_fullCode` = Masukkan kode kabupaten/kota, contoh 5371
- `level2_id` = Masukkan id kabupaten/kota. Dapat dilihat pada regions_level2_id.json. Contoh id untuk 5371 adalah 2c28f605-5d75-4b91-b4fd-52092a7f8e45
- nama file output cache

Contoh output:

```text
regions_UMKM_5371.json
regions_UMKM_5305.json
```

Catatan:
- untuk kabupaten/kota baru, file cache wilayah harus dibuat dulu
- script ini login manual lewat browser

hanya dilakukan sekali saja untuk mengambil data wilayah kabupaten.


### Ambil report assignment

Jalankan:

```powershell
uv run python report_assignment_UMKM.py
```

Mode:
- `all`
  - run normal dari scope yang dipilih
- `failed`
  - hanya rerun scope yang tersimpan di `failed_report_scopes.json`

Alur mode `all`:
1. pilih file cache wilayah. Contoh : regions_UMKM_5371.json
2. pilih level `2/3/4/5` (level 2 : Kabkot, Level 3 : Kecamatan, Level 4 : Kelurahan/Desa, Level 5 : SLS)
3. masukkan `levelN_id` atau `levelN_fullCode`
4. script akan expand ke level 5 lalu ambil report

Output:
- raw JSON
- file Excel hasil flatten
- `failed_report_scopes.json` jika ada scope yang gagal

Contoh output:

```text
report_assignment_UMKM_level2_5371.json
report_assignment_UMKM_level2_5371.xlsx
failed_report_scopes.json
```

## Retry dan Timeout

`report_assignment_UMKM.py` saat ini:
- timeout request `60` detik
- retry sampai `5` kali untuk timeout / connection error
- simpan scope gagal ke `failed_report_scopes.json`

## Login

Semua script yang akses API FASIH memakai login manual melalui `login.py`.

Alur singkat:
- browser dibuka
- isi login dan OTP manual, masing-masing diberikan waktu 3 menit
- jika ada OTP, isi manual
- setelah login berhasil, script lanjut memakai cookie sesi
