# LAPORAN IMPLEMENTASI BACKEND REST API
**Pencatatan Data Digital Twin Mesin Pengisi Botol ke MongoDB Atlas**

---

## 1. Ringkasan Proyek

REST API ini dibangun menggunakan **Python 3.12**, **FastAPI**, **Pydantic v2**, dan **Motor (Async MongoDB Driver)** sebagai lapisan perantara (*middleware*) antara simulasi *digital twin* Unity dengan cluster database **MongoDB Atlas** (`liquidfilling`).

### Cakupan Implementasi
- **Fase 1 (Fondasi & Tulis)**: Endpoint penerimaan batch telemetri, pencatatan event kejadian mesin, pencatatan data botol selesai, serta endpoint health check konektivitas database.
- **Fase 3 (Baca & Ringkasan)**: Endpoint pembacaan konfigurasi mesin, status telemetri terkini, riwayat kejadian (*event*), serta agregasi ringkasan produksi (total botol, botol cacat, durasi siklus rata-rata, dan total durasi tombol darurat E-stop).

### Penyesuaian & Keputusan Dibanding Dokumen PRD
1. **Penyederhanaan Kunci API (`API_KEY`)**:
   Pada dokumen PRD awal dirancang pemetaan API Key per ID mesin (`MESIN_API_KEYS`). Mengingat hanya ada satu mesin fisik/digital twin (`mesin-01`), sistem disederhanakan menggunakan satu kunci API global via environment variable `API_KEY` yang diverifikasi menggunakan `secrets.compare_digest` untuk mencegah *timing attacks*.
2. **Validasi Eksistensi Mesin**:
   Validasi kepemilikan mesin disesuaikan menjadi validasi keberadaan dokumen `_id` pada collection `mesin`. Body request dengan `mesin_id` yang tidak terdaftar otomatis ditolak dengan **HTTP 400 Bad Request**.
3. **Peniadaan Modul Hardware ESP32 / MQTT**:
   Sesuai instruksi dan cakupan digital twin murni, modul ESP32, hardware, dan protokol MQTT (Fase 4) diabaikan. Namun, nilai enum `"esp32"` pada field `sumber` tetap dipertahankan pada skema Pydantic untuk kompatibilitas ke depan.
4. **Penambahan Field `pengguna` (Multi-Pengguna Digital Twin)**:
   Karena beberapa pengembang/operator menjalankan simulasi Unity masing-masing dan mengirim data ke mesin yang sama (`mesin-01`), setiap payload `telemetri`, `event`, dan `botol` diwajibkan membawa field `pengguna`. Nilai yang sah dibaca dari konfigurasi `PENGGUNA_VALID` (`gibral`, `haikal`, `alvin`, `naya`), dinormalisasi ke huruf kecil, dan jika di luar daftar akan ditolak **HTTP 400**.
5. **Rincian Per Pengguna pada Endpoint Ringkasan**:
   Endpoint `GET /api/v1/mesin/{id}/ringkasan` diperluas dengan field `rincian_pengguna` saat query parameter `pengguna` tidak diisi, menyajikan rincian statistik (botol, gagal, rata-rata siklus, durasi darurat) untuk setiap pengguna secara terpisah.
6. **Konfirmasi Jenis Event E-stop**:
   Sesuai konfirmasi, jenis event untuk penekanan dan pelepasan E-stop dibakukan menggunakan format snake_case Bahasa Indonesia: `estop_tekan` dan `estop_lepas`.

---

## 2. Daftar File yang Dibuat / Dikelola

