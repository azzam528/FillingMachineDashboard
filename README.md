# Liquid Filling Machine REST API

REST API performa tinggi berbasis **Python 3.11+**, **FastAPI**, **Pydantic v2**, dan **Motor (Async MongoDB Driver)** sebagai perantara antara *digital twin* Unity dan database **MongoDB Atlas** (`liquidfilling`), sesuai dokumen PRD Pencatatan Data Mesin Pengisi Botol ke MongoDB (Cakupan: API Tulis & Health Fase 1, serta Endpoint Baca & Ringkasan Fase 3).

---

## 📋 Fitur Utama

1. **Endpoint Tulis (Fase 1)**:
   - `POST /api/v1/telemetri`: Batch ingestion 1–10 dokumen telemetri (lebih dari 10 atau kosong ditolak 400). Deduplikasi `id_kirim` di level API untuk collection time series.
   - `POST /api/v1/event`: Pencatatan kejadian mesin (*START, estop_tekan, estop_lepas, MCB, dll.*). Idempoten dengan penangkapan `DuplicateKeyError` pada `id_kirim`.
   - `POST /api/v1/botol`: Pencatatan siklus setiap botol saat masuk kotak penampung (*OK, TIDAK_PENUH, TANPA_TUTUP*). Idempoten dengan penanganan `DuplicateKeyError`.
2. **Endpoint Baca & Analisis (Fase 3)**:
   - `GET /api/v1/mesin/{id}`: Membaca spesifikasi dan konfigurasi fisik mesin (`mesin-01`).
   - `GET /api/v1/mesin/{id}/status`: Membaca telemetri terakhir (terkini), mendukung filter opsional `pengguna`.
   - `GET /api/v1/mesin/{id}/ringkasan`: Agregasi metrik produksi: total botol, botol gagal (`status != "OK"`), rata-rata waktu siklus (`waktu_keluar - waktu_masuk`), serta total durasi status Darurat (*E-stop* ditekan). Mendukung filter `sesi_id`, rentang `dari`-`sampai`, dan `pengguna`. Menampilkan **rincian per pengguna** jika filter `pengguna` tidak ditentukan.
   - `GET /api/v1/mesin/{id}/event`: Riwayat kejadian mesin terurut dari yang terbaru (*newest first*) dengan filter multi-kriteria (`jenis`, `sesi_id`, `pengguna`, `dari`, `sampai`, `limit` 1–1000).
3. **Kesehatan Sistem**:
   - `GET /api/v1/health` dan `GET /health`: Pemeriksaan liveness API dan verifikasi koneksi ping ke MongoDB Atlas.
4. **Keamanan, Multi-Pengguna & Validasi**:
   - Autentikasi `X-Api-Key` tunggal via environment variable `API_KEY` menggunakan `secrets.compare_digest` untuk mencegah *timing attacks*.
   - Validasi bahwa `mesin_id` terdaftar di collection `mesin` (jika tidak -> HTTP 400).
   - Pengelolaan multi-pengguna: Setiap dokumen telemetri, event, dan botol wajib membawa field `pengguna` (`gibral`, `haikal`, `alvin`, `naya` via env `PENGGUNA_VALID`). Huruf dinormalisasi ke huruf kecil.
   - Seluruh timestamp wajib format ISO 8601 UTC dengan zona waktu (contoh: `2026-10-29T10:00:00Z`). Timestamp naive tanpa zona waktu otomatis ditolak HTTP 400.
   - Server otomatis menambahkan timestamp `diterima` (UTC server time) pada setiap dokumen yang disimpan.
   - Format error validasi bawaan FastAPI (422) ditransformasikan menjadi **HTTP 400 Bad Request** dengan pesan jelas berbahasa Indonesia dan jalur field yang bermasalah.
   - Mendukung kompatibilitas skema ke depan (skema v1): field tambahan yang tidak dikenal diizinkan (`extra="allow"`).

---

## 🏗️ Struktur Proyek

