
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

# CARDIOLOGY-SPECIFIC CONSTANTS
# Target Cardiology Department only (will extend to other depts later)

# Lab itemids that are CRITICAL for cardiology accuracy
# Source: MIMIC d_labitems.csv verified against real data
CARDIOLOGY_CRITICAL_LAB_ITEMIDS = frozenset({
    # Troponin (myocardial injury marker — THE most important cardiac lab)
    51002, 51003, 52642,
    # BNP / NT-proBNP (heart failure severity)
    50963, 51921,
    # CK-MB (myocardial infarction)
    50908, 50911, 51580,
    # PT / INR (anticoagulation monitoring — warfarin, heparin)
    51237, 51675,
    # Potassium (arrhythmia risk — must be >3.5 for cardiac patients)
    50822, 52452,
    # Magnesium (arrhythmia risk — low Mg causes VF)
    50960,
    # Creatinine / BUN (renal function — contrast nephropathy, ACE dosing)
    50912, 52024, 51006,
    # Lactate (cardiogenic shock severity)
    50813, 52442,
    # Hemoglobin / Hematocrit (anemia worsens cardiac demand)
    50811, 50810,
    # Glucose (stress hyperglycemia in ACS)
    50809, 50931, 52027,
    # Sodium (hyponatremia in heart failure — poor prognosis marker)
    50824, 52455,
    # Chloride
    50806, 52434,
    # Bicarbonate (acid-base in cardiogenic shock)
    50803, 52038,
})

# Lab labels to catch by name (some itemids vary across MIMIC versions)
CARDIOLOGY_CRITICAL_LAB_KEYWORDS = frozenset({
    'troponin', 'ntprobnp', 'bnp', 'natriuretic',
    'ck-mb', 'creatine kinase, mb',
    'inr', 'prothrombin',
    'potassium', 'magnesium', 'lactate',
    'creatinine', 'hemoglobin', 'hematocrit',
})

# Cardiac medication classification
# Each key = category name, value = keywords to match against drug name
CARDIAC_MED_CATEGORIES: dict[str, frozenset] = {
    'antiplatelet': frozenset({
        'aspirin', 'clopidogrel', 'plavix', 'ticagrelor', 'brilinta',
        'prasugrel', 'effient', 'ticlopidine',
    }),
    'anticoagulant': frozenset({
        'heparin', 'warfarin', 'coumadin', 'enoxaparin', 'lovenox',
        'rivaroxaban', 'xarelto', 'apixaban', 'eliquis',
        'dabigatran', 'pradaxa', 'fondaparinux', 'bivalirudin',
    }),
    'beta_blocker': frozenset({
        'metoprolol', 'carvedilol', 'atenolol', 'bisoprolol',
        'labetalol', 'propranolol', 'nebivolol',
    }),
    'ace_arb': frozenset({
        'lisinopril', 'enalapril', 'ramipril', 'captopril', 'perindopril',
        'losartan', 'valsartan', 'irbesartan', 'telmisartan', 'olmesartan',
        'sacubitril',  # entresto = sacubitril/valsartan
    }),
    'statin': frozenset({
        'atorvastatin', 'rosuvastatin', 'simvastatin', 'pravastatin',
        'lovastatin', 'fluvastatin', 'pitavastatin',
    }),
    'diuretic': frozenset({
        'furosemide', 'lasix', 'torsemide', 'bumetanide', 'hydrochlorothiazide',
        'chlorthalidone', 'metolazone', 'spironolactone', 'eplerenone',
    }),
    'antiarrhythmic': frozenset({
        'amiodarone', 'flecainide', 'sotalol', 'mexiletine', 'lidocaine',
        'adenosine', 'digoxin', 'verapamil', 'diltiazem',
    }),
    'vasopressor_inotrope': frozenset({
        'norepinephrine', 'epinephrine', 'dopamine', 'dobutamine',
        'milrinone', 'vasopressin', 'phenylephrine', 'levosimendan',
    }),
    'nitrate': frozenset({
        'nitroglycerin', 'isosorbide', 'nitroprusside',
    }),
    'calcium_channel_blocker': frozenset({
        'amlodipine', 'nifedipine', 'felodipine', 'diltiazem', 'verapamil',
    }),
}

# ICU procedure labels that are cardiac-critical
CARDIAC_ICU_PROCEDURE_KEYWORDS = frozenset({
    'intubat', 'ventilat', 'trach',          # ventilatory support
    'dialysis', 'crrt', 'hemodialysis',       # renal replacement (AKI from cardiogenic shock)
    'arterial line', 'art line',              # hemodynamic monitoring
    'central line', 'cvp', 'triple lumen',   # central access
    'swan ganz', 'pa catheter', 'pulmonary artery',  # hemodynamic monitoring
    'iabp', 'intra-aortic', 'balloon pump',  # mechanical circulatory support
    'impella', 'ecmo', 'lvad',               # advanced mechanical support
    'defibrillat', 'cardiovert',             # rhythm management
    'pacemaker', 'pacing',                   # pacing
    'picc', 'peripherally inserted',         # IV access
})