| No | File | Deskripsi Singkat |
|:---|:---|:---|
| 1 | `app/main.py` | Entrypoint FastAPI, pengelolaan lifecycle koneksi MongoDB, exception handler validasi 400 Bahasa Indonesia, dan registrasi router. |
| 2 | `app/config.py` | Pengaturan konfigurasi aplikasi berbasis `pydantic-settings` (koneksi URI, API Key, daftar pengguna, konstanta e-stop). |
| 3 | `app/db.py` | Inisialisasi client asynchronous Motor MongoDB (`AsyncIOMotorClient`) dan penyedia dependency database aktif. |
| 4 | `app/auth.py` | Dependency autentikasi header `X-Api-Key` menggunakan `compare_digest`, proteksi baca, dan validasi eksistensi `mesin_id`. |
| 5 | `app/models.py` | Model data Pydantic v2 untuk payload tulis, validasi timestamp ISO 8601 UTC aware, normalisasi pengguna, enum, dan model respons. |
| 6 | `app/routers/tulis.py` | Endpoint POST `/telemetri` (batch 1–10 + dedup API), `/event` (idempoten), dan `/botol` (idempoten). |
| 7 | `app/routers/baca.py` | Endpoint GET `/mesin/{id}`, `/mesin/{id}/status`, `/mesin/{id}/ringkasan` (agregasi & durasi e-stop), dan `/mesin/{id}/event`. |
| 8 | `app/routers/health.py` | Endpoint GET `/health` dan `/api/v1/health` untuk pemeriksaan status liveness server dan ping database MongoDB. |
| 9 | `scripts/seed_contoh.py` | Script CLI pengiriman data contoh (telemetri, event, botol) ke server REST API via HTTP client. |
| 10 | `tests/conftest.py` | Konfigurasi pytest, fixture AsyncClient httpx, dan isolasi database test `liquidfilling_test`. |
| 11 | `tests/test_auth.py` | Pengujian keamanan header `X-Api-Key`, penolakan 401 saat key hilang/salah, dan toggle proteksi baca. |
| 12 | `tests/test_validation.py` | Pengujian penolakan 400 untuk field wajib hilang, enum salah, timestamp naive tanpa timezone, dan pengguna tidak sah. |
| 13 | `tests/test_tulis.py` | Pengujian batch telemetri (1-10 data), deduplikasi `id_kirim`, timestamp `diterima`, dan idempotensi event/botol. |
| 14 | `tests/test_baca.py` | Pengujian GET konfigurasi mesin, status telemetri terakhir, filter pengguna, dan verifikasi perhitungan manual ringkasan. |
| 15 | `tests/test_health.py` | Pengujian endpoint health check saat database terhubung. |
| 16 | `requirements.txt` | Daftar dependensi paket Python proyek (FastAPI, Uvicorn, Motor, Pydantic, Pytest, Mongomock-Motor, dll). |
| 17 | `.env.example` | Template variabel lingkungan aman tanpa nilai rahasia untuk panduan deployment. |
| 18 | `.env` | File konfigurasi lokal aktif dengan kredensial Atlas (terproteksi oleh `.gitignore`). |
| 19 | `.gitignore` | Konfigurasi pengabaian file Git untuk mencegah kebocoran kredensial, cache bytecode, dan file temporary. |
| 20 | `pytest.ini` | Konfigurasi runner pengujian pytest dengan dukungan asynchronous (`asyncio_mode = auto`). |
| 21 | `Dockerfile` | Definisi kontainerisasi multi-stage berbasis `python:3.12-slim` untuk standarisasi deployment server. |
| 22 | `setup_mongodb.py` | Script inisialisasi skema validator $jsonSchema dan indeks awal database `liquidfilling` di MongoDB Atlas. |
| 23 | `README.md` | Dokumentasi lengkap arsitektur, panduan instalasi, pengujian, deployment Docker, dan contoh perintah cURL. |
| 24 | `LAPORAN.md` | Laporan evaluasi teknis backend lengkap, transparansi pengujian, dan instruksi operasional VPS. |

---

## 3. Daftar Endpoint dan Contoh Request / Response Singkat

### A. Endpoint Tulis (Wajib Header `X-Api-Key`)
1. **`POST /api/v1/telemetri`**
   - **Request**: Array 1–10 dokumen telemetri.
     ```json
     [
       {
         "waktu": "2026-10-29T10:00:00Z",
         "mesin_id": "mesin-01",
         "sesi_id": "gibral-20261029-1000",
         "pengguna": "gibral",
         "id_kirim": "tel-01",
         "mode": "Berjalan",
         "darurat": false,
         "mcb": {"utama": true, "mesin": true, "kontrol": true, "lampu": true},
         "sudut_turret_deg": 36.0,
         "botol_selesai": 10,
         "isi_kotak": 10,
         "sisa_peti": 110,
         "gpio": {"step": true, "dir": false, "en": true, "pompa": true, "buzzer": false, "ir": true, "start": false, "limit": false}
       }
     ]
     ```
   - **Response (HTTP 201)**:
     ```json
     {"status": "sukses", "pesan": "1 data tersimpan, 0 duplikat diabaikan", "tersimpan": 1, "duplikat_diabaikan": 0}
     ```

2. **`POST /api/v1/event`**
   - **Request**: 1 dokumen kejadian mesin.
     ```json
     {
       "waktu": "2026-10-29T10:05:00Z",
       "mesin_id": "mesin-01",
       "sesi_id": "haikal-20261029-1005",
       "pengguna": "haikal",
       "id_kirim": "ev-01",
       "jenis": "estop_tekan",
       "mode_sebelum": "Berjalan",
       "mode_sesudah": "Darurat",
       "sumber": "pemain",
       "pesan": "Tombol e-stop ditekan"
     }
     ```
   - **Response (HTTP 201)**:
     ```json
     {"status": "sukses", "pesan": "event berhasil disimpan", "id_kirim": "ev-01", "tersimpan": true, "id": "6720f123456789abcdef0123"}
     ```
   - *Kirim ulang id_kirim sama*: `{"status": "sukses", "pesan": "duplikat diabaikan", "id_kirim": "ev-01", "tersimpan": false, "id": null}`

