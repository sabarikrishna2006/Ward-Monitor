"""
models.py — Complete data models for Discharge Summary AI
==========================================================
Uses ALL available MIMIC-IV tables:

hosp/  admissions, patients, diagnoses_icd, d_icd_diagnoses,
       procedures_icd, d_icd_procedures, labevents, d_labitems,
       prescriptions, emar, emar_detail, pharmacy,
       microbiologyevents, services, drgcodes, omr, transfers

icu/   icustays, chartevents, inputevents, outputevents,
       procedureevents, d_items

note/  discharge.csv (when CITI access arrives)

Each model has to_text() — converts structured data to one sentence.
EncounterDocument.get_section_context(section) is the RAG entry point.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import ClassVar, Optional

from pydantic import BaseModel


# ============================================================
# SECTION 1 — Patient and admission
# ============================================================

class PatientDemographics(BaseModel):
    subject_id: int
    gender: str
    anchor_age: int
    anchor_year: int
    anchor_year_group: str
    dod: Optional[date] = None

    def age_str(self) -> str:
        return f"{self.anchor_age}-year-old {'male' if self.gender == 'M' else 'female'}"


class AdmissionInfo(BaseModel):
    hadm_id: int
    subject_id: int
    admittime: datetime
    dischtime: Optional[datetime] = None
    deathtime: Optional[datetime] = None
    admission_type: Optional[str] = None
    admit_provider_id: Optional[str] = None
    admission_location: Optional[str] = None
    discharge_location: Optional[str] = None
    insurance: Optional[str] = None
    language: Optional[str] = None
    marital_status: Optional[str] = None
    race: Optional[str] = None
    edregtime: Optional[datetime] = None
    edouttime: Optional[datetime] = None
    hospital_expire_flag: int = 0

    def los_days(self) -> Optional[int]:
        if self.admittime and self.dischtime:
            return (self.dischtime - self.admittime).days
        return None

    def admit_date_str(self) -> str:
        return self.admittime.strftime("%B %d, %Y") if self.admittime else "unknown date"

    def discharge_date_str(self) -> str:
        return self.dischtime.strftime("%B %d, %Y") if self.dischtime else "unknown date"


# ============================================================
# SECTION 2 — Diagnoses, procedures, DRG
# ============================================================

class Diagnosis(BaseModel):
    seq_num: int
    icd_code: str
    icd_version: int
    description: str

    def to_text(self) -> str:
        priority = "Primary diagnosis" if self.seq_num == 1 else f"Diagnosis #{self.seq_num}"
        return f"[{priority}] {self.description} (ICD-{self.icd_version}: {self.icd_code})"

    def is_primary(self) -> bool:
        return self.seq_num == 1


class Procedure(BaseModel):
    seq_num: int
    icd_code: str
    icd_version: int
    description: str
    chartdate: Optional[date] = None

    def to_text(self) -> str:
        date_str = f" on {self.chartdate}" if self.chartdate else ""
        return (f"[Procedure #{self.seq_num}] {self.description} "
                f"(ICD-{self.icd_version}: {self.icd_code}){date_str}")


class DRGCode(BaseModel):
    drg_type: str
    drg_code: int
    description: str
    drg_severity: Optional[int] = None
    drg_mortality: Optional[int] = None

    def to_text(self) -> str:
        sev = f" | Severity: {self.drg_severity}/4" if self.drg_severity else ""
        mort = f" | Mortality risk: {self.drg_mortality}/4" if self.drg_mortality else ""
        return f"[DRG {self.drg_type} {self.drg_code}] {self.description}{sev}{mort}"


# ============================================================
# SECTION 3 — Medications (3 sources for maximum accuracy)
# ============================================================

class Medication(BaseModel):
    """prescriptions.csv — what was PRESCRIBED."""
    drug: str
    drug_type: Optional[str] = None
    prod_strength: Optional[str] = None
    dose_val_rx: Optional[str] = None
    dose_unit_rx: Optional[str] = None
    form_val_disp: Optional[str] = None
    form_unit_disp: Optional[str] = None
    doses_per_24_hrs: Optional[float] = None
    route: Optional[str] = None
    starttime: Optional[datetime] = None
    stoptime: Optional[datetime] = None

    def to_text(self) -> str:
        parts = [self.drug]
        if self.prod_strength:
            parts.append(self.prod_strength)
        elif self.dose_val_rx and self.dose_unit_rx:
            parts.append(f"{self.dose_val_rx} {self.dose_unit_rx}")
        if self.route:
            parts.append(f"route: {self.route}")
        if self.doses_per_24_hrs and self.doses_per_24_hrs > 0:
            freq_map = {1.0: "once daily", 2.0: "twice daily",
                        3.0: "three times daily", 4.0: "four times daily"}
            parts.append(freq_map.get(self.doses_per_24_hrs,
                                      f"{self.doses_per_24_hrs:.0f}x/day"))
        if self.starttime:
            parts.append(f"started {self.starttime.strftime('%Y-%m-%d')}")
        return " | ".join(parts)

    def is_active_at(self, dt: datetime) -> bool:
        started = self.starttime is None or self.starttime <= dt
        not_stopped = self.stoptime is None or self.stoptime > dt
        return started and not_stopped


class MedicationAdministration(BaseModel):
    """
    emar.csv + emar_detail.csv — what was ACTUALLY GIVEN.
    Most accurate source for discharge medications.
    Note: event_txt is often null in MIMIC demo — null = treat as administered.
    """
    emar_id: str
    charttime: Optional[datetime] = None
    medication: str
    event_txt: Optional[str] = None
    dose_given: Optional[str] = None
    dose_given_unit: Optional[str] = None
    route: Optional[str] = None
    infusion_rate: Optional[str] = None
    infusion_rate_unit: Optional[str] = None

    # Whitelist of event_txt values that confirm medication was given.
    # Based on analysis of all 40+ unique values in MIMIC-IV demo emar.csv.
    # Anything NOT in this set = not administered (conservative approach).
    _ADMINISTERED_STATUSES: ClassVar[frozenset] = frozenset({
        # Explicitly given
        'Administered',
        'Delayed Administered',              # given late — still given
        'Partial Administered',              # partial dose — still given
        'Administered Bolus from IV Drip',   # bolus pulled from running drip
        'Administered in Other Location',    # given in a different ward
        'in Other Location',                # given elsewhere (MIMIC: leading space stripped)
        # Infusion is actively running
        'Started',                           # new infusion started
        'Delayed Started',                   # started late — running
        'Started in Other Location',         # started in different unit
        'Restarted',                         # restarted after hold
        'Infusion Reconciliation',           # nurse confirmed infusion still running
        'Rate Change',                       # rate changed — infusion still running
        # Nurse confirmed administration
        'Confirmed',
        'Delayed Confirmed',                 # confirmed late
        'Confirmed in Other Location',       # confirmed given elsewhere
        # Topical / patch medications
        'Applied',                           # patch or cream applied
        'Applied in Other Location',         # applied in different unit
        'Removed Existing / Applied New',    # patch replaced — new dose applied
    })

    def was_administered(self) -> bool:
        """
        True only if medication was actually given to the patient.

        Uses a WHITELIST approach — only statuses that explicitly
        confirm administration return True. Everything else is False.

        Null event_txt: 311 records in demo with null — these are
        scheduled medications and are treated as administered.

        Key exclusions:
          Flushed / Not Flushed / Delayed Flushed  → saline flush, NOT a drug
          Not Given / Hold Dose / Not Confirmed     → dose skipped
          Stopped / Stopped As Directed             → infusion ended
          Assessed / Delayed Assessed               → assessment only
          Infusion Reconciliation Not Done          → reconciliation skipped
        """
        if self.event_txt is None:
            return True   # null = treat as administered (MIMIC demo convention)
        return self.event_txt.strip() in self._ADMINISTERED_STATUSES

    def to_text(self) -> str:
        status = self.event_txt or 'Administered'
        dose = (f" {self.dose_given} {self.dose_given_unit}"
                if self.dose_given and self.dose_given_unit else '')
        route = f" via {self.route}" if self.route else ''
        rate = (f" at {self.infusion_rate} {self.infusion_rate_unit}"
                if self.infusion_rate and self.infusion_rate_unit else '')
        time = (f" at {self.charttime.strftime('%Y-%m-%d %H:%M')}"
                if self.charttime else '')
        return f"[EMAR] {self.medication}{dose}{route}{rate} — {status}{time}"


class PharmacyRecord(BaseModel):
    """pharmacy.csv — what pharmacy VERIFIED and DISPENSED."""
    pharmacy_id: int
    medication: str
    status: Optional[str] = None
    route: Optional[str] = None
    frequency: Optional[str] = None
    doses_per_24_hrs: Optional[float] = None
    starttime: Optional[datetime] = None
    stoptime: Optional[datetime] = None
    dispensation: Optional[str] = None

    def is_active(self) -> bool:
        """
        True if medication was active at or through discharge.
        'Discontinued via patient discharge' = stopped BECAUSE patient left
        = this IS a discharge medication. Must be included.
        Real statuses seen in MIMIC demo:
          'Discontinued' — stopped during admission
          'Discontinued via patient discharge' — stopped at discharge (KEEP)
          'Expired' — order expired
          'Inactive (Due to a change order)' — replaced by updated order
        """
        if self.status is None:
            return True
        s = self.status.lower()
        if 'via patient discharge' in s:
            return True
        return 'active' in s and 'inactive' not in s

    def to_text(self) -> str:
        status = self.status or 'Unknown'
        freq = f" {self.frequency}" if self.frequency else ''
        route = f" via {self.route}" if self.route else ''
        return f"[Pharmacy] {self.medication}{freq}{route} — {status}"


# ============================================================
# SECTION 4 — Laboratory results
# ============================================================

class LabResult(BaseModel):
    labevent_id: int
    itemid: int
    label: str
    fluid: Optional[str] = None
    category: Optional[str] = None
    charttime: Optional[datetime] = None
    value: Optional[str] = None
    valuenum: Optional[float] = None
    valueuom: Optional[str] = None
    ref_range_lower: Optional[float] = None
    ref_range_upper: Optional[float] = None
    flag: Optional[str] = None
    priority: Optional[str] = None

    def to_text(self) -> str:
        val_str = (str(self.valuenum) if self.valuenum is not None
                   else (self.value or "N/A"))
        unit_str = f" {self.valueuom}" if self.valueuom else ""
        ref_str = ""
        if self.ref_range_lower is not None and self.ref_range_upper is not None:
            ref_str = f" (ref: {self.ref_range_lower}–{self.ref_range_upper})"
        elif self.ref_range_upper is not None:
            ref_str = f" (ref: <{self.ref_range_upper})"
        flag_str = f" [{self.flag.upper()}]" if self.flag else ""
        time_str = (f" at {self.charttime.strftime('%Y-%m-%d %H:%M')}"
                    if self.charttime else "")
        fluid_str = f" [{self.fluid}]" if self.fluid else ""
        return (f"[Lab] {self.label}{fluid_str}: "
                f"{val_str}{unit_str}{ref_str}{flag_str}{time_str}")

    def is_abnormal(self) -> bool:
        return self.flag == "abnormal"

    def is_critical(self) -> bool:
        if self.valuenum is None:
            return False
        if self.ref_range_upper and self.valuenum > 2 * self.ref_range_upper:
            return True
        if (self.ref_range_lower and self.ref_range_lower > 0
                and self.valuenum < 0.5 * self.ref_range_lower):
            return True
        return False


# ============================================================
# SECTION 5 — Microbiology
# ============================================================

class AntibioticSensitivity(BaseModel):
    ab_name: str
    interpretation: Optional[str] = None
    dilution_text: Optional[str] = None

    INTERP_MAP: ClassVar[dict] = {
        'S': 'Sensitive', 'R': 'Resistant', 'I': 'Intermediate'
    }

    def to_text(self) -> str:
        interp = self.INTERP_MAP.get(self.interpretation or '',
                                     self.interpretation or 'Unknown')
        return f"{self.ab_name}: {interp}"


class MicrobiologyResult(BaseModel):
    microevent_id: int
    micro_specimen_id: Optional[int] = None
    chartdate: Optional[date] = None
    charttime: Optional[datetime] = None
    spec_type_desc: Optional[str] = None
    test_name: Optional[str] = None
    org_name: Optional[str] = None
    isolate_num: Optional[int] = None
    quantity: Optional[str] = None
    sensitivities: list[AntibioticSensitivity] = []

    def to_text(self) -> str:
        date_str = str(self.chartdate) if self.chartdate else "unknown date"
        spec = self.spec_type_desc or "Unknown specimen"
        if not self.org_name:
            return f"[Culture] {spec} ({date_str}): No growth"
        lines = [f"[Culture] {spec} ({date_str}): {self.org_name}"]
        if self.sensitivities:
            sensitive = [s.ab_name for s in self.sensitivities if s.interpretation == 'S']
            resistant = [s.ab_name for s in self.sensitivities if s.interpretation == 'R']
            if sensitive:
                lines.append(f"  Sensitive: {', '.join(sensitive[:6])}")
            if resistant:
                lines.append(f"  Resistant: {', '.join(resistant[:6])}")
        return "\n".join(lines)

    def has_growth(self) -> bool:
        return self.org_name is not None


# ============================================================
# SECTION 6 — ICU events (inputevents, outputevents, procedureevents)
# ============================================================

class ICUInputEvent(BaseModel):
    """
    inputevents.csv + d_items.csv.
    IV medications (vasopressors, antibiotics, insulin),
    blood products, and fluids in ICU.
    ordercategoryname: '01-Drips', '08-Antibiotics (IV)', '03-Blood Products', etc.
    """
    stay_id: int
    itemid: int
    label: str
    category: Optional[str] = None
    starttime: Optional[datetime] = None
    endtime: Optional[datetime] = None
    amount: Optional[float] = None
    amountuom: Optional[str] = None
    rate: Optional[float] = None
    rateuom: Optional[str] = None
    ordercategoryname: Optional[str] = None
    totalamount: Optional[float] = None
    totalamountuom: Optional[str] = None
    statusdescription: Optional[str] = None

    def to_text(self) -> str:
        cat = f" [{self.ordercategoryname}]" if self.ordercategoryname else ""
        amount_str = (f" {self.totalamount:.0f} {self.totalamountuom}"
                      if self.totalamount and self.totalamountuom else
                      (f" {self.amount:.1f} {self.amountuom}"
                       if self.amount and self.amountuom else ""))
        rate_str = (f" at {self.rate:.2f} {self.rateuom}"
                    if self.rate and self.rateuom else "")
        time_str = (f" from {self.starttime.strftime('%Y-%m-%d %H:%M')}"
                    if self.starttime else "")
        return f"[ICU Input]{cat} {self.label}{amount_str}{rate_str}{time_str}"


class DailyFluidBalance(BaseModel):
    """
    Aggregated daily output from outputevents.csv.
    Critical for AKI, CHF, and fluid overload assessment.
    """
    date: date
    urine_output_ml: Optional[float] = None
    other_output_ml: Optional[float] = None
    total_output_ml: Optional[float] = None

    def to_text(self) -> str:
        urine = (f"Urine: {self.urine_output_ml:.0f} mL"
                 if self.urine_output_ml is not None else "Urine: not recorded")
        other = (f", Other: {self.other_output_ml:.0f} mL"
                 if self.other_output_ml else "")
        total = (f", Total: {self.total_output_ml:.0f} mL"
                 if self.total_output_ml else "")
        return f"[Fluid Output] {self.date}: {urine}{other}{total}"


class ICUProcedureEvent(BaseModel):
    """
    procedureevents.csv + d_items.csv.
    Intubation, extubation, central line, arterial line, dialysis, etc.
    Key itemids: 225792=Intubation, 225794=Extubation,
                 225752=Arterial Line, 225751=Central Line, 225441=Dialysis
    """
    stay_id: int
    itemid: int
    label: str
    category: Optional[str] = None
    starttime: Optional[datetime] = None
    endtime: Optional[datetime] = None
    value: Optional[float] = None
    valueuom: Optional[str] = None
    ordercategoryname: Optional[str] = None
    location: Optional[str] = None

    def duration_hours(self) -> Optional[float]:
        if self.starttime and self.endtime:
            return round((self.endtime - self.starttime).total_seconds() / 3600, 1)
        return None

    def to_text(self) -> str:
        cat = f" [{self.ordercategoryname}]" if self.ordercategoryname else ""
        loc = f" at {self.location}" if self.location else ""
        time_str = (f" started {self.starttime.strftime('%Y-%m-%d %H:%M')}"
                    if self.starttime else "")
        dur = self.duration_hours()
        dur_str = f" (duration: {dur}h)" if dur else ""
        return f"[ICU Procedure]{cat} {self.label}{loc}{time_str}{dur_str}"


# ============================================================
# SECTION 7 — ICU stays, service, and hospital transfers
# ============================================================

class ICUStay(BaseModel):
    stay_id: int
    first_careunit: str
    last_careunit: str
    intime: datetime
    outtime: Optional[datetime] = None
    los: float

    def to_text(self) -> str:
        out_str = (self.outtime.strftime('%Y-%m-%d') if self.outtime else "ongoing")
        unit = (self.first_careunit if self.first_careunit == self.last_careunit
                else f"{self.first_careunit} → {self.last_careunit}")
        return (f"[ICU] {unit} — admitted {self.intime.strftime('%Y-%m-%d')}, "
                f"discharged {out_str} ({self.los:.1f} days)")


class ServiceTransfer(BaseModel):
    SERVICE_NAMES: ClassVar[dict] = {
        'MED': 'General Medicine', 'CMED': 'Cardiac Medicine',
        'OMED': 'Oncology Medicine', 'SURG': 'General Surgery',
        'CSURG': 'Cardiac Surgery', 'NSURG': 'Neurosurgery',
        'TRAUM': 'Trauma Surgery', 'GYN': 'Gynecology',
        'OBS': 'Obstetrics', 'PSYCH': 'Psychiatry',
        'ENT': 'Ear Nose Throat', 'GU': 'Genitourinary',
        'NMED': 'Neurology', 'ORTHO': 'Orthopaedics',
    }
    transfertime: Optional[datetime] = None
    prev_service: Optional[str] = None
    curr_service: str

    def service_name(self) -> str:
        return self.SERVICE_NAMES.get(self.curr_service, self.curr_service)

    def to_text(self) -> str:
        time_str = (f" from {self.transfertime.strftime('%Y-%m-%d')}"
                    if self.transfertime else "")
        return f"[Service] {self.service_name()}{time_str}"


class HospitalTransfer(BaseModel):
    """
    transfers.csv — full patient journey through the hospital.
    eventtype: 'admit', 'transfer', 'discharge'
    careunit: 'Emergency Department', 'Medical Intensive Care Unit (MICU)', etc.
    """
    transfer_id: int
    eventtype: str
    careunit: Optional[str] = None
    intime: Optional[datetime] = None
    outtime: Optional[datetime] = None

    def duration_hours(self) -> Optional[float]:
        if self.intime and self.outtime:
            return round((self.outtime - self.intime).total_seconds() / 3600, 1)
        return None

    def to_text(self) -> str:
        unit = self.careunit or "Unknown unit"
        time_str = (f" on {self.intime.strftime('%Y-%m-%d %H:%M')}"
                    if self.intime else "")
        dur = self.duration_hours()
        dur_str = f" ({dur:.0f}h)" if dur else ""
        return f"[Transfer] {self.eventtype.title()} → {unit}{time_str}{dur_str}"


# ============================================================
# SECTION 8 — Vital signs
# ============================================================

class VitalSignsSummary(BaseModel):
    window_start: datetime
    window_end: datetime
    heart_rate_min: Optional[float] = None
    heart_rate_max: Optional[float] = None
    heart_rate_mean: Optional[float] = None
    sbp_min: Optional[float] = None
    sbp_max: Optional[float] = None
    sbp_mean: Optional[float] = None
    dbp_min: Optional[float] = None
    dbp_max: Optional[float] = None
    dbp_mean: Optional[float] = None
    spo2_min: Optional[float] = None
    spo2_max: Optional[float] = None
    spo2_mean: Optional[float] = None
    temp_min_c: Optional[float] = None
    temp_max_c: Optional[float] = None
    resp_rate_min: Optional[float] = None
    resp_rate_max: Optional[float] = None
    resp_rate_mean: Optional[float] = None
    weight_kg: Optional[float] = None

    def to_text(self) -> str:
        date_str = self.window_start.strftime('%Y-%m-%d')
        lines = [f"[Vitals] {date_str}:"]
        if self.heart_rate_mean is not None:
            lines.append(f"  HR: {self.heart_rate_min:.0f}–{self.heart_rate_max:.0f} bpm "
                         f"(mean {self.heart_rate_mean:.0f})")
        if self.sbp_mean is not None:
            lines.append(f"  BP: {self.sbp_min:.0f}/{self.dbp_min:.0f}–"
                         f"{self.sbp_max:.0f}/{self.dbp_max:.0f} mmHg")
        if self.spo2_mean is not None:
            lines.append(f"  SpO2: {self.spo2_min:.0f}–{self.spo2_max:.0f}% "
                         f"(mean {self.spo2_mean:.0f}%)")
        if self.temp_min_c is not None:
            lines.append(f"  Temp: {self.temp_min_c:.1f}–{self.temp_max_c:.1f} °C")
        if self.resp_rate_mean is not None:
            lines.append(f"  RR: {self.resp_rate_min:.0f}–{self.resp_rate_max:.0f}/min")
        if self.weight_kg is not None:
            lines.append(f"  Weight: {self.weight_kg:.1f} kg")
        return "\n".join(lines)


class OMRVitals(BaseModel):
    chartdate: date
    seq_num: int
    result_name: str
    result_value: str

    def to_text(self) -> str:
        return (f"[Baseline {self.result_name}] {self.result_value} "
                f"(recorded {self.chartdate})")


# ============================================================
# SECTION 8b — Physician orders, ICU ingredients, ICU datetime events
# ============================================================

class PhysicianOrder(BaseModel):
    """
    poe.csv — Physician Order Entry.
    Every order placed by a physician during the admission.

    Most useful order_types for discharge summary:
      'Consults'    → which specialists were consulted (Cardiology, Nephrology, etc.)
      'Radiology'   → what imaging was ordered (X-ray, CT, Echo)
      'Cardiology'  → cardiology-specific orders
      'ADT orders'  → admit/discharge/transfer orders
      'Hemodialysis'→ dialysis orders
      'TPN'         → nutritional support

    Most useful order_subtypes:
      'Discharge'           → discharge planning orders (GOLD for follow-up section)
      'Code status'         → DNR/full code (critical clinical info)
      'CT Scan'             → CT imaging ordered
      'Mechanical Ventilation' → ventilator orders
      'Physical Therapy'    → rehab orders (useful for follow-up)
      'Consult'             → specialty consultation
    """
    poe_id: str
    ordertime: Optional[datetime] = None
    order_type: str
    order_subtype: Optional[str] = None
    transaction_type: Optional[str] = None   # 'New', 'Discontinue', 'Change'
    order_status: Optional[str] = None       # 'Active', 'Inactive'

    def to_text(self) -> str:
        subtype = f" — {self.order_subtype}" if self.order_subtype else ""
        time = (f" on {self.ordertime.strftime('%Y-%m-%d')}"
                if self.ordertime else "")
        status = f" [{self.order_status}]" if self.order_status else ""
        return f"[Order] {self.order_type}{subtype}{time}{status}"

    def is_consult(self) -> bool:
        return self.order_type.lower() in ('consults', 'cardiology',
                                           'neurology', 'critical care')

    def is_radiology(self) -> bool:
        return self.order_type.lower() == 'radiology'

    def is_discharge_planning(self) -> bool:
        return (self.order_subtype or '').lower() == 'discharge'

    def is_code_status(self) -> bool:
        return (self.order_subtype or '').lower() == 'code status'


class ICUIngredientEvent(BaseModel):
    """
    ingredientevents.csv + d_items.csv.
    Individual ingredients of compound ICU medications (TPN, compound drips).
    Links to inputevents via orderid — these are the components INSIDE
    a compounded medication bag (e.g., TPN = dextrose + amino acids + lipids).
    Only 15 unique items in demo data — mostly TPN nutritional components.
    Clinically relevant: confirms patient was on nutritional support,
    shows TPN composition for metabolic context.
    """
    stay_id: int
    itemid: int
    label: str
    category: Optional[str] = None
    starttime: Optional[datetime] = None
    endtime: Optional[datetime] = None
    amount: Optional[float] = None
    amountuom: Optional[str] = None
    rate: Optional[float] = None
    rateuom: Optional[str] = None
    statusdescription: Optional[str] = None

    def to_text(self) -> str:
        amount_str = (f" {self.amount:.1f} {self.amountuom}"
                      if self.amount and self.amountuom else "")
        rate_str = (f" at {self.rate:.1f} {self.rateuom}"
                    if self.rate and self.rateuom else "")
        time_str = (f" from {self.starttime.strftime('%Y-%m-%d %H:%M')}"
                    if self.starttime else "")
        return f"[ICU Ingredient] {self.label}{amount_str}{rate_str}{time_str}"


class ICUDatetimeEvent(BaseModel):
    """
    datetimeevents.csv + d_items.csv.
    ICU events recorded as date/time values (not numeric).
    The `value` field IS the datetime of the clinical event.

    Examples (87 unique items in demo data):
      - Foley Catheter insertion date
      - Arterial line start date
      - Subglottic suction start
      - Line removal dates
    Complements procedureevents with exact event timestamps.
    Useful for hospital course timeline reconstruction.
    """
    stay_id: int
    itemid: int
    label: str
    category: Optional[str] = None
    charttime: Optional[datetime] = None  # when it was charted
    value: Optional[datetime] = None      # the actual event datetime
    valueuom: Optional[str] = None

    def to_text(self) -> str:
        val_str = (self.value.strftime('%Y-%m-%d %H:%M')
                   if self.value else "N/A")
        chart_str = (f" (charted {self.charttime.strftime('%Y-%m-%d')})"
                     if self.charttime else "")
        return f"[ICU Timeline] {self.label}: {val_str}{chart_str}"


# ============================================================
# SECTION 9 — Clinical notes placeholder
# ============================================================

class ClinicalNote(BaseModel):
    note_id: str
    note_type: str
    note_seq: Optional[int] = None
    charttime: Optional[datetime] = None
    chartdate: Optional[date] = None
    text: str
    author_role: Optional[str] = None
    is_error: Optional[int] = None

    def to_text(self) -> str:
        return self.text

    def word_count(self) -> int:
        return len(self.text.split())

    def is_discharge_note(self) -> bool:
        return self.note_type.lower() in ('discharge', 'discharge summary')


# ============================================================
# SECTION 10 — Top-level container
# ============================================================

class EncounterDocument(BaseModel):
    """
    Single source of truth for one hospital admission.
    All MIMIC-IV structured tables consolidated into one typed object.
    """
    hadm_id: int
    subject_id: int
    patient: PatientDemographics
    admission: AdmissionInfo

    # Diagnoses, procedures, DRG
    diagnoses: list[Diagnosis] = []
    procedures: list[Procedure] = []
    drg_codes: list[DRGCode] = []

    # Medications — 3 sources ranked by accuracy
    medications: list[Medication] = []                           # prescribed
    medication_administrations: list[MedicationAdministration] = []  # actually given
    pharmacy_records: list[PharmacyRecord] = []                 # dispensed

    # Labs and microbiology
    lab_results: list[LabResult] = []
    microbiology: list[MicrobiologyResult] = []

    # ICU data
    icu_stays: list[ICUStay] = []
    icu_inputs: list[ICUInputEvent] = []
    daily_fluid_balance: list[DailyFluidBalance] = []
    icu_procedure_events: list[ICUProcedureEvent] = []
    icu_ingredients: list[ICUIngredientEvent] = []
    icu_datetime_events: list[ICUDatetimeEvent] = []
    vital_summaries: list[VitalSignsSummary] = []

    # Physician orders
    physician_orders: list[PhysicianOrder] = []

    # Ward and service
    services: list[ServiceTransfer] = []
    hospital_transfers: list[HospitalTransfer] = []

    # Outpatient baseline
    omr_vitals: list[OMRVitals] = []

    # Notes (empty until CITI access)
    notes: list[ClinicalNote] = []

    # ---- Properties ----

    @property
    def los_days(self) -> Optional[int]:
        return self.admission.los_days()

    @property
    def died_during_admission(self) -> bool:
        return bool(self.admission.hospital_expire_flag)

    @property
    def primary_diagnosis(self) -> Optional[Diagnosis]:
        primary = [d for d in self.diagnoses if d.seq_num == 1]
        return primary[0] if primary else (self.diagnoses[0] if self.diagnoses else None)

    @property
    def primary_service(self) -> Optional[str]:
        if not self.services:
            return None
        sorted_svcs = sorted(self.services,
                             key=lambda s: s.transfertime or datetime.min)
        return sorted_svcs[-1].service_name()

    # ---- Filtering helpers ----

    def has_notes(self) -> bool:
        return len(self.notes) > 0

    def get_abnormal_labs(self) -> list[LabResult]:
        return [l for l in self.lab_results if l.is_abnormal()]

    def get_critical_labs(self) -> list[LabResult]:
        return [l for l in self.lab_results if l.is_critical()]

    def get_labs_by_name(self, name: str) -> list[LabResult]:
        name_lower = name.lower()
        return [l for l in self.lab_results if name_lower in l.label.lower()]

    def get_discharge_meds(self) -> list[Medication]:
        """Prescription-based — fallback when EMAR not available."""
        if not self.admission.dischtime:
            return self.medications
        return [m for m in self.medications
                if m.stoptime is None or m.stoptime >= self.admission.dischtime]

    def get_actual_discharge_meds(self) -> list[MedicationAdministration]:
        """
        EMAR-based — MOST ACCURATE.
        Medications actually administered in the 48h before discharge.
        """
        if not self.medication_administrations or not self.admission.dischtime:
            return []
        cutoff = self.admission.dischtime - timedelta(hours=48)
        return [m for m in self.medication_administrations
                if m.was_administered()
                and m.charttime
                and m.charttime >= cutoff]

    def get_vasopressors(self) -> list[ICUInputEvent]:
        keywords = ['norepinephrine', 'epinephrine', 'dopamine', 'vasopressin',
                    'phenylephrine', 'dobutamine', 'milrinone']
        return [i for i in self.icu_inputs
                if any(k in i.label.lower() for k in keywords)]

    def get_consult_orders(self) -> list[PhysicianOrder]:
        return [o for o in self.physician_orders if o.is_consult()]

    def get_radiology_orders(self) -> list[PhysicianOrder]:
        return [o for o in self.physician_orders if o.is_radiology()]

    def get_discharge_planning_orders(self) -> list[PhysicianOrder]:
        return [o for o in self.physician_orders if o.is_discharge_planning()]

    def get_code_status_orders(self) -> list[PhysicianOrder]:
        return [o for o in self.physician_orders if o.is_code_status()]

    def get_unique_organisms(self) -> list[str]:
        seen: list[str] = []
        for mb in self.microbiology:
            if mb.org_name and mb.org_name not in seen:
                seen.append(mb.org_name)
        return seen

    def total_icu_days(self) -> float:
        return round(sum(s.los for s in self.icu_stays), 2)

    def was_on_icu(self) -> bool:
        return len(self.icu_stays) > 0

    def was_intubated(self) -> bool:
        return any('intubat' in p.label.lower() or 'ventilat' in p.label.lower()
                   for p in self.icu_procedure_events)

    def was_on_vasopressors(self) -> bool:
        return len(self.get_vasopressors()) > 0

    # ---- RAG context builders ----

    def context_for_presenting_complaint(self) -> list[str]:
        chunks = []
        adm = self.admission
        chunks.append(
            f"[Admission] {self.patient.age_str()} admitted "
            f"{adm.admit_date_str()} as {adm.admission_type or 'unknown type'} "
            f"from {adm.admission_location or 'unknown location'}."
        )
        if self.primary_diagnosis:
            chunks.append(f"[Primary diagnosis] {self.primary_diagnosis.description}")
        if self.primary_service:
            chunks.append(f"[Admitting service] {self.primary_service}")
        for icu in self.icu_stays[:2]:
            chunks.append(icu.to_text())
        for dx in self.diagnoses[:8]:
            chunks.append(dx.to_text())
        for drg in self.drg_codes:
            chunks.append(drg.to_text())
        for t in self.hospital_transfers[:4]:
            chunks.append(t.to_text())
        # Code status is clinically critical for presenting context
        for o in self.get_code_status_orders():
            chunks.append(o.to_text())
        return chunks

    def context_for_hospital_course(self) -> list[str]:
        chunks = []
        for t in self.hospital_transfers:
            chunks.append(t.to_text())
        for svc in self.services:
            chunks.append(svc.to_text())
        for icu in self.icu_stays:
            chunks.append(icu.to_text())
        # Specialist consults — who was involved in care
        for o in self.get_consult_orders():
            chunks.append(o.to_text())
        # Radiology orders — imaging done
        for o in self.get_radiology_orders():
            chunks.append(o.to_text())
        # ICU procedure timeline
        for proc in self.icu_procedure_events:
            chunks.append(proc.to_text())
        # ICU datetime events — exact timestamps of clinical events
        for dte in self.icu_datetime_events:
            chunks.append(dte.to_text())
        for proc in self.procedures:
            chunks.append(proc.to_text())
        # Vasopressors — severity indicator
        for vp in self.get_vasopressors():
            chunks.append(vp.to_text())
        for inp in self.icu_inputs:
            chunks.append(inp.to_text())
        # TPN / nutritional support ingredients
        for ing in self.icu_ingredients:
            chunks.append(ing.to_text())
        for fb in self.daily_fluid_balance:
            chunks.append(fb.to_text())
        for lab in self.get_critical_labs():
            chunks.append(lab.to_text())
        for lab in self.get_abnormal_labs()[:30]:
            chunks.append(lab.to_text())
        for mb in self.microbiology:
            chunks.append(mb.to_text())
        for vs in self.vital_summaries:
            chunks.append(vs.to_text())
        for dx in self.diagnoses:
            chunks.append(dx.to_text())
        return chunks

    def context_for_investigations(self) -> list[str]:
        chunks = []
        for lab in self.lab_results:
            chunks.append(lab.to_text())
        for mb in self.microbiology:
            chunks.append(mb.to_text())
        # Radiology orders — X-ray, CT, Echo ordered
        for o in self.get_radiology_orders():
            chunks.append(o.to_text())
        for vs in self.vital_summaries:
            chunks.append(vs.to_text())
        for fb in self.daily_fluid_balance:
            chunks.append(fb.to_text())
        for dte in self.icu_datetime_events:
            chunks.append(dte.to_text())
        for omr in self.omr_vitals:
            chunks.append(omr.to_text())
        for drg in self.drg_codes:
            chunks.append(drg.to_text())
        return chunks

    def context_for_discharge_medications(self) -> list[str]:
        chunks = []
        actual = self.get_actual_discharge_meds()
        if actual:
            for med in actual:
                chunks.append(med.to_text())
        for med in self.get_discharge_meds():
            chunks.append(med.to_text())
        for rx in self.pharmacy_records:
            if rx.is_active():
                chunks.append(rx.to_text())
        return chunks

    def context_for_followup(self) -> list[str]:
        chunks = []
        adm = self.admission
        if self.died_during_admission:
            chunks.append("[Outcome] Patient expired during this admission.")
        else:
            chunks.append(
                f"[Discharge] Discharged {adm.discharge_date_str()} "
                f"to {adm.discharge_location or 'unknown location'}."
            )
        # Discharge planning orders — GOLD for follow-up content
        for o in self.get_discharge_planning_orders():
            chunks.append(o.to_text())
        # Code status
        for o in self.get_code_status_orders():
            chunks.append(o.to_text())
        for svc in self.services:
            chunks.append(svc.to_text())
        # All consults — who needs follow-up
        for o in self.get_consult_orders():
            chunks.append(o.to_text())
        for dx in self.diagnoses[:12]:
            chunks.append(dx.to_text())
        actual = self.get_actual_discharge_meds()
        meds_to_use = actual if actual else self.get_discharge_meds()
        for med in meds_to_use:
            chunks.append(med.to_text())
        if self.was_on_icu():
            chunks.append(
                f"Patient required ICU care ({self.total_icu_days()} total ICU days).")
        if self.was_intubated():
            chunks.append("Patient required mechanical ventilation during admission.")
        if self.was_on_vasopressors():
            vp_names = list({v.label for v in self.get_vasopressors()})
            chunks.append(f"Vasopressor support required: {', '.join(vp_names)}.")
        return chunks

    def get_section_context(self, section: str) -> list[str]:
        dispatch = {
            'presenting_complaint':  self.context_for_presenting_complaint,
            'hospital_course':       self.context_for_hospital_course,
            'investigations':        self.context_for_investigations,
            'discharge_medications': self.context_for_discharge_medications,
            'followup':              self.context_for_followup,
        }
        fn = dispatch.get(section.lower().replace(' ', '_'))
        if fn is None:
            raise ValueError(
                f"Unknown section '{section}'. Valid: {list(dispatch.keys())}")
        return fn()

    def summary_stats(self) -> dict:
        return {
            'hadm_id':                      self.hadm_id,
            'subject_id':                   self.subject_id,
            'patient':                      self.patient.age_str(),
            'los_days':                     self.los_days,
            'died':                         self.died_during_admission,
            'primary_dx':                   (self.primary_diagnosis.description
                                             if self.primary_diagnosis else None),
            'primary_service':              self.primary_service,
            'n_diagnoses':                  len(self.diagnoses),
            'n_procedures':                 len(self.procedures),
            'n_labs':                       len(self.lab_results),
            'n_abnormal_labs':              len(self.get_abnormal_labs()),
            'n_critical_labs':              len(self.get_critical_labs()),
            'n_medications_prescribed':     len(self.medications),
            'n_emar_records':               len(self.medication_administrations),
            'n_actual_discharge_meds':      len(self.get_actual_discharge_meds()),
            'n_prescription_discharge_meds':len(self.get_discharge_meds()),
            'n_pharmacy_records':           len(self.pharmacy_records),
            'n_physician_orders':           len(self.physician_orders),
            'n_consult_orders':             len(self.get_consult_orders()),
            'n_radiology_orders':           len(self.get_radiology_orders()),
            'n_discharge_planning_orders':  len(self.get_discharge_planning_orders()),
            'code_status_documented':       len(self.get_code_status_orders()) > 0,
            'n_icu_inputs':                 len(self.icu_inputs),
            'n_icu_ingredients':            len(self.icu_ingredients),
            'n_icu_datetime_events':        len(self.icu_datetime_events),
            'vasopressors_used':            self.was_on_vasopressors(),
            'intubated':                    self.was_intubated(),
            'n_fluid_balance_days':         len(self.daily_fluid_balance),
            'n_icu_procedures':             len(self.icu_procedure_events),
            'n_micro_cultures':             len(self.microbiology),
            'unique_organisms':             self.get_unique_organisms(),
            'icu_stays':                    len(self.icu_stays),
            'total_icu_days':               self.total_icu_days(),
            'n_hospital_transfers':         len(self.hospital_transfers),
            'vital_summaries':              len(self.vital_summaries),
            'has_notes':                    self.has_notes(),
        }

    def __repr__(self) -> str:
        return (f"EncounterDocument(hadm_id={self.hadm_id}, "
                f"patient={self.patient.age_str()}, los={self.los_days}d, "
                f"dx={len(self.diagnoses)}, labs={len(self.lab_results)}, "
                f"emar={len(self.medication_administrations)}, "
                f"icu_inputs={len(self.icu_inputs)}, "
                f"icu_procs={len(self.icu_procedure_events)})")


# ============================================================
# SECTION 11 — Output schema
# ============================================================

class SectionDraft(BaseModel):
    section_name: str
    text: str
    chunk_ids_used: list[str] = []
    claim_citations: dict[str, list[str]] = {}
    entailment_rate: Optional[float] = None
    revision_count: int = 0
    needs_review: bool = False


# In models.py — replace the DischargeSummary class

class DischargeSummary(BaseModel):
    hadm_id: int
    generated_at: datetime

    # === SECTION 1: Auto-filled from structured data (no LLM needed) ===
    general_information: SectionDraft   # patient demographics, dates, consultant

    # === SECTION 2: LLM generated with citations ===
    diagnosis: SectionDraft             # primary + secondary diagnoses
    present_illness: SectionDraft       # HPI — why did patient come
    clinical_examination: SectionDraft  # vitals + systems on admission
    investigations: SectionDraft        # labs, imaging, cultures
    hospital_course: SectionDraft       # what happened, procedures, treatment

    # === SECTION 3: Advice on discharge ===
    discharge_medications: SectionDraft # drug | dose | frequency (1-0-1 format)
    diet_and_activity: SectionDraft     # dietary restrictions, physical activity
    follow_up: SectionDraft             # which doctor, when, pending tests
    warning_symptoms: SectionDraft      # red flags → templated, no LLM needed

    # === Metadata ===
    overall_entailment_rate: Optional[float] = None
    sections_needing_review: list[str] = []

    def all_sections(self) -> list[SectionDraft]:
        return [
            self.general_information, self.diagnosis,
            self.present_illness, self.clinical_examination,
            self.investigations, self.hospital_course,
            self.discharge_medications, self.diet_and_activity,
            self.follow_up, self.warning_symptoms,
        ]

    def is_ready_for_physician(self) -> bool:
        return len(self.sections_needing_review) == 0