# Cardiology-specific warning symptoms (template — no data needed)
CARDIOLOGY_WARNING_SYMPTOMS = [
    "Seek immediate emergency care if: Chest pain, tightness, pressure, or heaviness "
    "lasting more than 15 minutes.",
    "Seek immediate emergency care if: Sudden shortness of breath at rest or worsening "
    "breathlessness that prevents lying flat.",
    "Seek immediate emergency care if: Palpitations with dizziness, near-fainting, or "
    "loss of consciousness.",
    "Seek immediate emergency care if: New or worsening leg swelling (bilateral, pitting edema).",
    "Seek immediate emergency care if: Sudden unexplained weight gain of more than 2 kg "
    "in 24 hours (fluid retention).",
    "Contact your cardiologist within 24 hours if: Dizziness or lightheadedness while "
    "on new medications.",
    "Contact your cardiologist within 24 hours if: Any wound site redness, swelling, "
    "or discharge (post-procedure patients).",
    "Monitor daily: Blood pressure, pulse, and weight. Record and bring to follow-up.",
]

def _get_cardiac_med_category(drug_name: str) -> Optional[str]:
    """Classify a drug name into a cardiac medication category. Returns None if not cardiac."""
    name_lower = (drug_name or '').lower()
    for category, keywords in CARDIAC_MED_CATEGORIES.items():
        if any(kw in name_lower for kw in keywords):
            return category
    return None

def _is_cardiology_critical_lab(itemid: int, label: str) -> bool:
    """True if this lab is a cardiology-critical measurement."""
    if itemid in CARDIOLOGY_CRITICAL_LAB_ITEMIDS:
        return True
    label_lower = (label or '').lower()
    return any(kw in label_lower for kw in CARDIOLOGY_CRITICAL_LAB_KEYWORDS)

def _is_cardiac_icu_procedure(label: str) -> bool:
    """True if this ICU procedure is cardiac-critical."""
    label_lower = (label or '').lower()
    return any(kw in label_lower for kw in CARDIAC_ICU_PROCEDURE_KEYWORDS)

# Try to import prose-chunking libraries (needed only for CITI notes)
try:
    import medspacy
    MEDSPACY_AVAILABLE = True
except ImportError:
    MEDSPACY_AVAILABLE = False
    logger.info("medspaCy not installed — prose chunker disabled (ok until CITI notes arrive)")

try:
    import spacy
    _SCI_MODEL_AVAILABLE = False
    try:
        spacy.load("en_core_sci_scibert")
        _SCI_MODEL_AVAILABLE = True
    except OSError:
        try:
            spacy.load("en_core_sci_sm")
            _SCI_MODEL_AVAILABLE = True
        except OSError:
            pass
except ImportError:
    _SCI_MODEL_AVAILABLE = False



#section-1
#chunk dataclass
@dataclass
class Chunk:
    """
    One atomic fact, ready for embedding and retrieval.

    chunk_id       : stable UUID (str) — used by LLM for citations [c{chunk_id[:8]}]
    encounter_id   : hadm_id (int)
    note_type      : what kind of data this is (lab, diagnosis, emar, etc.)
    section        : which discharge summary section this belongs to
    text           : human-readable string (to_text() output or prose segment)
    timestamp      : when the fact was recorded (for recency-aware retrieval)
    char_offset_start/end : position in original source text (for UI highlighting)
                            0/len(text) for structured data (no source document)
    author_role    : physician | nurse | pharmacy | lab | system
    source_id      : original record ID for traceability (itemid, labevent_id, etc.)
    metadata       : arbitrary key-value for section-specific filtering in Qdrant
    """
    chunk_id: str
    encounter_id: int   #hadmid
    note_type: str
    section: str
    text: str  #what actually gets embedded
    timestamp: Optional[datetime] = None
    char_offset_start: int = 0
    char_offset_end: int = 0
    author_role: Optional[str] = None
    source_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        # char_offset_end defaults to full text length for structured chunks
        if self.char_offset_end == 0 and self.text:
            self.char_offset_end = len(self.text)

    def short_id(self) -> str:
        """First 8 chars — used in LLM citation format [c1a2b3c4]."""
        return self.chunk_id[:8]

    def to_qdrant_payload(self) -> dict:  #converts chunks dict
        """Payload stored alongside the vector in Qdrant for filtering."""
        return {
            "chunk_id":          self.chunk_id,
            "encounter_id":      self.encounter_id,
            "note_type":         self.note_type,
            "section":           self.section,
            "text":              self.text,
            "timestamp":         self.timestamp.isoformat() if self.timestamp else None,
            "char_offset_start": self.char_offset_start,
            "char_offset_end":   self.char_offset_end,
            "author_role":       self.author_role,
            "source_id":         self.source_id,
            **self.metadata,
        }


