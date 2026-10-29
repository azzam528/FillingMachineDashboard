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