3. **`POST /api/v1/botol`**
   - **Request**: 1 dokumen botol selesai.
     ```json
     {
       "mesin_id": "mesin-01",
       "sesi_id": "alvin-20261029-1010",
       "pengguna": "alvin",
       "id_kirim": "btl-01",
       "nomor": 1,
       "slot": 2,
       "waktu_masuk": "2026-10-29T10:00:00Z",
       "waktu_keluar": "2026-10-29T10:00:15Z",
       "level_isi": 0.95,
       "bertutup": true,
       "status": "OK"
     }
     ```
   - **Response (HTTP 201)**:
     ```json
     {"status": "sukses", "pesan": "botol berhasil disimpan", "id_kirim": "btl-01", "tersimpan": true, "id": "6720f4567890abcdef123456"}
     ```

### B. Endpoint Baca & Pemantauan
4. **`GET /api/v1/mesin/{id}`**
   - **Response (HTTP 200)**: Dokumen konfigurasi mesin dari collection `mesin`.

5. **`GET /api/v1/mesin/{id}/status?pengguna=gibral`**
   - **Response (HTTP 200)**: Dokumen telemetri terakhir dari mesin (atau milik pengguna tertentu jika difilter).

6. **`GET /api/v1/mesin/{id}/ringkasan?dari=&sampai=&sesi_id=&pengguna=`**
   - **Response (HTTP 200)**:
     ```json
     {
       "mesin_id": "mesin-01",
       "sesi_id": null,
       "pengguna": null,
       "rentang": {"dari": null, "sampai": null},
       "jumlah_botol": 45,
       "botol_gagal": 3,
       "rata_rata_waktu_siklus_detik": 15.25,
       "total_durasi_darurat_detik": 60.0,
       "rincian_pengguna": {
         "gibral": {"jumlah_botol": 30, "botol_gagal": 1, "rata_rata_waktu_siklus_detik": 14.8, "total_durasi_darurat_detik": 40.0},
         "haikal": {"jumlah_botol": 15, "botol_gagal": 2, "rata_rata_waktu_siklus_detik": 16.1, "total_durasi_darurat_detik": 20.0}
       }
     }
     ```

7. **`GET /api/v1/mesin/{id}/event?jenis=&dari=&sampai=&pengguna=&limit=100`**
   - **Response (HTTP 200)**: Array riwayat kejadian terurut menurun (*newest first*).

8. **`GET /api/v1/health` & `GET /health`**
   - **Response (HTTP 200)**:
     ```json
     {"status": "ok", "database": "terhubung", "waktu": "2026-10-29T10:30:00.123456+00:00", "detail": null}
     ```

---

## 4. Variabel Environment yang Dibutuhkan

| Nama Variabel | Tipe Data | Nilai Default | Fungsi / Penjelasan |
|:---|:---|:---|:---|
| `MONGODB_URI` | String | `mongodb://localhost:27017` | Connection string MongoDB Atlas (contoh: `mongodb+srv://...`). Dijaga ketat dan tidak pernah dicetak ke log. |
| `MONGODB_DB_NAME` | String | `liquidfilling` | Nama database MongoDB target pada cluster. |
| `API_KEY` | String | `rahasia-api-key` | Kunci autentikasi tunggal yang wajib dikirim klien pada header `X-Api-Key` untuk endpoint tulis. |
| `REQUIRE_KEY_FOR_READ` | Boolean | `false` | Menentukan apakah endpoint GET baca mewajibkan header `X-Api-Key` (`true`) atau terbuka untuk publik (`false`). |
| `PENGGUNA_VALID` | String | `gibral,haikal,alvin,naya` | Daftar identitas pengguna yang diizinkan, dipisahkan oleh tanda koma. |
| `EVENT_JENIS_ESTOP_TEKAN` | String | `estop_tekan` | Nilai string jenis kejadian saat tombol E-stop ditekan (untuk perhitungan durasi darurat). |
| `EVENT_JENIS_ESTOP_LEPAS` | String | `estop_lepas` | Nilai string jenis kejadian saat tombol E-stop dilepas / direset kembali. |
| `HOST` | String | `0.0.0.0` | Host IP pengikatan server Uvicorn. |
| `PORT` | Integer | `8000` | Port TCP layanan HTTP server. |
| `DEBUG` | Boolean | `false` | Flag mode debug pada FastAPI. |