def _make_chunk(
    encounter_id: int,
    note_type: str,
    section: str,
    text: str,
    timestamp: Optional[datetime] = None,
    author_role: Optional[str] = None,
    source_id: Optional[str] = None,
    **meta,
) -> Chunk:
    """Factory — creates a Chunk with a fresh UUID."""
    text = text.strip()
    return Chunk(
        chunk_id=str(uuid4()),
        encounter_id=encounter_id,
        note_type=note_type,
        section=section,
        text=text,
        timestamp=timestamp,
        char_offset_end=len(text),
        author_role=author_role,
        source_id=source_id,
        metadata=meta,
    )



# Which POE order_types to skip (fully covered by other tables)
_POE_SKIP_TYPES = frozenset({
    'Medications', 'Lab', 'IV therapy',
    'General Care', 'Nutrition', 'Blood Bank',
})

# POE section assignment
def _poe_section(order_type: str, order_subtype: Optional[str]) -> str:
    subtype = (order_subtype or '').lower()
    otype   = (order_type or '').lower()
    if 'discharge' in subtype:
        return 'follow_up'
    if 'code status' in subtype:
        return 'hospital_course'
    if 'diet' in subtype or 'nutrition' in subtype:
        return 'diet_and_activity'
    if 'activity' in subtype or 'physical therapy' in subtype:
        return 'diet_and_activity'
    if otype == 'radiology' or 'xray' in subtype or 'ct scan' in subtype:
        return 'investigations'
    if 'consult' in otype or otype in ('cardiology', 'neurology', 'critical care'):
        return 'hospital_course'
    if otype == 'hemodialysis':
        return 'hospital_course'
    return 'hospital_course'


#Structured chunkers
def _chunk_admission(enc) -> list[Chunk]:
    """Admission demographics + dates — general_information section."""
    adm = enc.admission
    pat = enc.patient
    lines = [
        f"[Patient] {pat.age_str()}, admitted {adm.admit_date_str()} "
        f"as {adm.admission_type or 'unknown'} from "
        f"{adm.admission_location or 'unknown location'}.",
    ]
    if adm.dischtime:

        lines.append(
            f"[Discharge] Discharged {adm.discharge_date_str()} to "
            f"{adm.discharge_location or 'unknown location'}. "
            f"LOS: {adm.los_days()} days."
        )
    if adm.hospital_expire_flag:
        lines.append("[Outcome] Patient expired during this admission.")
    if pat.dod:
        lines.append(f"[Death] Date of death recorded: {pat.dod}.")
    if adm.race:
        lines.append(f"[Demographics] Race: {adm.race}.")
    if enc.primary_service:
        lines.append(f"[Service] Primary service: {enc.primary_service}.")

    chunks = []
    for line in lines:
        chunks.append(_make_chunk(
            encounter_id=enc.hadm_id,
            note_type='admission',
            section='general_information',
            text=line,
            timestamp=adm.admittime,
            author_role='system',
            source_id=str(enc.hadm_id),
        ))
    return chunks


def _chunk_diagnoses(enc) -> list[Chunk]:
    chunks = []
    for dx in enc.diagnoses:
        chunks.append(_make_chunk(
            encounter_id=enc.hadm_id,
            note_type='diagnosis',
            section='diagnosis',
            text=dx.to_text(),
            timestamp=enc.admission.admittime,
            author_role='physician',
            source_id=dx.icd_code,
            seq_num=dx.seq_num,
            is_primary=(dx.seq_num == 1),
        ))
    return chunks


def _chunk_procedures(enc) -> list[Chunk]:
    chunks = []
    for proc in enc.procedures:
        chunks.append(_make_chunk(
            encounter_id=enc.hadm_id,
            note_type='procedure',
            section='diagnosis',
            text=proc.to_text(),
            timestamp=datetime.combine(proc.chartdate, datetime.min.time())
                      if proc.chartdate else enc.admission.admittime,
            author_role='physician',
            source_id=proc.icd_code,
            seq_num=proc.seq_num,
        ))
    return chunks


def _chunk_drg(enc) -> list[Chunk]:
    chunks = []
    for drg in enc.drg_codes:
        chunks.append(_make_chunk(
            encounter_id=enc.hadm_id,
            note_type='drg',
            section='diagnosis',
            text=drg.to_text(),
            timestamp=enc.admission.admittime,
            author_role='system',
            source_id=str(drg.drg_code),
            drg_severity=drg.drg_severity,
            drg_mortality=drg.drg_mortality,
        ))
    return chunks


