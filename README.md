# MES Liquid Filling Machine REST API & Analytics Backend

REST API performa tinggi berbasis **Python 3.11+**, **FastAPI**, **Pydantic v2**, dan **Motor (Async MongoDB Driver)** sebagai perantara terpadu antara simulasi **Digital Twin Unity** dan sistem pemantauan **Frontend MES (Manufacturing Execution System)** dengan basis data **MongoDB Atlas** (`liquidfilling`).

Backend ini mendukung dua kelompok integrasi utama:
1. **Unity Digital Twin / ESP32**: Ingest data telemetri real-time (batch 1–10 data), streaming event mesin (*START*, *STOP*, *E-stop*, dll.), dan pencatatan botol selesai beserta inspeksi kualitas fisik.
2. **Frontend MES**: Penyedia data untuk 6 modul utama: **Live Monitoring**, **Produksi**, **Kualitas**, **Downtime**, **Traceability**, dan **Laporan Terpadu**.

---

## 📋 Daftar Isi
- [Fitur Utama](#-fitur-utama)
- [Arsitektur & Konfigurasi Lingkungan](#-arsitektur--konfigurasi-lingkungan)
- [Dokumentasi Endpoint REST API](#-dokumentasi-endpoint-rest-api)
  - [1. Health Check](#1-health-check)
  - [2. Tulis Data (Ingest Unity / Hardware)](#2-tulis-data-ingest-unity--hardware)
  - [3. Live Monitoring & Konfigurasi Mesin](#3-live-monitoring--konfigurasi-mesin)
  - [4. Analitik MES & Laporan](#4-analitik-mes--laporan)
- [Panduan Integrasi Unity Digital Twin](#-panduan-integrasi-unity-digital-twin)
- [Panduan Integrasi Frontend MES](#-panduan-integrasi-frontend-mes)
- [Dokumentasi Interaktif (Swagger & ReDoc)](#-dokumentasi-interaktif-swagger--redoc)
- [Instalasi & Pengujian](#-instalasi--pengujian)

---

## 🚀 Fitur Utama

- **Batch Telemetri Aman & Cepat**: Ingest batch 1–10 dokumen telemetri per request. Pengiriman di luar rentang (kosong atau >10) ditolak HTTP 400.
- **Idempotensi Pengiriman**: Penggunaan field unik `id_kirim` pada telemetri, event, dan botol mencegah duplikasi data akibat retry jaringan Unity.
- **Dukungan Dual Prefix API**: Seluruh endpoint dapat diakses baik melalui prefix versi `/api/v1/...` maupun prefix ringkas `/api/...`.
- **CORS Ketat & Fleksibel**: Whitelist origin khusus frontend MES (Next.js, Vite, React) dengan validasi ketat anti-wildcard `*` pada mode produksi.
- **Validasi Skema Berbahasa Indonesia**: Error validasi bawaan Pydantic v2 (422) diubah menjadi **HTTP 400 Bad Request** dengan pesan jelas dalam Bahasa Indonesia.
- **Traceability Botol Lengkap**: Penelusuran botol individual berdasarkan nomor urut, durasi siklus detik aktual, stasiun kerja, level isi, dan status tutup.
- **Downtime E-Stop Berpasangan**: Analisis otomatis durasi henti mesin darurat berdasarkan pasangan event `estop_tekan` dan `estop_lepas`.

---

## ⚙️ Arsitektur & Konfigurasi Lingkungan

Aplikasi membaca konfigurasi dari environment variables atau file `.env`:

| Variabel | Tipe | Default | Keterangan |
| :--- | :--- | :--- | :--- |
| `ENVIRONMENT` | String | `development` | Pilihan: `development`, `production`, `test`. |
| `MONGODB_URI` | String | *wajib diisi* | Connection string MongoDB Atlas. |
| `MONGODB_DB_NAME` | String | `liquidfilling` | Nama database MongoDB. |
| `API_KEY` | String | *wajib diisi* | Kunci API rahasia untuk otorisasi ingest data. |
| `REQUIRE_KEY_FOR_READ` | Boolean | `false` | Jika `true`, endpoint GET juga memerlukan `X-Api-Key`. |
| `CORS_ORIGINS` | String | `http://localhost:3000,...` | Daftar origin yang diizinkan (dipisahkan koma). Dilarang `*` pada `production`. |
| `API_V1_STR` | String | `/api/v1` | Prefix default API. |
| `API_BASE_URL` | String | `""` | URL publik server API untuk dokumentasi Swagger servers. |
| `PENGGUNA_VALID` | String | `gibral,haikal,alvin,naya`| Daftar operator/pengguna valid (dipisahkan koma). |

> **Catatan Keamanan:** File `.env` tidak pernah di-commit ke Git. Template konfigurasi tersedia di `.env.example`.

---

## 📡 Dokumentasi Endpoint REST API

### 1. Health Check
| Method | Endpoint | Auth | Deskripsi |
| :--- | :--- | :--- | :--- |
| `GET` | `/health`, `/api/health`, `/api/v1/health` | Publik | Cek kesehatan server dan konektivitas MongoDB Atlas (`ping`). |

### 2. Tulis Data (Ingest Unity / Hardware)
*Wajib menyertakan header:* `X-Api-Key: <API_KEY>`

| Method | Endpoint | Payload | Deskripsi |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/telemetri`, `/api/telemetri` | Array `[TelemetriCreate]` (1–10 item) | Simpan data telemetri batch dengan dedup `id_kirim`. |
| `POST` | `/api/v1/event`, `/api/event` | Object `EventCreate` | Simpan event mesin (*START, STOP, estop_tekan, estop_lepas*). |
| `POST` | `/api/v1/botol`, `/api/botol` | Object `BotolCreate` | Simpan data hasil inspeksi botol selesai. |

### 3. Live Monitoring & Konfigurasi Mesin
| Method | Endpoint | Query Params | Deskripsi |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/mesin` | - | Mengambil seluruh daftar mesin yang terdaftar. |
| `GET` | `/api/mesin/{id}` | - | Mengambil data spesifikasi fisik mesin (10 slot, sudut 36°, stasiun, pin GPIO). |
| `GET` | `/api/mesin/{id}/status` | `pengguna`, `sesi_id` | Mengambil 1 dokumen telemetri terbaru untuk live monitoring status mesin. |
| `GET` | `/api/mesin/{id}/event` | `jenis`, `dari`, `sampai`, `sesi_id`, `pengguna`, `sumber`, `mode`, `limit`, `skip`, `page`, `wrap` | Mengambil riwayat event mesin terurut menurun (terbaru duluan) dengan header pagination. |

### 4. Analitik MES & Laporan
| Method | Endpoint | Query Params | Deskripsi |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/mesin/{id}/ringkasan` | `dari`, `sampai`, `sesi_id`, `pengguna` | Ringkasan metrik produksi, botol OK/gagal, rata-rata siklus, kategori defect, downtime, dan rincian per pengguna. |
| `GET` | `/api/mesin/{id}/botol` | `nomor`, `status`, `slot`, `sesi_id`, `pengguna`, `dari`, `sampai`, `page`, `skip`, `limit`, `wrap` | Riwayat botol untuk analisis Kualitas dan Traceability dengan filter & pagination. |
| `GET` | `/api/mesin/{id}/botol/{nomor}` | `sesi_id` | Detail traceability botol individual berdasarkan nomor urut (termasuk `durasi_siklus_detik`). |
| `GET` | `/api/mesin/{id}/downtime` | `dari`, `sampai`, `sesi_id`, `pengguna` | Analisis total durasi henti mesin darurat, frekuensi kejadian, dan rincian per insiden E-stop. |
| `GET` | `/api/mesin/{id}/laporan` | `dari`, `sampai`, `sesi_id`, `pengguna` | Laporan terpadu yang menggabungkan metrik Produksi, Kualitas (persentase & defect), dan Downtime. |

---

## 🎮 Panduan Integrasi Unity Digital Twin

### 1. Header Wajib
Setiap request HTTP dari Unity ke backend wajib menyertakan:
```http
Content-Type: application/json
X-Api-Key: <KUNCI_API_ANDA>
```

### 2. Format Timestamp
Semua field waktu (`waktu`, `waktu_masuk`, `waktu_keluar`) wajib berformat **ISO 8601 UTC** dengan akhiran `Z` atau offset zona waktu:
```text
2026-10-30T10:00:00Z
```

### 3. Contoh Pengiriman Telemetri Batch
Kirimkan batch 1 hingga 10 item secara berkala (misal setiap 1 detik untuk 10 sampel atau 100ms per sampel):
```json
[
  {
    "waktu": "2026-10-30T10:00:00Z",
    "mesin_id": "mesin-01",
    "sesi_id": "sesi-unity-001",
    "pengguna": "gibral",
    "id_kirim": "telem-gibral-100000",
    "darurat": false,
    "mode": "Berjalan",
    "mcb": {
      "utama": true,
      "mesin": true,
      "kontrol": true,
      "lampu": true
    },
    "sudut_turret_deg": 36.0,
    "botol_selesai": 10,
    "isi_kotak": 10,
    "sisa_peti": 11,
    "tahap": "Pengisian",
    "langkah": 2,
    "gpio": {
      "step": true,
      "dir": false,
      "pompa": true
    }
  }
]
```

### 4. Contoh Pengiriman Data Botol (Kualitas & Traceability)
Kirimkan saat botol telah selesai diproses dan jatuh ke kotak penampung:
```json
{
  "mesin_id": "mesin-01",
  "sesi_id": "sesi-unity-001",
  "pengguna": "gibral",
  "id_kirim": "botol-gibral-001",
  "nomor": 1,
  "slot": 1,
  "waktu_masuk": "2026-10-30T10:00:00Z",
  "waktu_isi_mulai": "2026-10-30T10:00:02Z",
  "waktu_isi_selesai": "2026-10-30T10:00:06Z",
  "waktu_tutup": "2026-10-30T10:00:08Z",
  "waktu_keluar": "2026-10-30T10:00:10Z",
  "level_isi": 1.0,
  "bertutup": true,
  "status": "OK"
}
```
*Catatan status botol:* Nilai yang diterima adalah `"OK"`, `"TIDAK_PENUH"`, atau `"TANPA_TUTUP"`.

---

## 💻 Panduan Integrasi Frontend MES

Frontend MES (Next.js / Vite / React) berkomunikasi dengan backend melalui HTTP REST API:

### 1. Konfigurasi Base URL
Gunakan base URL API sesuai lingkungan deployment Anda:
- Development: `http://localhost:8000/api` (atau `http://localhost:8000/api/v1`)
- Production: `https://api.fillingmachine.domainkamu.com/api`

### 2. Pemetaan Modul Halaman Frontend MES
| Halaman Frontend | Endpoint Backend Utama | Data yang Didapat |
| :--- | :--- | :--- |
| **Live Monitoring** | `GET /api/mesin/mesin-01/status`<br>`GET /api/mesin/mesin-01/event?limit=10`<br>`GET /api/mesin/mesin-01` | Status mesin real-time, mode, sudut turret, status MCB, pin GPIO, langkah proses, dan log event terbaru. |
| **Halaman Produksi** | `GET /api/mesin/mesin-01/ringkasan`<br>`GET /api/mesin/mesin-01/laporan` | Jumlah botol diproduksi, rata-rata durasi siklus, pembagian metrik per operator. |
| **Halaman Kualitas** | `GET /api/mesin/mesin-01/ringkasan`<br>`GET /api/mesin/mesin-01/botol?status=TIDAK_PENUH` | Total botol OK vs Gagal, yield percentage, kategori defect (`TIDAK_PENUH`, `TANPA_TUTUP`). |
| **Halaman Downtime** | `GET /api/mesin/mesin-01/downtime` | Total durasi E-stop, frekuensi kejadian, daftar detail waktu mulai & selesai setiap insiden. |
| **Halaman Traceability** | `GET /api/mesin/mesin-01/botol`<br>`GET /api/mesin/mesin-01/botol/{nomor}` | Pencarian botol per nomor seri, riwayat waktu setiap stasiun, dan durasi siklus per botol. |
| **Halaman Laporan** | `GET /api/mesin/mesin-01/laporan?dari=...&sampai=...` | Rekapitulasi terpadu kinerja shift/periode tertentu (Produksi, Kualitas, dan Downtime). |

### 3. Pagination & Headers
Endpoint daftar (`/botol` dan `/event`) menyediakan metadata pagination melalui HTTP response headers:
- `X-Total-Count`: Jumlah total dokumen yang cocok dengan filter.
- `X-Page`: Nomor halaman saat ini.
- `X-Limit`: Batas item per halaman.
- `X-Total-Pages`: Total jumlah halaman yang tersedia.

Jika parameter query `wrap=true` digunakan, response JSON dibungkus dalam objek:
```json
{
  "total": 120,
  "page": 1,
  "limit": 50,
  "skip": 0,
  "total_pages": 3,
  "items": [...]
}
```

---

## 📖 Dokumentasi Interaktif (Swagger & ReDoc)

Saat server berjalan, Anda dapat mengakses dokumentasi interaktif yang dikelompokkan rapi ke dalam 4 tag utama (**Health**, **Tulis Data**, **Live Monitoring & Konfigurasi Mesin**, **Analitik MES & Laporan**):

- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **OpenAPI JSON**: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

---

## 🧪 Instalasi & Pengujian

### 1. Menyiapkan Virtual Environment
```bash
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Menjalankan Server Development
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Menjalankan Seluruh Automated Test Suite
Pengujian menggunakan database terisolasi (`mongomock_motor`) dan tidak memerlukan koneksi internet aktif:
```bash
pytest -v
```

Seluruh 48 pengujian mencakup:
- Keamanan & Autentikasi API Key (`tests/test_auth.py`)
- CORS & Isolasi Environment (`tests/test_cors_and_config.py`)
- Validasi Input Pydantic (`tests/test_validation.py`)
- Ingestion Data & Idempotensi (`tests/test_tulis.py`)
- Live Monitoring Mesin (`tests/test_live_monitoring.py`)
- Analitik Produksi, Kualitas & Downtime (`tests/test_production_and_quality.py`)
- Endpoint Baca & Agregasi (`tests/test_baca.py`)
- Integration Tests Unity & Frontend MES (`tests/test_integration_unity_and_frontend.py`)
