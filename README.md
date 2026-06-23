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
- `build_regions_UB.py`
  - ambil struktur wilayah level 3 sampai level 6 untuk UB
  - hasil disimpan ke file seperti `regions_UB_5307.json`
- `report_assignment_UMKM.py`
  - ambil report progress assignment
  - bisa single run, rerun failed scope, atau batch beberapa level-2
- `report_assignment_UB.py`
  - ambil report progress assignment untuk UB
  - flow sama dengan UMKM, tetapi memakai payload dan file failed khusus UB

## ALUR

### Build cache wilayah

Jalankan:

```powershell
uv run python build_regions_UMKM.py
```

Untuk UB:

```powershell
uv run python build_regions_UB.py
```

Input yang diminta:
- `level2_fullCode` = Masukkan kode kabupaten/kota, contoh 5371
- `level2_id` = Masukkan id kabupaten/kota. Dapat dilihat pada regions_level2_id.json. Contoh id untuk 5371 adalah 2c28f605-5d75-4b91-b4fd-52092a7f8e45
- nama file output cache

Contoh output:

```text
regions_UMKM_5371.json
regions_UMKM_5305.json
regions_UB_5307.json
```

Catatan:
- untuk kabupaten/kota baru, file cache wilayah harus dibuat dulu
- script ini login manual lewat browser
- `build_regions_UMKM.py` dan `build_regions_UB.py` memakai ID wilayah yang berbeda, jadi cache-nya tidak bisa saling dipakai

hanya dilakukan sekali saja untuk mengambil data wilayah kabupaten per dataset.


### Ambil report assignment

Jalankan:

```powershell
uv run python report_assignment_UMKM.py
```

Mode:
- `single`
  - run normal dari scope yang dipilih
- `failed`
  - hanya rerun scope yang tersimpan di `failed_report_scopes.json`
- `batch-all`
  - jalankan semua file `regions_UMKM_*.json`
- `batch-selected`
  - pilih beberapa file `regions_UMKM_*.json`

Jika ada isi di `failed_level2_batches_UMKM.json`, script akan menawarkan rerun hanya batch level-2 yang gagal.

Alur mode `single`:
1. pilih file cache wilayah. Contoh : regions_UMKM_5371.json
2. pilih level `2/3/4/5` (level 2 : Kabkot, Level 3 : Kecamatan, Level 4 : Kelurahan/Desa, Level 5 : SLS)
3. masukkan `levelN_id` atau `levelN_fullCode`
4. script akan expand ke level 5 lalu ambil report

Alur mode batch:
1. login sekali
2. script loop serial per file cache level-2
3. setiap level-2 menghasilkan file JSON/XLSX sendiri
4. jika ada level-2 yang masih gagal, nama file cache-nya disimpan ke `failed_level2_batches_UMKM.json`

Output:
- raw JSON
- file Excel hasil flatten
- `failed_report_scopes.json` untuk single/failed mode
- `failed_report_scopes_level2_<fullCode>.json` untuk batch mode
- `failed_level2_batches_UMKM.json` jika ada level-2 yang gagal saat batch

Contoh output:

```text
report_assignment_UMKM_level2_5371.json
report_assignment_UMKM_level2_5371.xlsx
failed_report_scopes.json
failed_report_scopes_level2_5371.json
failed_level2_batches_UMKM.json
```

### Ambil report assignment UB

Jalankan:

```powershell
uv run python report_assignment_UB.py
```

Alur:
1. pilih file cache wilayah UB, mis. `regions_UB_5307.json`
2. pilih level `2/3/4/5`
3. masukkan `levelN_id` atau `levelN_fullCode`
4. script expand ke level 5
5. level 5 yang response-nya kosong akan dilewati dan tidak dianggap gagal

Output contoh:

```text
report_assignment_UB_level2_5305.json
report_assignment_UB_level2_5305.xlsx
failed_report_scopes_UB.json
```

## Retry dan Timeout

`report_assignment_UMKM.py` saat ini:
- timeout request `60` detik
- retry sampai `5` kali untuk timeout / connection error
- simpan scope gagal ke `failed_report_scopes.json`
- untuk batch, simpan level-2 gagal ke `failed_level2_batches_UMKM.json`

`report_assignment_UB.py` saat ini:
- timeout request `60` detik
- retry sampai `5` kali untuk timeout / connection error
- scope kosong tidak dianggap gagal
- simpan scope gagal ke `failed_report_scopes_UB.json`

## Login

Semua script yang akses API FASIH memakai login manual melalui `login.py`.

Alur singkat:
- browser dibuka
- isi login dan OTP manual, masing-masing diberikan waktu 3 menit
- jika ada OTP, isi manual
- setelah login berhasil, script lanjut memakai cookie sesi