def _chunk_labs(enc) -> list[Chunk]:
    """
    One chunk per lab result. Each is independently retrievable and citable.
    Cardiology-critical labs (Troponin, BNP, CK-MB, PT/INR, electrolytes)
    are flagged for priority retrieval in cardiology sections.
    """
    chunks = []
    for lab in enc.lab_results:
        is_cardiac = _is_cardiology_critical_lab(lab.itemid, lab.label)
        # Troponin is THE most important cardiac lab — special flag
        is_troponin = 'troponin' in (lab.label or '').lower()
        is_bnp = any(k in (lab.label or '').lower()
                     for k in ['bnp', 'natriuretic', 'ntprobnp'])

        chunks.append(_make_chunk(
            encounter_id=enc.hadm_id,
            note_type='lab',
            section='investigations',
            text=lab.to_text(),
            timestamp=lab.charttime,
            author_role='lab',
            source_id=str(lab.labevent_id),
            itemid=lab.itemid,
            label=lab.label,
            is_abnormal=lab.is_abnormal(),
            is_critical=lab.is_critical(),
            flag=lab.flag,
            # CARDIOLOGY-SPECIFIC FLAGS
            is_cardiology_critical=is_cardiac,
            is_troponin=is_troponin,
            is_bnp=is_bnp,
            cardiac_lab_category=(
                'troponin' if is_troponin else
                'bnp' if is_bnp else
                'cardiac' if is_cardiac else None
            ),
        ))
    return chunks


def _chunk_microbiology(enc) -> list[Chunk]:
    chunks = []
    for mb in enc.microbiology:
        chunks.append(_make_chunk(
            encounter_id=enc.hadm_id,
            note_type='microbiology',
            section='investigations',
            text=mb.to_text(),
            timestamp=mb.charttime or (
                datetime.combine(mb.chartdate, datetime.min.time())
                if mb.chartdate else None
            ),
            author_role='lab',
            source_id=str(mb.microevent_id),
            spec_type=mb.spec_type_desc,
            org_name=mb.org_name,
            has_growth=mb.has_growth(),
        ))
    return chunks


def _chunk_medications(enc) -> list[Chunk]:
    """
    From prescriptions.csv — what was PRESCRIBED.
    Fallback source for discharge medications when EMAR is unavailable.
    Cardiac medications are flagged and categorized for cardiology retrieval.
    """
    chunks = []
    for med in enc.medications:
        cardiac_cat = _get_cardiac_med_category(med.drug)
        chunks.append(_make_chunk(
            encounter_id=enc.hadm_id,
            note_type='medication_prescribed',
            section='discharge_medications',
            text=med.to_text(),
            timestamp=med.starttime,
            author_role='physician',
            source_id=med.drug,
            drug=med.drug,
            route=med.route,
            # CARDIOLOGY-SPECIFIC FLAGS
            is_cardiac_medication=(cardiac_cat is not None),
            cardiac_med_category=cardiac_cat,
        ))
    return chunks


def _chunk_emar(enc) -> list[Chunk]:
    """
    From emar.csv + emar_detail.csv — what was ACTUALLY GIVEN.
    Records within 48h of discharge → discharge_medications section.
    Earlier records → hospital_course section (shows treatment history).
    Cardiac medications flagged and categorized — CRITICAL for cardiology.
    """
    chunks = []
    dischtime = enc.admission.dischtime
    cutoff = (dischtime - timedelta(hours=48)) if dischtime else None

    for emar in enc.medication_administrations:
        if cutoff and emar.charttime and emar.charttime >= cutoff:
            section = 'discharge_medications'
        else:
            section = 'hospital_course'

        cardiac_cat = _get_cardiac_med_category(emar.medication)
        chunks.append(_make_chunk(
            encounter_id=enc.hadm_id,
            note_type='medication_administered',
            section=section,
            text=emar.to_text(),
            timestamp=emar.charttime,
            author_role='nurse',
            source_id=emar.emar_id,
            medication=emar.medication,
            was_administered=emar.was_administered(),
            near_discharge=(section == 'discharge_medications'),
            # CARDIOLOGY-SPECIFIC FLAGS
            is_cardiac_medication=(cardiac_cat is not None),
            cardiac_med_category=cardiac_cat,
        ))
    return chunks


def _chunk_pharmacy(enc) -> list[Chunk]:
    """
    From pharmacy.csv — what pharmacy verified and dispensed.
    'Discontinued via patient discharge' = discharge medication.
    """
    chunks = []
    for rx in enc.pharmacy_records:
        chunks.append(_make_chunk(
            encounter_id=enc.hadm_id,
            note_type='medication_pharmacy',
            section='discharge_medications',
            text=rx.to_text(),
            timestamp=rx.starttime,
            author_role='pharmacy',
            source_id=str(rx.pharmacy_id),
            medication=rx.medication,
            is_active=rx.is_active(),
            status=rx.status,
        ))
    return chunks


