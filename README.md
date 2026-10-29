# Liquid Filling Machine REST API

REST API performa tinggi berbasis **Python 3.11+**, **FastAPI**, **Pydantic v2**, dan **Motor (Async MongoDB Driver)** sebagai perantara antara sumber data (*digital twin* Unity dan perangkat keras ESP32) ke database **MongoDB Atlas** (`liquidfilling`), sesuai dokumen PRD Pencatatan Data Mesin Pengisi Botol ke MongoDB (Fase 1 & Fase 3).

---

## 📋 Fitur Utama

1. **Endpoint Tulis (Fase 1)**:
   - `POST /api/v1/telemetri`: Batch ingestion 1–10 dokumen telemetri. Dilengkapi deduplikasi `id_kirim` di level API untuk collection time series.
   - `POST /api/v1/event`: Pencatatan kejadian mesin (*START, E-stop, MCB, status kotak/peti*). Idempoten dengan penangkapan `DuplicateKeyError` pada `id_kirim`.
   - `POST /api/v1/botol`: Pencatatan riwayat siklus setiap botol saat masuk kotak penampung. Idempoten dengan penanganan `DuplicateKeyError`.
2. **Endpoint Baca & Analisis (Fase 3)**:
   - `GET /api/v1/mesin/{id}`: Membaca spesifikasi dan konfigurasi fisik mesin.
   - `GET /api/v1/mesin/{id}/status`: Membaca telemetri terakhir (terkini).
   - `GET /api/v1/mesin/{id}/ringkasan`: Agregasi metrik produksi: total botol, botol cacat/gagal (`status != "OK"`), rata-rata waktu siklus (`waktu_keluar - waktu_masuk`), serta total durasi status Darurat (E-stop ditekan).
   - `GET /api/v1/mesin/{id}/event`: Riwayat kejadian mesin dengan penyortiran waktu menurun (*newest first*) dan filter multi-kriteria (`jenis`, `sesi_id`, rentang `dari`-`sampai`, `limit`).
3. **Kesehatan Sistem**:
   - `GET /api/v1/health` dan `GET /health`: Pemeriksaan liveness API dan verifikasi koneksi ping ke MongoDB Atlas.
4. **Keamanan & Validasi**:
   - Autentikasi `X-Api-Key` per mesin menggunakan `secrets.compare_digest` untuk proteksi terhadap *timing attacks*.
   - Verifikasi kepemilikan mesin: kunci mesin `mesin-01` tidak dapat digunakan untuk menulis data mesin `mesin-02` (HTTP 403 Forbidden).
   - Seluruh timestamp wajib format ISO 8601 UTC dengan zona waktu (contoh: `2026-10-29T10:00:00Z`). Timestamp naive tanpa zona waktu otomatis ditolak.
   - Server otomatis menambahkan field `diterima` (UTC server time) pada setiap dokumen yang disimpan.
   - Format error validasi bawaan FastAPI (422) ditransformasikan menjadi **HTTP 400 Bad Request** dengan pesan jelas berbahasa Indonesia dan jalur field yang bermasalah.
   - Mendukung kompatibilitas skema ke depan (skema v1): field tambahan yang tidak dikenal diizinkan dan tidak ditolak.

---

## 🏗️ Struktur Proyek

```text
FillingMachine/
├── app/
│   ├── __init__.py
│   ├── main.py              # Entrypoint FastAPI, exception handler 400, lifecycle DB
│   ├── config.py            # Konfigurasi via pydantic-settings & parsing API key
│   ├── db.py                # Inisialisasi Async Motor client (singleton connection)
│   ├── auth.py              # Autentikasi X-Api-Key, compare_digest, otorisasi mesin
│   ├── models.py            # Skema Pydantic v2, validasi UTC tz-aware, enum, extra=allow
│   └── routers/
│       ├── __init__.py
│       ├── tulis.py         # POST telemetri, event, botol
│       ├── baca.py          # GET mesin, status, ringkasan, event
│       └── health.py        # GET health check
├── tests/
│   ├── conftest.py          # Fixtures pytest, AsyncClient, mock MongoDB (mongomock-motor)
│   ├── test_auth.py         # Uji 401, 403, dan proteksi kunci baca
│   ├── test_validation.py   # Uji penolakan timestamp tanpa timezone, enum, batas level
│   ├── test_tulis.py        # Uji tulis batch, dedup telemetri, idempotensi event/botol
│   ├── test_baca.py         # Uji ringkasan, metrik durasi darurat, status terkini
│   └── test_health.py       # Uji ping endpoint health
├── .env.example             # Template konfigurasi environment variables
├── .gitignore               # Memastikan .env dan cache tidak ter-commit
├── Dockerfile               # Kontainerisasi siap produksi
├── pytest.ini               # Konfigurasi test runner
├── requirements.txt         # Daftar pustaka Python
├── setup_mongodb.py         # Skrip pembuatan collection & indeks MongoDB awal
└── README.md                # Dokumentasi panduan penggunaan
```

