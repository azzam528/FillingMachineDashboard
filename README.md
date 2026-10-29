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

