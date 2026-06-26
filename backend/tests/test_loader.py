import pytest
import sys

sys.path.insert(0, ".")

from backend.app.loader import MIMICLoader

DATA_PATH = "data/mimic-demo"

NORTH_STAR_ENCOUNTERS = [
    24181354,
    28258130,
    22987108,
    22205327,
    26529390
]

def test_loader_returns_encounter():

    loader = MIMICLoader(DATA_PATH)

    enc = loader.load_encounter(NORTH_STAR_ENCOUNTERS[0])

    assert enc.hadm_id == NORTH_STAR_ENCOUNTERS[0]

    assert enc.subject_id > 0

    assert len(enc.diagnoses) > 0, \
        "every admission should have at least one diagnosis"

    assert len(enc.lab_results) > 0

    print(f"\nLoaded encounter: {enc.hadm_id}")

    print(f"Diagnoses: {len(enc.diagnoses)}")

    print(f"Labs: {len(enc.lab_results)}")

    print(f"Meds: {len(enc.medications)}")

    print(
        f"Notes: {len(enc.notes)} "
        f"({'available' if enc.has_notes() else 'not yet'})"
    )

    print(
        f"Primary dx: "
        f"{enc.diagnoses[0].description if enc.diagnoses else 'none'}"
    )