def _chunk_icu_inputs(enc) -> list[Chunk]:
    """
    From inputevents.csv — IV medications, drips, fluids.
    Vasopressors, antibiotics, sedation → all clinically important.
    """
    chunks = []
    vasopressor_keywords = {
        'norepinephrine', 'epinephrine', 'dopamine', 'vasopressin',
        'phenylephrine', 'dobutamine', 'milrinone'
    }
    for inp in enc.icu_inputs:
        label_lower = inp.label.lower()
        is_vasopressor = any(k in label_lower for k in vasopressor_keywords)
        chunks.append(_make_chunk(
            encounter_id=enc.hadm_id,
            note_type='icu_input',
            section='hospital_course',
            text=inp.to_text(),
            timestamp=inp.starttime,
            author_role='nurse',
            source_id=str(inp.itemid),
            label=inp.label,
            category=inp.ordercategoryname,
            is_vasopressor=is_vasopressor,
        ))
    return chunks


def _chunk_vital_summaries(enc) -> list[Chunk]:
    """
    One chunk per 24h vital sign window.
    First window → clinical_examination (admission vitals).
    Subsequent windows → hospital_course (trend data).
    """
    chunks = []
    for i, vs in enumerate(sorted(enc.vital_summaries,
                                  key=lambda v: v.window_start)):
        section = 'clinical_examination' if i == 0 else 'hospital_course'
        chunks.append(_make_chunk(
            encounter_id=enc.hadm_id,
            note_type='vital_signs',
            section=section,
            text=vs.to_text(),
            timestamp=vs.window_start,
            author_role='nurse',
            source_id=f"vitals_{vs.window_start.date()}",
            window_day=i,
            is_admission_vitals=(i == 0),
        ))
    return chunks


def _chunk_icu_procedures(enc) -> list[Chunk]:
    """
    From procedureevents.csv — intubation, extubation, lines, dialysis.
    Cardiac-critical procedures flagged: IABP, ECMO, cardioversion, pacing.
    """
    chunks = []
    intubation_kw = {'intubat', 'ventilat', 'trach'}
    dialysis_kw   = {'dialysis', 'crrt', 'hemodialysis', 'ultrafiltration'}
    line_kw       = {'arterial line', 'art line', 'central line',
                     'picc', 'cvp', 'triple lumen'}

    for proc in enc.icu_procedure_events:
        label_lower = proc.label.lower()
        is_intubation = any(k in label_lower for k in intubation_kw)
        is_dialysis   = any(k in label_lower for k in dialysis_kw)
        is_line       = any(k in label_lower for k in line_kw)
        is_cardiac    = _is_cardiac_icu_procedure(proc.label)

        chunks.append(_make_chunk(
            encounter_id=enc.hadm_id,
            note_type='icu_procedure',
            section='hospital_course',
            text=proc.to_text(),
            timestamp=proc.starttime,
            author_role='nurse',
            source_id=str(proc.itemid),
            label=proc.label,
            category=proc.ordercategoryname,
            is_intubation=is_intubation,
            is_dialysis=is_dialysis,
            is_line=is_line,
            # CARDIOLOGY-SPECIFIC FLAG
            is_cardiac_critical_procedure=is_cardiac,
        ))
    return chunks


def _chunk_icu_ingredients(enc) -> list[Chunk]:
    """
    From ingredientevents.csv — TPN components and compound IV ingredients.
    Confirms nutritional support was active. Only 15 unique items in demo.
    """
    chunks = []
    for ing in enc.icu_ingredients:
        chunks.append(_make_chunk(
            encounter_id=enc.hadm_id,
            note_type='icu_ingredient',
            section='hospital_course',
            text=ing.to_text(),
            timestamp=ing.starttime,
            author_role='nurse',
            source_id=str(ing.itemid),
            label=ing.label,
        ))
    return chunks


def _chunk_icu_datetimes(enc) -> list[Chunk]:
    """
    From datetimeevents.csv — clinical event timestamps.
    When lines were placed/removed, when events occurred.
    """
    chunks = []
    for dte in enc.icu_datetime_events:
        chunks.append(_make_chunk(
            encounter_id=enc.hadm_id,
            note_type='icu_datetime',
            section='hospital_course',
            text=dte.to_text(),
            timestamp=dte.charttime,
            author_role='nurse',
            source_id=str(dte.itemid),
            label=dte.label,
        ))
    return chunks


def _chunk_fluid_balance(enc) -> list[Chunk]:
    """
    From outputevents.csv (aggregated) — daily urine output.
    Critical for AKI, CHF, fluid overload context.
    """
    chunks = []
    for fb in enc.daily_fluid_balance:
        chunks.append(_make_chunk(
            encounter_id=enc.hadm_id,
            note_type='fluid_balance',
            section='hospital_course',
            text=fb.to_text(),
            timestamp=datetime.combine(fb.date, datetime.min.time()),
            author_role='nurse',
            source_id=f"fluid_{fb.date}",
            urine_ml=fb.urine_output_ml,
            total_ml=fb.total_output_ml,
        ))
    return chunks