---

## ⚙️ Persyaratan Sistem & Instalasi

### 1. Prasyarat
- Python 3.11 atau lebih baru (direkomendasikan Python 3.12)
- Koneksi internet untuk mengakses MongoDB Atlas

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
MONGODB_URI=mongodb+srv://<username>:<password>@<cluster>.mongodb.net/?retryWrites=true&w=majority
MONGODB_DB_NAME=liquidfilling

# API Key per mesin (format: mesin_id:api_key dipisahkan koma)
MESIN_API_KEYS=mesin-01:kunci-rahasia-mesin-01,mesin-02:kunci-rahasia-mesin-02

# Opsi proteksi endpoint baca (default false untuk kemudahan dashboard)
REQUIRE_KEY_FOR_READ=false

# Konstanta nama jenis event untuk E-stop
EVENT_JENIS_ESTOP_TEKAN=estop_tekan
EVENT_JENIS_ESTOP_LEPAS=estop_lepas

# Konfigurasi Server
HOST=0.0.0.0
PORT=8000
DEBUG=false
```

> **Catatan Keamanan**: Connection string `MONGODB_URI` dijaga ketat di tingkat server API dan tidak pernah dicetak ke console atau log.

---

## 🚀 Menjalankan Server

### Menjalankan Langsung dengan Uvicorn

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Dokumentasi interaktif OpenAPI / Swagger UI dapat diakses di:
👉 **`http://localhost:8000/docs`** atau **`http://localhost:8000/redoc`**

---

## 🧪 Menjalankan Pengujian Otomatis (Unit & Integration Tests)

Semua pengujian menggunakan mock async MongoDB (`mongomock-motor`) sehingga dapat dijalankan kapan saja secara independen dan cepat tanpa memerlukan koneksi jaringan Atlas aktif:

```powershell
python -m pytest -v
```

Hasil uji:
- **19 test cases** mencakup otentikasi, validasi data, idempotensi dedup, ringkasan durasi darurat, dan health check.

---

## 🐳 Menjalankan dengan Docker

```bash
# Build Docker image
docker build -t filling-machine-api:latest .

# Jalankan container dengan file .env
docker run -d --name filling-api -p 8000:8000 --env-file .env filling-machine-api:latest

# Periksa log
docker logs -f filling-api
```

---

## 📡 Contoh Penggunaan Endpoint (cURL)

Berikut adalah contoh lengkap perintah cURL untuk seluruh endpoint API:

### 1. Health Check
```bash
curl -X GET "http://localhost:8000/api/v1/health"
```
**Contoh Respons (HTTP 200)**:
```json
{
  "status": "ok",
  "database": "terhubung",
  "waktu": "2026-10-29T10:30:00.123456+00:00"
}
```

---

### 2. Kirim Batch Dokumen Telemetri (POST /api/v1/telemetri)
> **Ketentuan**: 1–10 dokumen per request. Wajib membawa header `X-Api-Key`.
```bash
curl -X POST "http://localhost:8000/api/v1/telemetri" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: kunci-rahasia-mesin-01" \
  -d '[
    {
      "waktu": "2026-10-29T10:00:00Z",
      "mesin_id": "mesin-01",
      "sesi_id": "sesi-20261029-01",
      "id_kirim": "telem-uuid-001",
      "mode": "Berjalan",
      "darurat": false,
      "mcb": {
        "utama": true,
        "mesin": true,
        "kontrol": true,
        "lampu": true
      },
      "tahap": "Pengisian",
      "langkah": 2,
      "sudut_turret_deg": 36.0,
      "botol_selesai": 12,
      "isi_kotak": 12,
      "sisa_peti": 18,
      "operator_tugas": "Mengawasi",
      "gpio": {
        "step": true,
        "dir": true,
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
> **Ketentuan**: 1 dokumen per request. Wajib membawa header `X-Api-Key`.
```bash
curl -X POST "http://localhost:8000/api/v1/event" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: kunci-rahasia-mesin-01" \
  -d '{
    "waktu": "2026-10-29T10:05:00Z",
    "mesin_id": "mesin-01",
    "sesi_id": "sesi-20261029-01",
    "id_kirim": "event-uuid-101",
    "jenis": "estop_tekan",
    "mode_sebelum": "Berjalan",
    "mode_sesudah": "Darurat",
    "pesan": "Tombol darurat ditekan oleh operator",
    "sumber": "operator",
    "detail": {
      "alasan": "Botol macet di stasiun infeed"
    }
  }'