---

## 5. Asumsi yang Diambil dan Pertanyaan Terbuka

### Asumsi yang Diambil:
1. **Format Jenis Event E-stop**: Menggunakan snake_case Bahasa Indonesia `estop_tekan` dan `estop_lepas` sesuai konfirmasi pengguna.
2. **Kalkulasi Durasi E-stop Mengambang**: Jika terjadi kejadian `estop_tekan` dan sesi berakhir atau belum menerima kejadian `estop_lepas`, durasi dihitung dari waktu penekanan hingga parameter `sampai` (atau waktu UTC server sekarang jika `sampai` tidak didefinisikan).
3. **Penyatuan Metrik Multi-Sesi**: Setiap pengguna memiliki `sesi_id` independen. Total durasi darurat dihitung dengan menjumlahkan interval darurat berpasangan di setiap sesi, lalu di-clip ke rentang filter waktu `[dari, sampai]`.
4. **Normalisasi String Pengguna**: String `pengguna` otomatis dibersihkan dari spasi berlebih dan diubah menjadi huruf kecil (`.strip().lower()`) sebelum validasi dan penyimpanan.
5. **Ekstraksi Field Tambahan**: Model Pydantic v2 disetel `extra="allow"` sehingga field eksperimental baru dari Unity diizinkan tanpa merusak kompatibilitas skema.

### Pertanyaan Terbuka (Open Questions):
1. *Pembagian Shift Kerja Otomatis*: Apakah sistem memerlukan filter preset shift kerja otomatis (misal: Shift 1: 07.00–15.00, Shift 2: 15.00–23.00 WIB) langsung pada endpoint ringkasan tanpa perlu mengisi query parameter `dari` dan `sampai` secara manual?
2. *Konversi Volume Cairan*: Berapa volume botol fisik sebenarnya (dalam mililiter), jika nanti data agregasi ringkasan ingin menyajikan total liter cairan yang terisi selain persentase `level_isi` (0.0–1.0)?
3. *Manajemen Akun Pengguna Tingkat Lanjut*: Apakah di masa depan diperlukan token JWT atau API Key terpisah per pengguna jika sistem diakses oleh banyak praktikan di luar 4 pengguna yang telah terdaftar?

---

## 6. Hasil Pengujian dan Evaluasi

### A. Pengujian Unit & Integrasi Otomatis (Pytest)
Perintah yang dijalankan:
```bash
.\.venv\Scripts\pytest.exe -v
```

Hasil Pengujian:
- **Total Test Cases**: **24 passed** (0 failed, 0 error).
- **Waktu Eksekusi**: 0.38 detik.
- Rincian modul pengujian:
  - `tests/test_auth.py` (4 tests): Verifikasi penolakan 401 saat key tidak ada/salah, verifikasi akses GET publik, dan toggle `REQUIRE_KEY_FOR_READ=True`.
  - `tests/test_validation.py` (7 tests): Penolakan 400 untuk field wajib hilang, enum salah, timestamp naive tanpa zona waktu, pengguna tidak sah, normalisasi pengguna case-insensitive, penolakan mesin_id tidak terdaftar, dan kelolosan extra fields.
  - `tests/test_tulis.py` (7 tests): Penyimpanan telemetri batch 1-10, penolakan batch kosong dan >10 data, deduplikasi `id_kirim` telemetri di API, verifikasi server timestamp `diterima`, serta idempotensi event & botol saat `id_kirim` dikirim ulang.
  - `tests/test_baca.py` (5 tests): GET mesin, status terakhir per pengguna, pagination & limit event, verifikasi hitungan manual ringkasan (botol, gagal, rata-rata siklus, durasi darurat, rincian pengguna), dan kalkulasi E-stop tanpa lepas.
  - `tests/test_health.py` (1 test): Verifikasi status health check API dan koneksi database.

### B. Pengujian Live End-to-End (`scripts/seed_contoh.py`)
Perintah yang dijalankan:
```bash
.\.venv\Scripts\python.exe scripts/seed_contoh.py
```

Hasil Live:
- Berhasil terhubung ke server Uvicorn lokal dan cluster **MongoDB Atlas** (`liquidfilling`).
- Mengirimkan 5 dokumen telemetri, 3 event kejadian (START, estop_tekan, estop_lepas), dan 3 data botol (status OK dan TIDAK_PENUH).
- Pengujian eksekusi kedua membuktikan bahwa **seluruh data duplikat berhasil diabaikan secara idempoten** (HTTP 201 dengan pesan *"duplikat diabaikan"*).
- Ringkasan produksi live membaca metrik nyata: 3 botol, 1 botol gagal, durasi siklus 17.67 detik, dan durasi darurat 15 detik dengan rincian pengguna Gibral dan Haikal yang presisi.