def _chunk_transfers(enc) -> list[Chunk]:
    """
    From transfers.csv — patient journey through the hospital.
    ED → floor → ICU → step-down → discharge.
    """
    chunks = []
    for t in enc.hospital_transfers:
        section = 'follow_up' if t.eventtype == 'discharge' else 'hospital_course'
        chunks.append(_make_chunk(
            encounter_id=enc.hadm_id,
            note_type='hospital_transfer',
            section=section,
            text=t.to_text(),
            timestamp=t.intime,
            author_role='system',
            source_id=str(t.transfer_id),
            eventtype=t.eventtype,
            careunit=t.careunit,
        ))
    return chunks


def _chunk_services(enc) -> list[Chunk]:
    """From services.csv — which specialty team cared for the patient."""
    chunks = []
    for svc in enc.services:
        chunks.append(_make_chunk(
            encounter_id=enc.hadm_id,
            note_type='service_transfer',
            section='hospital_course',
            text=svc.to_text(),
            timestamp=svc.transfertime,
            author_role='system',
            source_id=svc.curr_service,
            service=svc.curr_service,
        ))
    return chunks


def _chunk_icu_stays(enc) -> list[Chunk]:
    """One chunk per ICU stay summarizing the unit and duration."""
    chunks = []
    for icu in enc.icu_stays:
        chunks.append(_make_chunk(
            encounter_id=enc.hadm_id,
            note_type='icu_stay',
            section='hospital_course',
            text=icu.to_text(),
            timestamp=icu.intime,
            author_role='system',
            source_id=str(icu.stay_id),
            stay_id=icu.stay_id,
            los_days=icu.los,
            first_careunit=icu.first_careunit,
        ))
    return chunks


def _chunk_physician_orders(enc) -> list[Chunk]:
    """
    From poe.csv. Filters out Medications/Lab/General Care (covered elsewhere).
    Preserves: Consults, Radiology, Cardiology, ADT orders, Hemodialysis, TPN.
    """
    chunks = []
    for poe in enc.physician_orders:
        if poe.order_type in _POE_SKIP_TYPES:
            continue
        section = _poe_section(poe.order_type, poe.order_subtype)
        chunks.append(_make_chunk(
            encounter_id=enc.hadm_id,
            note_type='physician_order',
            section=section,
            text=poe.to_text(),
            timestamp=poe.ordertime,
            author_role='physician',
            source_id=poe.poe_id,
            order_type=poe.order_type,
            order_subtype=poe.order_subtype,
            is_consult=poe.is_consult(),
            is_discharge_planning=poe.is_discharge_planning(),
            is_code_status=poe.is_code_status(),
        ))
    return chunks


def _chunk_omr_vitals(enc) -> list[Chunk]:
    """
    From omr.csv — outpatient/baseline vitals (pre-admission measurements).
    Context for how unwell the patient was before this admission.
    """
    chunks = []
    for omr in enc.omr_vitals:
        chunks.append(_make_chunk(
            encounter_id=enc.hadm_id,
            note_type='omr_vital',
            section='clinical_examination',
            text=omr.to_text(),
            timestamp=datetime.combine(omr.chartdate, datetime.min.time()),
            author_role='nurse',
            source_id=f"omr_{omr.chartdate}_{omr.result_name}",
            result_name=omr.result_name,
        ))
    return chunks


def _chunk_troponin_trend(enc) -> list[Chunk]:
    """
    CARDIOLOGY-SPECIFIC: Groups serial troponin measurements into a trend chunk.
    A single chunk saying 'Troponin peaked at X on Day 2 then trended down' is
    far more useful for the LLM than 8 individual troponin chunks.
    Also keeps individual chunks — both are indexed.
    """
    troponin_labs = [
        lab for lab in enc.lab_results
        if 'troponin' in (lab.label or '').lower()
    ]
    if len(troponin_labs) < 2:
        return []  # need at least 2 for a trend

    # Sort by time
    sorted_trop = sorted(
        [l for l in troponin_labs if l.charttime],
        key=lambda l: l.charttime
    )
    if not sorted_trop:
        return []

    # Build trend description
    count = len(sorted_trop)
    first = sorted_trop[0]
    last  = sorted_trop[-1]
    peak  = max(sorted_trop, key=lambda l: (l.valuenum or 0))

    first_val = first.value or str(first.valuenum) or 'N/A'
    last_val  = last.value  or str(last.valuenum)  or 'N/A'
    peak_val  = peak.value  or str(peak.valuenum)  or 'N/A'

    first_date = first.charttime.strftime('%Y-%m-%d %H:%M') if first.charttime else '?'
    last_date  = last.charttime.strftime('%Y-%m-%d %H:%M')  if last.charttime  else '?'
    peak_date  = peak.charttime.strftime('%Y-%m-%d %H:%M')  if peak.charttime  else '?'

    abnormal_count = sum(1 for l in sorted_trop if l.is_abnormal())
    trend_text = (
        f"[Troponin Trend] {count} serial measurements. "
        f"First: {first_val} ({first_date}). "
        f"Peak: {peak_val} ({peak_date}). "
        f"Last: {last_val} ({last_date}). "
        f"{abnormal_count}/{count} abnormal. "
        f"Label: {first.label}."
    )

    return [_make_chunk(
        encounter_id=enc.hadm_id,
        note_type='troponin_trend',
        section='investigations',
        text=trend_text,
        timestamp=first.charttime,
        author_role='lab',
        source_id='troponin_trend',
        measurement_count=count,
        abnormal_count=abnormal_count,
        is_cardiology_critical=True,
        is_troponin=True,
    )]


