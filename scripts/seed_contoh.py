"""Script untuk mengirim data contoh ke REST API via HTTP (bukan langsung ke database).

Cara pakai:
    python scripts/seed_contoh.py
    # atau dengan opsi URL/kunci khusus:
    python scripts/seed_contoh.py --url http://127.0.0.1:8000 --api-key <kunci>
"""

import argparse
import os
import sys
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
import httpx

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="Seed data contoh ke REST API Mesin Pengisi Botol")
    parser.add_argument(
        "--url",
        default=os.environ.get("API_BASE_URL", "http://127.0.0.1:8000"),
        help="Base URL API (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("API_KEY", "Sj0ETn-bp1lMiGASdQfdW5WiGEoIU2XskRp41IKy9vU"),
        help="API Key untuk header X-Api-Key",
    )
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    headers = {
        "X-Api-Key": args.api_key,
        "Content-Type": "application/json",
    }

    print(f"==================================================")
    print(f"Menjalankan Seeding Data Contoh ke API: {base_url}")
    print(f"==================================================")

    with httpx.Client(base_url=base_url, timeout=10.0) as client:
        # 1. Cek Health
        print("\n[1/6] Memeriksa /health ...")
        try:
            r_health = client.get("/api/v1/health")
            print(f"  Status: {r_health.status_code} - {r_health.json()}")
        except Exception as e:
            print(f"  [GAGAL TERHUBUNG] Pastikan server API sedang berjalan: {e}")
            return 1

        now = datetime.now(timezone.utc)

        # 2. Kirim Data Telemetri (Batch 5 data)
        print("\n[2/6] Mengirim batch 5 dokumen telemetri (Gibral & Haikal) ...")
        telemetri_batch = []
        for i in range(5):
            t_waktu = (now - timedelta(seconds=50 - i * 10)).isoformat()
            user = "gibral" if i < 3 else "haikal"
            telemetri_batch.append({
                "waktu": t_waktu,
                "mesin_id": "mesin-01",
                "sesi_id": f"{user}-20261029-1000",
                "pengguna": user,
                "id_kirim": f"seed-tel-{i+1}",
                "mode": "Berjalan",
                "darurat": False,
                "mcb": {"utama": True, "mesin": True, "kontrol": True, "lampu": True},
                "tahap": 2,
                "langkah": i + 1,
                "sudut_turret_deg": float((i * 36) % 360),
                "botol_selesai": i,
                "isi_kotak": i,
                "sisa_peti": 120 - i,
                "operator_tugas": "memantau turret",
                "gpio": {
                    "step": True, "dir": False, "en": True,
                    "pompa": True, "buzzer": False, "ir": True,
                    "start": False, "limit": False
                },
            })

        r_tel = client.post("/api/v1/telemetri", headers=headers, json=telemetri_batch)
        print(f"  Status: {r_tel.status_code} - {r_tel.text}")

        # 3. Kirim Event START & E-stop
        print("\n[3/6] Mengirim event kejadian (START, estop_tekan, estop_lepas) ...")
        events = [
            {
                "waktu": (now - timedelta(seconds=60)).isoformat(),
                "mesin_id": "mesin-01",
                "sesi_id": "gibral-20261029-1000",
                "pengguna": "gibral",
                "id_kirim": "seed-ev-start-1",
                "jenis": "START",
                "mode_sebelum": "Siap",
                "mode_sesudah": "Berjalan",
                "sumber": "pemain",
                "pesan": "Simulasi dimulai oleh pemain Gibral",
            },
            {
                "waktu": (now - timedelta(seconds=40)).isoformat(),
                "mesin_id": "mesin-01",
                "sesi_id": "gibral-20261029-1000",
                "pengguna": "gibral",
                "id_kirim": "seed-ev-estop-tekan-1",
                "jenis": "estop_tekan",
                "mode_sebelum": "Berjalan",
                "mode_sesudah": "Darurat",
                "sumber": "pemain",
                "pesan": "E-stop ditekan saat botol miring",
            },
            {
                "waktu": (now - timedelta(seconds=25)).isoformat(),
                "mesin_id": "mesin-01",
                "sesi_id": "gibral-20261029-1000",
                "pengguna": "gibral",
                "id_kirim": "seed-ev-estop-lepas-1",
                "jenis": "estop_lepas",
                "mode_sebelum": "Darurat",
                "mode_sesudah": "Siap",
                "sumber": "pemain",
                "pesan": "E-stop direset kembali oleh pemain",
            },
        ]
        for ev in events:
            r_ev = client.post("/api/v1/event", headers=headers, json=ev)
            print(f"  POST /event ({ev['jenis']}): {r_ev.status_code} - {r_ev.json().get('pesan')}")

        # 4. Kirim Data Botol Selesai
        print("\n[4/6] Mengirim data botol selesai diproses ...")
        botol_samples = [
            {
                "mesin_id": "mesin-01",
                "sesi_id": "gibral-20261029-1000",
                "pengguna": "gibral",
                "id_kirim": "seed-btl-01",
                "nomor": 1,
                "slot": 1,
                "waktu_masuk": (now - timedelta(seconds=55)).isoformat(),
                "waktu_isi_mulai": (now - timedelta(seconds=50)).isoformat(),
                "waktu_isi_selesai": (now - timedelta(seconds=45)).isoformat(),
                "waktu_tutup": (now - timedelta(seconds=42)).isoformat(),
                "waktu_keluar": (now - timedelta(seconds=40)).isoformat(),
                "level_isi": 1.0,
                "bertutup": True,
                "status": "OK",
            },
            {
                "mesin_id": "mesin-01",
                "sesi_id": "gibral-20261029-1000",
                "pengguna": "gibral",
                "id_kirim": "seed-btl-02",
                "nomor": 2,
                "slot": 2,
                "waktu_masuk": (now - timedelta(seconds=40)).isoformat(),
                "waktu_isi_mulai": (now - timedelta(seconds=35)).isoformat(),
                "waktu_isi_selesai": (now - timedelta(seconds=30)).isoformat(),
                "waktu_tutup": (now - timedelta(seconds=27)).isoformat(),
                "waktu_keluar": (now - timedelta(seconds=20)).isoformat(),
                "level_isi": 0.65,
                "bertutup": True,
                "status": "TIDAK_PENUH",
            },
            {
                "mesin_id": "mesin-01",
                "sesi_id": "haikal-20261029-1005",
                "pengguna": "haikal",
                "id_kirim": "seed-btl-03",
                "nomor": 1,
                "slot": 3,
                "waktu_masuk": (now - timedelta(seconds=20)).isoformat(),
                "waktu_isi_mulai": (now - timedelta(seconds=16)).isoformat(),
                "waktu_isi_selesai": (now - timedelta(seconds=10)).isoformat(),
                "waktu_tutup": (now - timedelta(seconds=7)).isoformat(),
                "waktu_keluar": (now - timedelta(seconds=2)).isoformat(),
                "level_isi": 0.99,
                "bertutup": True,
                "status": "OK",
            },
        ]
        for b in botol_samples:
            r_b = client.post("/api/v1/botol", headers=headers, json=b)
            print(f"  POST /botol (No.{b['nomor']}, Status:{b['status']}): {r_b.status_code} - {r_b.json().get('pesan')}")

        # 5. Cek Status Telemetri Terakhir via GET
        print("\n[5/6] Membaca telemetri terakhir (GET /api/v1/mesin/mesin-01/status) ...")
        r_status = client.get("/api/v1/mesin/mesin-01/status")
        print(f"  Status: {r_status.status_code} - Pengguna: {r_status.json().get('pengguna')}, Waktu: {r_status.json().get('waktu')}")

        # 6. Cek Ringkasan Produksi via GET
        print("\n[6/6] Membaca ringkasan produksi (GET /api/v1/mesin/mesin-01/ringkasan) ...")
        r_ringkasan = client.get("/api/v1/mesin/mesin-01/ringkasan")
        print(f"  Status: {r_ringkasan.status_code}")
        print(f"  Hasil Ringkasan: {r_ringkasan.json()}")

    print("\n[OK] Selesai! Seeding data contoh berhasil dijalankan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