```text
FillingMachine/
├── app/
│   ├── __init__.py
│   ├── main.py              # Entrypoint FastAPI, exception handler 400, lifecycle DB
│   ├── config.py            # Konfigurasi via pydantic-settings (API_KEY, PENGGUNA_VALID)
│   ├── db.py                # Inisialisasi Async Motor client (singleton connection)
│   ├── auth.py              # Autentikasi X-Api-Key, compare_digest, validasi mesin_id
│   ├── models.py            # Skema Pydantic v2, validasi UTC tz-aware, enum, extra=allow
│   └── routers/
│       ├── __init__.py
│       ├── tulis.py         # POST telemetri, event, botol
│       ├── baca.py          # GET mesin, status, ringkasan, event
│       └── health.py        # GET health check
├── scripts/
│   └── seed_contoh.py       # Script pengiriman dokumen contoh via API HTTP
├── tests/
│   ├── conftest.py          # Fixtures pytest, AsyncClient, isolasi liquidfilling_test
│   ├── test_auth.py         # Uji otentikasi X-Api-Key, 401, dan proteksi kunci baca
│   ├── test_validation.py   # Uji field wajib, enum, timestamp timezone, pengguna, extra fields
│   ├── test_tulis.py        # Uji tulis batch telemetri, dedup telemetri, idempotensi event & botol
│   ├── test_baca.py         # Uji status, filter pengguna, event, dan kalkulasi manual ringkasan
│   └── test_health.py       # Uji ping endpoint health check
├── .env.example             # Template konfigurasi environment variables
├── .env                     # Konfigurasi lokal aktif (tidak di-commit ke Git)
├── .gitignore               # Memastikan .env dan cache tidak ter-commit
├── Dockerfile               # Kontainerisasi siap produksi
├── pytest.ini               # Konfigurasi test runner pytest
├── requirements.txt         # Daftar pustaka Python
├── setup_mongodb.py         # Skrip pembuatan collection & indeks MongoDB Atlas
├── LAPORAN.md               # Laporan teknis lengkap implementasi backend
└── README.md                # Dokumentasi panduan penggunaan & cURL
```

---

## ⚙️ Persyaratan Sistem & Instalasi

### 1. Prasyarat
- Python 3.11 atau lebih baru (direkomendasikan Python 3.12)
- Koneksi internet untuk mengakses cluster MongoDB Atlas

### 2. Membuat Virtual Environment & Memasang Dependensi

```powershell
# Buka direktori proyek
cd f:\coding\FillingMachine

# Buat virtual environment
python -m venv .venv

# Aktifkan virtual environment (Windows PowerShell)
.\.venv\Scripts\Activate.ps1

# Pasang dependensi
pip install -r requirements.txt
```

### 3. Konfigurasi Environment Variable (`.env`)

Salin file `.env.example` menjadi `.env`:

```powershell
Copy-Item .env.example .env
```

Sesuaikan isi `.env`:

```env
# MongoDB Connection URI (dari MongoDB Atlas)
MONGODB_URI=mongodb+srv://<username>:<password>@<cluster>.mongodb.net/
MONGODB_DB_NAME=liquidfilling

# Autentikasi API Key tunggal untuk semua pengirim
API_KEY=kunci-rahasia-digital-twin

# Opsi proteksi endpoint baca (default false untuk kemudahan dashboard)
REQUIRE_KEY_FOR_READ=false

# Daftar pengguna yang sah dipisahkan koma
PENGGUNA_VALID=gibral,haikal,alvin,naya

# Konstanta nama jenis event untuk E-stop
EVENT_JENIS_ESTOP_TEKAN=estop_tekan
EVENT_JENIS_ESTOP_LEPAS=estop_lepas

# Konfigurasi Server
HOST=0.0.0.0
PORT=8000
DEBUG=false
```

> **Catatan Keamanan**: Kredensial `MONGODB_URI` dan `API_KEY` dijaga ketat di tingkat server API dan tidak pernah dicetak ke console atau file log.

---

## 🚀 Menjalankan Server & Seeding Data

### 1. Menjalankan Server API

```powershell
.\.venv\Scripts\uvicorn.exe app.main:app --host 0.0.0.0 --port 8000 --reload
```

Dokumentasi interaktif OpenAPI / Swagger UI dapat diakses di browser:
👉 **`http://localhost:8000/docs`** atau **`http://localhost:8000/redoc`**

### 2. Menjalankan Seeding Data Contoh via API

Jalankan script `seed_contoh.py` untuk memverifikasi alur pengiriman data HTTP:

```powershell
.\.venv\Scripts\python.exe scripts/seed_contoh.py
```

---

## 🧪 Menjalankan Pengujian Otomatis

Semua pengujian dijalankan terhadap database terpisah `liquidfilling_test` yang diisolasi, memvalidasi skema, otentikasi, deduplikasi, dan metrik:

```powershell
.\.venv\Scripts\pytest.exe -v
```

Hasil uji: **24 passed** mencakup seluruh kriteria verifikasi:
- Otentikasi `X-Api-Key` (401 saat tidak ada/salah, proteksi read toggle).
- Validasi data & enum (400 untuk field salah/hilang, enum salah, timestamp tanpa zona waktu).
- Validasi `pengguna` (wajib ada, ditolak 400 jika di luar daftar, case-insensitive).
- Validasi `mesin_id` (wajib terdaftar di database `mesin`, ditolak 400 jika tidak dikenal).
- Batch telemetri 1–10 (kosong ditolak 400, >10 ditolak 400).
- Deduplikasi `id_kirim` (telemetri di level API, event & botol via `DuplicateKeyError` idempoten).
- Perhitungan ringkasan manual (total botol, botol cacat, durasi siklus, durasi darurat E-stop berpasangan, dan rincian per pengguna).