def _chunk_cardiology_warning_symptoms(enc) -> list[Chunk]:
    """
    CARDIOLOGY-SPECIFIC: Template-based warning symptoms chunk.
    No source data needed. Pre-defined cardiac red flags.
    These go into the warning_symptoms section of every cardiology discharge summary.
    """
    chunks = []
    for i, symptom in enumerate(CARDIOLOGY_WARNING_SYMPTOMS):
        chunks.append(_make_chunk(
            encounter_id=enc.hadm_id,
            note_type='warning_symptom',
            section='warning_symptoms',
            text=symptom,
            timestamp=enc.admission.dischtime or enc.admission.admittime,
            author_role='physician',
            source_id=f'cardiology_warning_{i}',
        ))
    return chunks


#prose chunker 
# Section → discharge summary section label
_NOTE_SECTION_MAP = {
    'chief complaint':             'present_illness',
    'history of present illness':  'present_illness',
    'hpi':                         'present_illness',
    'past medical history':        'present_illness',
    'social history':              'present_illness',
    'medications on admission':    'discharge_medications',
    'allergies':                   'general_information',
    'physical exam':               'clinical_examination',
    'pertinent results':           'investigations',
    'labs':                        'investigations',
    'imaging':                     'investigations',
    'microbiology':                'investigations',
    'brief hospital course':       'hospital_course',
    'hospital course':             'hospital_course',
    'assessment and plan':         'hospital_course',
    'discharge medications':       'discharge_medications',
    'discharge diagnosis':         'diagnosis',
    'discharge condition':         'follow_up',
    'discharge instructions':      'follow_up',
    'followup instructions':       'follow_up',
    'discharge disposition':       'follow_up',
}

def _detect_section(header: str) -> str:
    """Map a note header → discharge summary section label."""
    h = header.lower().strip()
    for key, section in _NOTE_SECTION_MAP.items():
        if key in h:
            return section
    return 'hospital_course'  # default


def _split_into_sentence_windows(
    text: str, window: int = 5, overlap: int = 1
) -> list[str]:
    """
    Split prose text into overlapping sentence windows.
    Uses simple regex sentence splitting (scispaCy if available, else regex).
    Never crosses section boundaries (caller handles that).
    """
    if _SCI_MODEL_AVAILABLE:
        try:
            nlp = spacy.load("en_core_sci_sm")
            doc = nlp(text)
            sentences = [sent.text.strip() for sent in doc.sents if sent.text.strip()]
        except Exception:
            sentences = _regex_sentence_split(text)
    else:
        sentences = _regex_sentence_split(text)

    if not sentences:
        return [text] if text.strip() else []

    windows = []
    step = window - overlap
    for i in range(0, len(sentences), step):
        chunk_sents = sentences[i:i + window]
        chunk_text = ' '.join(chunk_sents)
        if chunk_text.strip():
            windows.append(chunk_text.strip())
    return windows


def _regex_sentence_split(text: str) -> list[str]:
    """Fallback sentence splitter when scispaCy is unavailable."""
    raw = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text.strip())
    return [s.strip() for s in raw if s.strip()]


