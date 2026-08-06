"""
fix_names.py — Run once to assign each patient a unique name.
Usage: python fix_names.py
"""
from database import engine
from models import Patient
from sqlalchemy.orm import Session

# Large pool of realistic names — enough so all 31 patients get unique ones
NAMES = [
    "James Wilson", "Sarah Connor", "Michael Chang", "Emma Watson",
    "David Smith", "Linda Taylor", "Robert Johnson", "Emily Davis",
    "Thomas Harris", "Amanda Clarke", "Christopher Lee", "Jessica Brown",
    "Matthew Allen", "Patricia Moore", "Daniel White", "Nancy Lewis",
    "Richard Walker", "Karen Hall", "Charles Young", "Susan Martin",
    "Joseph Thompson", "Margaret Garcia", "Kevin Martinez", "Dorothy Anderson",
    "Brian Robinson", "Ruth Thomas", "Edward Jackson", "Lisa Hernandez",
    "Ronald Clark", "Sandra Lewis", "Anthony Scott", "Sharon King",
    "Kevin Wright", "Helen Torres", "Mark Nguyen", "Deborah Hill",
    "Donald Green", "Carolyn Adams", "George Baker", "Janet Nelson",
    "Paul Carter", "Catherine Mitchell", "Larry Perez", "Frances Roberts",
    "Joshua Turner", "Kathleen Phillips", "Kenneth Campbell", "Evelyn Parker",
    "Andrew Evans", "Alice Edwards", "Raymond Collins", "Donna Stewart",
    "Gregory Sanchez", "Martha Morris", "Frank Rogers", "Julie Reed",
    "Harold Cook", "Katherine Morgan", "Dennis Bell", "Theresa Murphy",
    "Walter Bailey", "Judith Rivera", "Peter Cooper", "Christine Richardson",
]

def fix_names():
    with Session(engine) as session:
        patients = session.query(Patient).order_by(Patient.subject_id).all()
        used_names = list(NAMES)
        for i, p in enumerate(patients):
            if i < len(used_names):
                p.name = used_names[i]
            else:
                p.name = f"Patient {p.subject_id}"
        session.commit()
        print(f"Updated {len(patients)} patients with unique names.")

if __name__ == "__main__":
    fix_names()
