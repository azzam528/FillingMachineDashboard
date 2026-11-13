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
- **Prefix Routing API Bersih**: Seluruh endpoint terstandarisasi di bawah prefix ringkas `/api/...` (misal: `/api/telemetri`, `/api/event`, `/api/botol`, `/api/mesin/...`).
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
| `API_PREFIX` | String | `/api` | Prefix default API. |
| `API_BASE_URL` | String | `""` | URL publik server API untuk dokumentasi Swagger servers. |
| `PENGGUNA_VALID` | String | `gibral,haikal,alvin,naya`| Daftar operator/pengguna valid (dipisahkan koma). |

> **Catatan Keamanan:** File `.env` tidak pernah di-commit ke Git. Template konfigurasi tersedia di `.env.example`.

---

## 📡 Dokumentasi Endpoint REST API

### 1. Health Check
| Method | Endpoint | Auth | Deskripsi |
| :--- | :--- | :--- | :--- |
| `GET` | `/health`, `/api/health` | Publik | Cek kesehatan server dan konektivitas MongoDB Atlas (`ping`). |

### 2. Tulis Data (Ingest Unity / Hardware)
*Wajib menyertakan header:* `X-Api-Key: <API_KEY>`

| Method | Endpoint | Payload | Deskripsi |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/telemetri` | Array `[TelemetriCreate]` (1–10 item) | Simpan data telemetri batch dengan dedup `id_kirim`. |
| `POST` | `/api/event` | Object `EventCreate` | Simpan event mesin (*START, STOP, estop_tekan, estop_lepas*). |
| `POST` | `/api/botol` | Object `BotolCreate` | Simpan data hasil inspeksi botol selesai. |

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

sts Unity & Frontend MES (`tests/test_integration_unity_and_frontend.py`)