def _chunk_clinical_notes(enc) -> list[Chunk]:
    """
    Prose chunker for clinical notes (requires CITI access).
    Chunks by section, then by sentence windows.
    Active once enc.notes is non-empty.
    """
    if not enc.notes:
        return []

    chunks = []

    for note in enc.notes:
        if note.is_error:
            continue

        text = note.text.strip()
        if not text:
            continue

        author_role = 'physician' if note.note_type in (
            'Discharge summary', 'Physician', 'Radiology'
        ) else 'nurse'

        # Try to split by section headers (medspaCy if available, else regex)
        sections = _parse_note_sections(text)

        char_offset = 0
        for section_header, section_text in sections:
            section_label = _detect_section(section_header)

            windows = _split_into_sentence_windows(
                section_text, window=5, overlap=1
            )

            for window_text in windows:
                # Approximate char offsets within original note
                start = text.find(window_text[:40], char_offset)
                start = start if start != -1 else char_offset
                end   = start + len(window_text)
                char_offset = max(char_offset, end - len(window_text) // 2)

                chunks.append(Chunk(
                    chunk_id=str(uuid4()),
                    encounter_id=enc.hadm_id,
                    note_type='clinical_note',
                    section=section_label,
                    text=window_text,
                    timestamp=note.charttime or (
                        datetime.combine(note.chartdate, datetime.min.time())
                        if note.chartdate else None
                    ),
                    char_offset_start=start,
                    char_offset_end=end,
                    author_role=author_role,
                    source_id=note.note_id,
                    metadata={
                        'note_type':      note.note_type,
                        'note_section':   section_header,
                        'note_id':        note.note_id,
                    },
                ))

    return chunks


def _parse_note_sections(text: str) -> list[tuple[str, str]]:
    """
    Split a clinical note into (header, body) pairs by section.
    Uses medspaCy if available, else simple regex pattern.

    MIMIC-IV notes use patterns like:
        'Chief Complaint:\n', 'History of Present Illness:\n', etc.
    """
    if MEDSPACY_AVAILABLE:
        try:
            nlp = medspacy.load()
            doc = nlp(text)
            sections = []
            for section in doc._.sections:
                header = section.title_span.text if section.title_span else 'unknown'
                body   = section.body_span.text.strip() if section.body_span else ''
                if body:
                    sections.append((header, body))
            if sections:
                return sections
        except Exception as e:
            logger.debug(f"medspaCy section parse failed: {e}")

    # Regex fallback — works well on MIMIC notes
    pattern = re.compile(
        r'^([A-Z][A-Za-z /&]+(?:\([^)]+\))?):?\s*\n', re.MULTILINE
    )
    matches = list(pattern.finditer(text))

    if not matches:
        return [('full_text', text)]

    sections = []
    for i, match in enumerate(matches):
        header = match.group(1).strip()
        start  = match.end()
        end    = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body   = text[start:end].strip()
        if body:
            sections.append((header, body))
    return sections


#MAIN POINT

def chunk_encounter(enc) -> list[Chunk]:
    """
    Main entry point. Takes a fully-loaded EncounterDocument,
    returns a flat list[Chunk] ready for embedding and indexing.

    Structured chunkers (active now):
        admission, diagnoses, procedures, drg, labs, microbiology,
        medications, emar, pharmacy, icu_inputs, vital_summaries,
        icu_procedures, icu_ingredients, icu_datetimes, fluid_balance,
        transfers, services, icu_stays, physician_orders, omr_vitals

    Prose chunker (activates when enc.notes is non-empty / CITI approved):
        clinical_notes → section-aware sentence windows
    """
    all_chunks: list[Chunk] = []

    chunkers = [
        _chunk_admission,
        _chunk_diagnoses,
        _chunk_procedures,
        _chunk_drg,
        _chunk_labs,
        _chunk_troponin_trend,          # CARDIOLOGY: serial troponin grouped as trend
        _chunk_microbiology,
        _chunk_medications,
        _chunk_emar,
        _chunk_pharmacy,
        _chunk_icu_inputs,
        _chunk_vital_summaries,
        _chunk_icu_procedures,
        _chunk_icu_ingredients,
        _chunk_icu_datetimes,
        _chunk_fluid_balance,
        _chunk_transfers,
        _chunk_services,
        _chunk_icu_stays,
        _chunk_physician_orders,
        _chunk_omr_vitals,
        _chunk_cardiology_warning_symptoms,  # CARDIOLOGY: red flag symptoms template
        _chunk_clinical_notes,          # no-op until CITI notes arrive
    ]

    for fn in chunkers:
        try:
            new_chunks = fn(enc)
            all_chunks.extend(new_chunks)
        except Exception as e:
            logger.error(f"Chunker {fn.__name__} failed for "
                         f"hadm_id={enc.hadm_id}: {e}")

    # Dedup on (encounter_id, text) — same fact shouldn't appear twice
    seen: set[tuple] = set()
    deduped: list[Chunk] = []
    for c in all_chunks:
        key = (c.encounter_id, c.text[:120])
        if key not in seen:
            seen.add(key)
            deduped.append(c)

    logger.info(
        f"chunk_encounter(hadm_id={enc.hadm_id}): "
        f"{len(deduped)} chunks "
        f"({len(all_chunks) - len(deduped)} duplicates removed)"
    )
    return deduped


# ============================================================
# SECTION 6 — Chunk statistics (for testing and verification)
# ============================================================

def chunk_stats(chunks: list[Chunk]) -> dict:
    """
    Returns a breakdown of chunk counts by note_type and section.
    Use this to verify chunker output before embedding.
    """
    from collections import Counter

    by_type    = Counter(c.note_type for c in chunks)
    by_section = Counter(c.section for c in chunks)
    empty_text = [c for c in chunks if not c.text.strip()]
    no_timestamp = [c for c in chunks if c.timestamp is None]
    dup_ids    = len(chunks) - len({c.chunk_id for c in chunks})

    return {
        'total':          len(chunks),
        'by_note_type':   dict(by_type.most_common()),
        'by_section':     dict(by_section.most_common()),
        'empty_text':     len(empty_text),
        'no_timestamp':   len(no_timestamp),
        'duplicate_ids':  dup_ids,
    }