---

## 🐳 Menjalankan dengan Docker

```bash
# Build Docker image
docker build -t filling-machine-api:latest .

# Jalankan container dengan file .env
docker run -d --name filling-api -p 8000:8000 --env-file .env filling-machine-api:latest

# Periksa log container
docker logs -f filling-api
```

---

## 📡 Contoh Penggunaan Endpoint (cURL)

Berikut adalah contoh perintah cURL untuk seluruh endpoint API:

### 1. Health Check
```bash
curl -X GET "http://localhost:8000/api/v1/health"
```
**Contoh Respons (HTTP 200)**:
```json
{
  "status": "ok",
  "database": "terhubung",
  "waktu": "2026-10-29T10:30:00.123456+00:00",
  "detail": null
}
```

---

### 2. Kirim Batch Telemetri (POST /api/v1/telemetri)
> **Ketentuan**: 1–10 dokumen per request. Wajib membawa header `X-Api-Key` dan field `pengguna`.
```bash
curl -X POST "http://localhost:8000/api/v1/telemetri" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: Sj0ETn-bp1lMiGASdQfdW5WiGEoIU2XskRp41IKy9vU" \
  -d '[
    {
      "waktu": "2026-10-29T10:00:00Z",
      "mesin_id": "mesin-01",
      "sesi_id": "gibral-20261029-1000",
      "pengguna": "gibral",
      "id_kirim": "tel-uuid-001",
      "mode": "Berjalan",
      "darurat": false,
      "mcb": {
        "utama": true,
        "mesin": true,
        "kontrol": true,
        "lampu": true
      },
      "tahap": 2,
      "langkah": 3,
      "sudut_turret_deg": 72.0,
      "botol_selesai": 15,
      "isi_kotak": 15,
      "sisa_peti": 105,
      "operator_tugas": "memantau",
      "gpio": {
        "step": true,
        "dir": false,
        "en": true,
        "pompa": true,
        "buzzer": false,
        "ir": true,
        "start": false,
        "limit": false
      }
    }
  ]'
```
**Contoh Respons (HTTP 201)**:
```json
{
  "status": "sukses",
  "pesan": "1 data tersimpan, 0 duplikat diabaikan",
  "tersimpan": 1,
  "duplikat_diabaikan": 0
}
```

---

### 3. Kirim Kejadian Mesin / Event (POST /api/v1/event)
> **Ketentuan**: 1 dokumen per request. Wajib membawa header `X-Api-Key` dan field `pengguna`.
```bash
curl -X POST "http://localhost:8000/api/v1/event" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: Sj0ETn-bp1lMiGASdQfdW5WiGEoIU2XskRp41IKy9vU" \
  -d '{
    "waktu": "2026-10-29T10:05:00Z",
    "mesin_id": "mesin-01",
    "sesi_id": "haikal-20261029-1005",
    "pengguna": "haikal",
    "id_kirim": "ev-uuid-101",
    "jenis": "estop_tekan",
    "mode_sebelum": "Berjalan",
    "mode_sesudah": "Darurat",
    "pesan": "Tombol darurat ditekan oleh pemain Haikal",
    "sumber": "pemain",
    "detail": {
      "alasan": "Posisi botol miring di konveyor"
    }
  }'
```
**Contoh Respons (HTTP 201)**:
```json
{
  "status": "sukses",
  "pesan": "event berhasil disimpan",
  "id_kirim": "ev-uuid-101",
  "tersimpan": true,
  "id": "6720f123456789abcdef0123"
}
```
*Jika dikirim ulang dengan `id_kirim` yang sama*:
```json
{
  "status": "sukses",
  "pesan": "duplikat diabaikan",
  "id_kirim": "ev-uuid-101",
  "tersimpan": false,
  "id": null
}
```

---

### 4. Kirim Data Botol Selesai (POST /api/v1/botol)
> **Ketentuan**: 1 dokumen saat botol masuk kotak. Wajib membawa header `X-Api-Key` dan field `pengguna`.
```bash
curl -X POST "http://localhost:8000/api/v1/botol" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: Sj0ETn-bp1lMiGASdQfdW5WiGEoIU2XskRp41IKy9vU" \
  -d '{
    "mesin_id": "mesin-01",
    "sesi_id": "alvin-20261029-1010",
    "pengguna": "alvin",
    "id_kirim": "botol-uuid-201",
    "nomor": 1,
    "slot": 4,
    "waktu_masuk": "2026-10-29T10:04:45Z",
    "waktu_isi_mulai": "2026-10-29T10:04:48Z",
    "waktu_isi_selesai": "2026-10-29T10:04:52Z",
    "waktu_tutup": "2026-10-29T10:04:56Z",
    "waktu_keluar": "2026-10-29T10:05:00Z",
    "level_isi": 0.98,
    "bertutup": true,
    "status": "OK"
  }'
```
**Contoh Respons (HTTP 201)**:
```json
{
  "status": "sukses",
  "pesan": "botol berhasil disimpan",
  "id_kirim": "botol-uuid-201",
  "tersimpan": true,
  "id": "6720f4567890abcdef123456"
}
```