### C. Hal yang BELUM Diuji (Transparansi Teknis)
Laporan ini secara jujur mencatat batasan pengujian yang belum dieksekusi:
1. **Uji Beban & Konkurensi Skala Besar (*Stress / Load Testing*)**:
   Belum diuji ketahanan throughput tinggi (misal: 1.000–5.000 request per detik secara simultan menggunakan tools seperti Locust atau k6) untuk melihat batas saturasi thread pool Motor dan batas *connection pool* MongoDB Atlas tier M0/Shared.
2. **Koneksi Jaringan Tidak Stabil (*Network Partition / High Latency Spike*)**:
   Belum diuji bagaimana perilaku antrean driver saat koneksi internet ke Atlas mengalami *timeout* berkepanjangan (meskipun simulasi antrean lokal di sisi Unity telah dirancang di PRD F-04).
3. **Terminasi SSL / TLS Langsung**:
   Pengujian lokal dilakukan via HTTP polos (port 8000). Enkripsi HTTPS belum diuji langsung di level aplikasi karena praktik terbaik produksi adalah mendelegasikan terminasi SSL kepada Reverse Proxy (Nginx/Traefik).
4. **Izin Database Atlas untuk Database Test Baru**:
   User kredensial Atlas `laskar` memiliki izin readWrite terbatas pada database `liquidfilling`. User tersebut tidak memiliki hak membuat database sembarang seperti `liquidfilling_test` di cluster Atlas. Oleh karena itu, pengujian automated suite `liquidfilling_test` menggunakan library in-memory `mongomock-motor` agar tidak mengotori atau menyentuh database produksi `liquidfilling`.

---

## 7. Panduan Menjalankan Lokal dan Deploy ke VPS

### A. Panduan Menjalankan di Komputer Lokal

1. **Clone repositori dan pasang dependensi**:
   ```powershell
   git clone <repo-url>
   cd FillingMachine
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
2. **Konfigurasi Environment Variable**:
   Salin `.env.example` menjadi `.env` dan masukkan connection string MongoDB Atlas Anda.
3. **Jalankan Server Uvicorn**:
   ```powershell
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
4. **Akses Dokumentasi API**:
   Buka peramban di `http://localhost:8000/docs`.
5. **Kirim Data Contoh**:
   Buka terminal terpisah dan jalankan:
   ```powershell
   python scripts/seed_contoh.py
   ```

---

### B. Panduan Deploy ke VPS (Ubuntu / Debian Linux)

#### Opsi 1: Menggunakan Docker & Docker Compose (Direkomendasikan)
1. **Salin repositori ke VPS**:
   ```bash
   git clone <repo-url> /opt/filling-machine
   cd /opt/filling-machine
   cp .env.example .env
   nano .env  # Masukkan MONGODB_URI dan API_KEY produksi
   ```
2. **Build dan Jalankan Container**:
   ```bash
   docker build -t filling-machine-api:latest .
   docker run -d \
     --name filling-machine-api \
     --restart unless-stopped \
     -p 127.0.0.1:8000:8000 \
     --env-file .env \
     filling-machine-api:latest
   ```

#### Opsi 2: Menggunakan Systemd Service & Nginx Reverse Proxy
1. **Buat Systemd Service**:
   Buat file `/etc/systemd/system/filling-api.service`:
   ```ini
   [Unit]
   Description=Liquid Filling Machine FastAPI Backend
   After=network.target

   [Service]
   User=www-data
   Group=www-data
   WorkingDirectory=/opt/filling-machine
   EnvironmentFile=/opt/filling-machine/.env
   ExecStart=/opt/filling-machine/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```
   Aktifkan service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now filling-api
   ```

2. **Konfigurasi Nginx Reverse Proxy & SSL (Certbot)**:
   Buat file `/etc/nginx/sites-available/filling-api`:
   ```nginx
   server {
       server_name api.fillingmachine.domainkamu.com;

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }
   }
   ```
   Aktifkan site dan pasang SSL gratis Let's Encrypt:
   ```bash
   sudo ln -s /etc/nginx/sites-available/filling-api /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl reload nginx
   sudo certbot --nginx -d api.fillingmachine.domainkamu.com
   ```
3. **Verifikasi Layanan di VPS**:
   ```bash
   curl -X GET "https://api.fillingmachine.domainkamu.com/api/v1/health"
   ```