```
**Contoh Respons (HTTP 201)**:
```json
{
  "status": "sukses",
  "pesan": "event berhasil disimpan",
  "id_kirim": "event-uuid-101",
  "tersimpan": true,
  "id": "6720f123456789abcdef0123"
}
```
*Jika dikirim ulang dengan `id_kirim` yang sama*:
```json
{
  "status": "sukses",
  "pesan": "duplikat diabaikan",
  "id_kirim": "event-uuid-101",
  "tersimpan": false,
  "id": null
}
```

---

### 4. Kirim Data Botol Selesai (POST /api/v1/botol)
> **Ketentuan**: 1 dokumen saat botol masuk ke kotak. Wajib membawa header `X-Api-Key`.
```bash
curl -X POST "http://localhost:8000/api/v1/botol" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: kunci-rahasia-mesin-01" \
  -d '{
    "mesin_id": "mesin-01",
    "sesi_id": "sesi-20261029-01",
    "id_kirim": "botol-uuid-201",
    "nomor": 13,
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
```bash
curl -X GET "http://localhost:8000/api/v1/mesin/mesin-01/status"
```
**Contoh Respons (HTTP 200)**:
```json
{
  "_id": "6720f789abcdef1234567890",
  "waktu": "2026-10-29T10:00:00.000Z",
  "mesin_id": "mesin-01",
  "sesi_id": "sesi-20261029-01",
  "mode": "Berjalan",
  "darurat": false,
  "sudut_turret_deg": 36.0,
  "botol_selesai": 12,
  "isi_kotak": 12,
  "sisa_peti": 18
}
```

---

### 7. Ambil Ringkasan Produksi (GET /api/v1/mesin/{id}/ringkasan)
Parameter opsional: `dari`, `sampai` (ISO 8601 UTC), `sesi_id`.
```bash
curl -X GET "http://localhost:8000/api/v1/mesin/mesin-01/ringkasan?dari=2026-10-29T08:00:00Z&sampai=2026-10-29T12:00:00Z&sesi_id=sesi-20261029-01"
```
**Contoh Respons (HTTP 200)**:
```json
{
  "mesin_id": "mesin-01",
  "sesi_id": "sesi-20261029-01",
  "rentang": {
    "dari": "2026-10-29T08:00:00+00:00",
    "sampai": "2026-10-29T12:00:00+00:00"
  },
  "jumlah_botol": 45,
  "botol_gagal": 3,
  "rata_rata_waktu_siklus_detik": 14.852,
  "total_durasi_darurat_detik": 75.32
}
```

---

### 8. Ambil Riwayat Event Mesin (GET /api/v1/mesin/{id}/event)
Parameter opsional: `jenis`, `sesi_id`, `dari`, `sampai`, `limit` (default 100, maks 1000).
```bash
curl -X GET "http://localhost:8000/api/v1/mesin/mesin-01/event?limit=10"
```
**Contoh Respons (HTTP 200)**:
```json
[
  {
    "_id": "6720f999abcdef0123456789",
    "waktu": "2026-10-29T10:05:00.000Z",
    "mesin_id": "mesin-01",
    "sesi_id": "sesi-20261029-01",
    "jenis": "estop_tekan",
    "mode_sebelum": "Berjalan",
    "mode_sesudah": "Darurat",
    "sumber": "operator",
    "pesan": "Tombol darurat ditekan oleh operator"
  }
]
```

---

## 🔍 Logika Perhitungan Durasi Status Darurat

Durasi darurat dihitung dengan cara:
1. Mengambil seluruh event berjenis `estop_tekan` dan `estop_lepas` untuk `mesin_id` yang diminta (dan `sesi_id` jika difilter).
2. Mengelompokkan event per `sesi_id` dan mengurutkannya secara kronologis waktu.
3. Memasangkan setiap kejadian `estop_tekan` dengan `estop_lepas` berikutnya.
4. Apabila tombol `estop_tekan` belum dilepas (*active emergency*), durasi dihitung sampai batas parameter `sampai` (atau waktu server sekarang jika `sampai` tidak diberikan).
5. Interval darurat dipotong (*clipped*) tepat di dalam rentang filter `[dari, sampai]` agar data agregasi waktu shift akurat.