---

### 5. Ambil Konfigurasi Mesin (GET /api/v1/mesin/{id})
```bash
curl -X GET "http://localhost:8000/api/v1/mesin/mesin-01"
```
**Contoh Respons (HTTP 200)**:
```json
{
  "_id": "mesin-01",
  "nama": "Mesin Pengisi Botol Rotary 10 Slot (Digital Twin)",
  "jumlah_slot": 10,
  "sudut_per_slot_deg": 36,
  "stasiun": {
    "infeed": 36,
    "isi": 180,
    "capping": 144,
    "buang": 108
  },
  "kapasitas_kotak": 30,
  "kapasitas_peti": 12,
  "pin_gpio": {
    "step": null,
    "dir": null,
    "en": null,
    "pompa": null,
    "buzzer": null,
    "ir": null,
    "start": null,
    "limit": null
  }
}
```

---

### 6. Ambil Status Telemetri Terakhir (GET /api/v1/mesin/{id}/status)
Parameter opsional: `pengguna`.
```bash
# Tanpa filter (mengambil data telemetri terbaru dari semua pengguna)
curl -X GET "http://localhost:8000/api/v1/mesin/mesin-01/status"

# Dengan filter pengguna
curl -X GET "http://localhost:8000/api/v1/mesin/mesin-01/status?pengguna=gibral"
```
**Contoh Respons (HTTP 200)**:
```json
{
  "_id": "6720f789abcdef1234567890",
  "waktu": "2026-10-29T10:00:00.000Z",
  "mesin_id": "mesin-01",
  "sesi_id": "gibral-20261029-1000",
  "pengguna": "gibral",
  "mode": "Berjalan",
  "darurat": false,
  "sudut_turret_deg": 72.0,
  "botol_selesai": 15,
  "isi_kotak": 15,
  "sisa_peti": 105
}
```

---

### 7. Ambil Ringkasan Produksi (GET /api/v1/mesin/{id}/ringkasan)
Parameter opsional: `dari`, `sampai` (ISO 8601 UTC), `sesi_id`, `pengguna`.
```bash
# Ringkasan keseluruhan mesin (dengan rincian per pengguna)
curl -X GET "http://localhost:8000/api/v1/mesin/mesin-01/ringkasan"

# Ringkasan dengan filter rentang waktu dan pengguna spesifik
curl -X GET "http://localhost:8000/api/v1/mesin/mesin-01/ringkasan?pengguna=gibral&dari=2026-10-29T08:00:00Z&sampai=2026-10-29T12:00:00Z"
```
**Contoh Respons Tanpa Filter Pengguna (HTTP 200)**:
```json
{
  "mesin_id": "mesin-01",
  "sesi_id": null,
  "pengguna": null,
  "rentang": {
    "dari": null,
    "sampai": null
  },
  "jumlah_botol": 45,
  "botol_gagal": 3,
  "rata_rata_waktu_siklus_detik": 14.852,
  "total_durasi_darurat_detik": 75.32,
  "rincian_pengguna": {
    "gibral": {
      "jumlah_botol": 30,
      "botol_gagal": 1,
      "rata_rata_waktu_siklus_detik": 14.2,
      "total_durasi_darurat_detik": 45.0
    },
    "haikal": {
      "jumlah_botol": 15,
      "botol_gagal": 2,
      "rata_rata_waktu_siklus_detik": 16.156,
      "total_durasi_darurat_detik": 30.32
    }
  }
}
```

---

### 8. Ambil Riwayat Event Mesin (GET /api/v1/mesin/{id}/event)
Parameter opsional: `jenis`, `sesi_id`, `pengguna`, `dari`, `sampai`, `limit` (default 100, maks 1000).
```bash
curl -X GET "http://localhost:8000/api/v1/mesin/mesin-01/event?pengguna=haikal&jenis=estop_tekan&limit=10"
```
**Contoh Respons (HTTP 200)**:
```json
[
  {
    "_id": "6720f999abcdef0123456789",
    "waktu": "2026-10-29T10:05:00.000Z",
    "mesin_id": "mesin-01",
    "sesi_id": "haikal-20261029-1005",
    "pengguna": "haikal",
    "jenis": "estop_tekan",
    "mode_sebelum": "Berjalan",
    "mode_sesudah": "Darurat",
    "sumber": "pemain",
    "pesan": "Tombol darurat ditekan oleh pemain Haikal"
  }
]
```
