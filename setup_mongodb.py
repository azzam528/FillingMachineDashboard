"""Setup MongoDB Atlas: Pencatatan Data Mesin Pengisi Botol (database: liquidfilling).

Cara pakai:
    pip install "pymongo[srv]"
    export MONGODB_URI="mongodb+srv://<user>:<password>@<cluster>.mongodb.net/"
    python setup_mongodb.py

Aman dijalankan berulang: collection/index yang sudah ada dilewati,
dokumen mesin di-upsert.
"""

import os
import sys

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import PyMongoError

DB_NAME = "liquidfilling"
TTL_TELEMETRI_DETIK = 30 * 24 * 60 * 60  # 30 hari

MODE = ["Mati", "Siap", "Berjalan", "Darurat", None]
INT = ["int", "long"]
NUM = ["int", "long", "double"]


def validator(schema: dict) -> dict:
    return {"$jsonSchema": {"bsonType": "object", **schema}}


MESIN = validator(
    {
        "required": [
            "_id",
            "nama",
            "jumlah_slot",
            "sudut_per_slot_deg",
            "stasiun",
            "kapasitas_kotak",
            "kapasitas_peti",
        ],
        "properties": {
            "_id": {"bsonType": "string"},
            "nama": {"bsonType": "string"},
            "jumlah_slot": {"bsonType": INT, "minimum": 1},
            "sudut_per_slot_deg": {"bsonType": NUM},
            "stasiun": {
                "bsonType": "object",
                "required": ["infeed", "isi", "capping", "buang"],
                "properties": {
                    k: {"bsonType": NUM} for k in ("infeed", "isi", "capping", "buang")
                },
            },
            "kapasitas_kotak": {"bsonType": INT, "minimum": 1},
            "kapasitas_peti": {"bsonType": INT, "minimum": 1},
            "pin_gpio": {"bsonType": "object"},
        },
    }
)

EVENT = validator(
    {
        "required": ["waktu", "mesin_id", "sesi_id", "jenis", "sumber"],
        "properties": {
            "waktu": {"bsonType": "date"},
            "diterima": {"bsonType": "date"},
            "mesin_id": {"bsonType": "string"},
            "sesi_id": {"bsonType": "string"},
            "id_kirim": {"bsonType": "string"},
            "jenis": {"bsonType": "string"},
            "mode_sebelum": {"enum": MODE},
            "mode_sesudah": {"enum": MODE},
            "pesan": {"bsonType": ["string", "null"]},
            "sumber": {"enum": ["pemain", "sistem", "operator", "esp32"]},
            "detail": {"bsonType": ["object", "null"]},
        },
    }
)

BOTOL = validator(
    {
        "required": [
            "mesin_id",
            "sesi_id",
            "nomor",
            "slot",
            "waktu_masuk",
            "waktu_keluar",
            "level_isi",
            "bertutup",
            "status",
        ],
        "properties": {
            "mesin_id": {"bsonType": "string"},
            "sesi_id": {"bsonType": "string"},
            "id_kirim": {"bsonType": "string"},
            "diterima": {"bsonType": "date"},
            "nomor": {"bsonType": INT, "minimum": 1},
            "slot": {"bsonType": INT, "minimum": 0},
            "waktu_masuk": {"bsonType": "date"},
            "waktu_isi_mulai": {"bsonType": ["date", "null"]},
            "waktu_isi_selesai": {"bsonType": ["date", "null"]},
            "waktu_tutup": {"bsonType": ["date", "null"]},
            "waktu_keluar": {"bsonType": "date"},
            "level_isi": {"bsonType": NUM, "minimum": 0, "maximum": 1},
            "bertutup": {"bsonType": "bool"},
            "status": {"enum": ["OK", "TIDAK_PENUH", "TANPA_TUTUP"]},
        },
    }
)

MESIN_01 = {
    "nama": "Mesin Pengisi Botol Rotary 10 Slot (Digital Twin)",
    "jumlah_slot": 10,
    "sudut_per_slot_deg": 36,
    "stasiun": {"infeed": 36, "isi": 180, "capping": 144, "buang": 108},
    "kapasitas_kotak": 30,
    "kapasitas_peti": 12,
    # Isi nomor pin sebenarnya nanti; None = belum ditetapkan
    "pin_gpio": {
        k: None
        for k in ("step", "dir", "en", "pompa", "buzzer", "ir", "start", "limit")
    },
}


def buat(db, nama, **opsi):
    if nama in db.list_collection_names():
        print(f"• collection {nama} sudah ada")
        return
    db.create_collection(nama, **opsi)
    print(f"✔ collection {nama} dibuat")


def main() -> int:
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        print(
            "Set dulu environment variable MONGODB_URI (connection string Atlas).",
            file=sys.stderr,
        )
        return 1

    client = MongoClient(uri, serverSelectionTimeoutMS=10000)
    db = client[DB_NAME]
    try:
        client.admin.command("ping")

        # 1. mesin
        buat(
            db,
            "mesin",
            validator=MESIN,
            validationLevel="strict",
            validationAction="error",
        )
        db.mesin.update_one(
            {"_id": "mesin-01"}, {"$setOnInsert": MESIN_01}, upsert=True
        )
        print("✔ dokumen mesin-01 siap")

        # 2. telemetri: time series, TTL 30 hari.
        # Time series tidak mendukung validator maupun unique index, jadi
        # validasi (F-05) dan dedup id_kirim dilakukan di API.
        buat(
            db,
            "telemetri",
            timeseries={
                "timeField": "waktu",
                "metaField": "mesin_id",
                "granularity": "seconds",
            },
            expireAfterSeconds=TTL_TELEMETRI_DETIK,
        )

        # 3. event
        buat(
            db,
            "event",
            validator=EVENT,
            validationLevel="strict",
            validationAction="error",
        )
        db.event.create_index(
            [("mesin_id", ASCENDING), ("waktu", DESCENDING)], name="mesin_waktu"
        )
        db.event.create_index(
            [("mesin_id", ASCENDING), ("sesi_id", ASCENDING)], name="mesin_sesi"
        )
        db.event.create_index(
            [("id_kirim", ASCENDING)],
            name="id_kirim_unik",
            unique=True,
            partialFilterExpression={"id_kirim": {"$type": "string"}},
        )

        # 4. botol
        buat(
            db,
            "botol",
            validator=BOTOL,
            validationLevel="strict",
            validationAction="error",
        )
        db.botol.create_index(
            [("mesin_id", ASCENDING), ("waktu_keluar", DESCENDING)],
            name="mesin_waktu_keluar",
        )
        db.botol.create_index(
            [("mesin_id", ASCENDING), ("sesi_id", ASCENDING)], name="mesin_sesi"
        )
        db.botol.create_index(
            [("id_kirim", ASCENDING)],
            name="id_kirim_unik",
            unique=True,
            partialFilterExpression={"id_kirim": {"$type": "string"}},
        )

        print(f"\nCollection di database '{DB_NAME}':")
        for info in db.list_collections():
            print(
                f"  - {info['name']}"
                + (" (time series)" if info.get("type") == "timeseries" else "")
            )
        return 0
    except PyMongoError as e:
        print(f"Gagal: {e}", file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
