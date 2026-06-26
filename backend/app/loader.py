import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import duckdb  #for joining
import pandas as pd

from .models import (
    AdmissionInfo, AntibioticSensitivity, ClinicalNote,
    DRGCode, DailyFluidBalance, Diagnosis,
    EncounterDocument, HospitalTransfer, ICUDatetimeEvent,
    ICUIngredientEvent, ICUInputEvent,
    ICUProcedureEvent, ICUStay, LabResult,
    Medication, MedicationAdministration, MicrobiologyResult,
    OMRVitals, PatientDemographics, PharmacyRecord,
    PhysicianOrder, Procedure, ServiceTransfer, VitalSignsSummary,
)

logger = logging.getLogger(__name__)

VITAL_ITEMIDS: dict[str, list[int]] = {
    "heart_rate": [220045],
    "sbp":        [220179, 220050],
    "dbp":        [220180, 220051],
    "spo2":       [220277],
    "resp_rate":  [220210],
    "temp_c":     [223762],
    "temp_f":     [223761],
    "weight_kg":  [224639, 226512],
}
ALL_VITAL_ITEMIDS: list[int] = [i for ids in VITAL_ITEMIDS.values() for i in ids]

# Urine output item IDs (Foley, Void, Suprapubic, etc.)
URINE_ITEMIDS: set[int] = {226559, 226560, 226561, 226563, 226584, 227488, 227489}



def _to_date(val) -> Optional[date]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    try:
        return pd.to_datetime(val).date()
    except Exception:
        return None


def _to_datetime(val) -> Optional[datetime]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, datetime):
        return val
    try:
        return pd.to_datetime(val).to_pydatetime()
    except Exception:
        return None


def _str_or_none(val) -> Optional[str]:
    if val is None:
        return None
    s = str(val).strip()
    return s if s and s.lower() not in ("none", "nan", "nat", "") else None


def _float_or_none(val) -> Optional[float]:
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def _int_or_none(val) -> Optional[int]:
    try:
        return int(val) if val is not None else None
    except (TypeError, ValueError):
        return None

class MIMICLoader:
    """
    Loads all available MIMIC-IV data for a single hospital admission
    and returns a fully typed EncounterDocument.

    Args:
        data_path: Root folder containing hosp/ and icu/ subdirectories.
    """

    def __init__(self, data_path: str) -> None:
        self.data_path = Path(data_path)
        self.hosp = self.data_path / "hosp"
        self.icu  = self.data_path / "icu"
        self.con  = duckdb.connect()

        if not self.hosp.exists():
            raise FileNotFoundError(
                f"hosp/ not found at {self.hosp}. "
                "Check data_path points to the folder containing hosp/ and icu/."
            )

        # Cached lookup tables — loaded once, used for every encounter
        self._d_icd_diagnoses:  Optional[pd.DataFrame] = None
        self._d_icd_procedures: Optional[pd.DataFrame] = None
        self._d_labitems:       Optional[pd.DataFrame] = None
        self._d_items:          Optional[pd.DataFrame] = None  # ICU item lookup

        logger.info(f"MIMICLoader ready — {self.data_path}")

    # ----------------------------------------------------------------
    # Path helpers
    # ----------------------------------------------------------------

    def _p(self, *parts: str) -> str:
        """Forward-slash path string safe for DuckDB SQL on Windows."""
        return str(self.data_path.joinpath(*parts)).replace("\\", "/")

    def _hosp(self, f: str) -> str:
        return f"read_csv_auto('{self._p('hosp', f)}')"

    def _icu(self, f: str) -> str:
        return f"read_csv_auto('{self._p('icu', f)}')"

    # ----------------------------------------------------------------
    # Cached lookup tables
    # ----------------------------------------------------------------

    def _get_d_items(self) -> pd.DataFrame:
        """d_items.csv — labels for ICU inputevents, outputevents, procedureevents."""
        if self._d_items is None:
            path = self.icu / "d_items.csv"
            if path.exists():
                self._d_items = pd.read_csv(path, low_memory=False)
            else:
                self._d_items = pd.DataFrame(columns=['itemid', 'label', 'category'])
        return self._d_items

    #load metadata of a patient 
    def load_encounter(self, hadm_id: int) -> EncounterDocument:
        """
        Load all available data for one hospital admission.
        Empty lists are returned for tables with no rows — not an error.

        Raises:
            ValueError  if hadm_id not found in admissions.csv
        """
        logger.info(f"Loading hadm_id={hadm_id}")

        admission  = self._load_admission(hadm_id)
        patient    = self._load_patient(admission.subject_id)
        diagnoses  = self._load_diagnoses(hadm_id)
        procedures = self._load_procedures(hadm_id)
        drg_codes  = self._load_drg_codes(hadm_id)
        labs       = self._load_labs(hadm_id)
        meds       = self._load_medications(hadm_id)
        emar       = self._load_emar(hadm_id)
        pharmacy   = self._load_pharmacy(hadm_id)
        micro      = self._load_microbiology(hadm_id)
        icu_stays  = self._load_icu_stays(hadm_id)
        icu_inputs = self._load_icu_inputs(hadm_id)
        fluid_bal  = self._load_daily_fluid_balance(hadm_id)
        icu_procs  = self._load_icu_procedure_events(hadm_id)
        icu_ingr   = self._load_icu_ingredients(hadm_id)
        icu_dts    = self._load_icu_datetime_events(hadm_id)
        poe        = self._load_physician_orders(hadm_id)
        vitals     = self._load_vital_summaries(hadm_id)
        services   = self._load_services(hadm_id)
        transfers  = self._load_hospital_transfers(hadm_id)
        omr        = self._load_omr_vitals(admission.subject_id)
        notes      = self._load_notes(hadm_id)

        enc = EncounterDocument(
            hadm_id=hadm_id,
            subject_id=admission.subject_id,
            patient=patient,
            admission=admission,
            diagnoses=diagnoses,
            procedures=procedures,
            drg_codes=drg_codes,
            lab_results=labs,
            medications=meds,
            medication_administrations=emar,
            pharmacy_records=pharmacy,
            microbiology=micro,
            icu_stays=icu_stays,
            icu_inputs=icu_inputs,
            daily_fluid_balance=fluid_bal,
            icu_procedure_events=icu_procs,
            icu_ingredients=icu_ingr,
            icu_datetime_events=icu_dts,
            physician_orders=poe,
            vital_summaries=vitals,
            services=services,
            hospital_transfers=transfers,
            omr_vitals=omr,
            notes=notes,
        )
        logger.info(f"Loaded {enc}")
        return enc

    def load_all(self, hadm_ids: list[int]) -> dict[int, EncounterDocument]:
        result: dict[int, EncounterDocument] = {}
        for hadm_id in hadm_ids:
            try:
                result[hadm_id] = self.load_encounter(hadm_id)
            except Exception as exc:
                logger.error(f"Failed hadm_id={hadm_id}: {exc}")
        return result

    def validate_files(self) -> dict[str, bool]:
        expected = [
            ("hosp", "admissions.csv"), ("hosp", "patients.csv"),
            ("hosp", "diagnoses_icd.csv"), ("hosp", "d_icd_diagnoses.csv"),
            ("hosp", "procedures_icd.csv"), ("hosp", "d_icd_procedures.csv"),
            ("hosp", "labevents.csv"), ("hosp", "d_labitems.csv"),
            ("hosp", "prescriptions.csv"), ("hosp", "emar.csv"),
            ("hosp", "emar_detail.csv"), ("hosp", "pharmacy.csv"),
            ("hosp", "microbiologyevents.csv"), ("hosp", "services.csv"),
            ("hosp", "drgcodes.csv"), ("hosp", "omr.csv"),
            ("hosp", "transfers.csv"),
            ("icu", "icustays.csv"), ("icu", "chartevents.csv"),
            ("icu", "inputevents.csv"), ("icu", "outputevents.csv"),
            ("icu", "procedureevents.csv"), ("icu", "d_items.csv"),
            ("icu", "ingredientevents.csv"), ("icu", "datetimeevents.csv"),
            ("hosp", "poe.csv"),
        ]
        status = {f"{folder}/{fname}": (self.data_path / folder / fname).exists()
                  for folder, fname in expected}
        status["note/discharge.csv"] = (self.data_path / "note" / "discharge.csv").exists()
        missing = [k for k, v in status.items() if not v]
        if missing:
            logger.warning(f"Missing files: {missing}")
        return status

    # ----------------------------------------------------------------
    # Admission and patient
    # ----------------------------------------------------------------

    def _load_admission(self, hadm_id: int) -> AdmissionInfo:
        row = self.con.execute(f"""
            SELECT subject_id, admittime, dischtime, deathtime,
                   admission_type, admit_provider_id, admission_location,
                   discharge_location, insurance, language, marital_status,
                   race, edregtime, edouttime, hospital_expire_flag
            FROM {self._hosp('admissions.csv')}
            WHERE hadm_id = {hadm_id}
        """).fetchone()
        if row is None:
            raise ValueError(f"hadm_id {hadm_id} not found in admissions.csv")
        return AdmissionInfo(
            hadm_id=hadm_id, subject_id=int(row[0]),
            admittime=_to_datetime(row[1]), dischtime=_to_datetime(row[2]),
            deathtime=_to_datetime(row[3]), admission_type=_str_or_none(row[4]),
            admit_provider_id=_str_or_none(row[5]),
            admission_location=_str_or_none(row[6]),
            discharge_location=_str_or_none(row[7]),
            insurance=_str_or_none(row[8]), language=_str_or_none(row[9]),
            marital_status=_str_or_none(row[10]), race=_str_or_none(row[11]),
            edregtime=_to_datetime(row[12]), edouttime=_to_datetime(row[13]),
            hospital_expire_flag=int(row[14]) if row[14] is not None else 0,
        )

    def _load_patient(self, subject_id: int) -> PatientDemographics:
        row = self.con.execute(f"""
            SELECT subject_id, gender, anchor_age, anchor_year,
                   anchor_year_group, dod
            FROM {self._hosp('patients.csv')}
            WHERE subject_id = {subject_id}
        """).fetchone()
        if row is None:
            raise ValueError(f"subject_id {subject_id} not found in patients.csv")
        return PatientDemographics(
            subject_id=int(row[0]), gender=str(row[1]),
            anchor_age=int(row[2]), anchor_year=int(row[3]),
            anchor_year_group=str(row[4]), dod=_to_date(row[5]),
        )

    # ----------------------------------------------------------------
    # Diagnoses, procedures, DRG
    # ----------------------------------------------------------------

    def _load_diagnoses(self, hadm_id: int) -> list[Diagnosis]:
        rows = self.con.execute(f"""
            SELECT d.icd_code, d.icd_version, d.seq_num,
                   COALESCE(i.long_title, 'Description unavailable')
            FROM {self._hosp('diagnoses_icd.csv')} d
            LEFT JOIN {self._hosp('d_icd_diagnoses.csv')} i
                   ON d.icd_code = i.icd_code AND d.icd_version = i.icd_version
            WHERE d.hadm_id = {hadm_id}
            ORDER BY d.seq_num
        """).fetchall()
        return [Diagnosis(icd_code=str(r[0]), icd_version=int(r[1]),
                          seq_num=int(r[2]), description=str(r[3]))
                for r in rows]

    def _load_procedures(self, hadm_id: int) -> list[Procedure]:
        rows = self.con.execute(f"""
            SELECT p.icd_code, p.icd_version, p.seq_num,
                   COALESCE(i.long_title, 'Description unavailable'), p.chartdate
            FROM {self._hosp('procedures_icd.csv')} p
            LEFT JOIN {self._hosp('d_icd_procedures.csv')} i
                   ON p.icd_code = i.icd_code AND p.icd_version = i.icd_version
            WHERE p.hadm_id = {hadm_id}
            ORDER BY p.seq_num
        """).fetchall()
        return [Procedure(icd_code=str(r[0]), icd_version=int(r[1]),
                          seq_num=int(r[2]), description=str(r[3]),
                          chartdate=_to_date(r[4]))
                for r in rows]

    def _load_drg_codes(self, hadm_id: int) -> list[DRGCode]:
        rows = self.con.execute(f"""
            SELECT drg_type, drg_code, description, drg_severity, drg_mortality
            FROM {self._hosp('drgcodes.csv')}
            WHERE hadm_id = {hadm_id}
        """).fetchall()
        return [DRGCode(drg_type=str(r[0]), drg_code=int(r[1]),
                        description=str(r[2]), drg_severity=_int_or_none(r[3]),
                        drg_mortality=_int_or_none(r[4]))
                for r in rows]

    # ----------------------------------------------------------------
    # Labs
    # ----------------------------------------------------------------

    def _load_labs(self, hadm_id: int) -> list[LabResult]:
        rows = self.con.execute(f"""
            SELECT l.labevent_id, l.itemid,
                   COALESCE(d.label, 'Unknown') AS label,
                   d.fluid, d.category,
                   l.charttime, l.value, l.valuenum, l.valueuom,
                   l.ref_range_lower, l.ref_range_upper, l.flag, l.priority
            FROM {self._hosp('labevents.csv')} l
            LEFT JOIN {self._hosp('d_labitems.csv')} d ON l.itemid = d.itemid
            WHERE l.hadm_id = {hadm_id}
            ORDER BY l.charttime
        """).fetchall()
        results = []
        for r in rows:
            try:
                results.append(LabResult(
                    labevent_id=int(r[0]), itemid=int(r[1]), label=str(r[2]),
                    fluid=_str_or_none(r[3]), category=_str_or_none(r[4]),
                    charttime=_to_datetime(r[5]), value=_str_or_none(r[6]),
                    valuenum=_float_or_none(r[7]), valueuom=_str_or_none(r[8]),
                    ref_range_lower=_float_or_none(r[9]),
                    ref_range_upper=_float_or_none(r[10]),
                    flag=_str_or_none(r[11]), priority=_str_or_none(r[12]),
                ))
            except Exception as exc:
                logger.warning(f"Skipping lab row: {exc}")
        return results

    # ----------------------------------------------------------------
    # Medications — 3 sources
    # ----------------------------------------------------------------

    def _load_medications(self, hadm_id: int) -> list[Medication]:
        """From prescriptions.csv — prescribed medications."""
        rows = self.con.execute(f"""
            SELECT drug, drug_type, prod_strength,
                   dose_val_rx, dose_unit_rx,
                   form_val_disp, form_unit_disp,
                   doses_per_24_hrs, route, starttime, stoptime
            FROM {self._hosp('prescriptions.csv')}
            WHERE hadm_id = {hadm_id} AND drug IS NOT NULL
            ORDER BY starttime
        """).fetchall()
        return [Medication(
            drug=str(r[0]), drug_type=_str_or_none(r[1]),
            prod_strength=_str_or_none(r[2]), dose_val_rx=_str_or_none(r[3]),
            dose_unit_rx=_str_or_none(r[4]), form_val_disp=_str_or_none(r[5]),
            form_unit_disp=_str_or_none(r[6]),
            doses_per_24_hrs=_float_or_none(r[7]),
            route=_str_or_none(r[8]), starttime=_to_datetime(r[9]),
            stoptime=_to_datetime(r[10]),
        ) for r in rows]

    def _load_emar(self, hadm_id: int) -> list[MedicationAdministration]:
        """
        From emar.csv + emar_detail.csv — actually administered medications.
        Joins emar with emar_detail on emar_id to get dose and route info.
        Takes the first emar_detail row per emar record (lowest parent_field_ordinal).
        """
        emar_df = self.con.execute(f"""
            SELECT emar_id, charttime, medication, event_txt
            FROM {self._hosp('emar.csv')}
            WHERE hadm_id = {hadm_id}
            ORDER BY charttime
        """).df()

        if emar_df.empty:
            return []

        # Load emar_detail for these emar_ids
        emar_ids = emar_df['emar_id'].tolist()
        emar_ids_sql = ", ".join(f"'{e}'" for e in emar_ids)

        try:
            detail_df = self.con.execute(f"""
                SELECT emar_id, dose_given, dose_given_unit,
                       route, infusion_rate, infusion_rate_unit
                FROM {self._hosp('emar_detail.csv')}
                WHERE emar_id IN ({emar_ids_sql})
                QUALIFY ROW_NUMBER() OVER (PARTITION BY emar_id
                                           ORDER BY parent_field_ordinal) = 1
            """).df()
        except Exception:
            # QUALIFY not supported in older DuckDB — fallback
            try:
                detail_df = self.con.execute(f"""
                    SELECT emar_id, dose_given, dose_given_unit,
                           route, infusion_rate, infusion_rate_unit
                    FROM {self._hosp('emar_detail.csv')}
                    WHERE emar_id IN ({emar_ids_sql})
                """).df()
                detail_df = detail_df.groupby('emar_id').first().reset_index()
            except Exception as exc:
                logger.warning(f"emar_detail join failed: {exc}")
                detail_df = pd.DataFrame(
                    columns=['emar_id', 'dose_given', 'dose_given_unit',
                             'route', 'infusion_rate', 'infusion_rate_unit'])

        merged = emar_df.merge(detail_df, on='emar_id', how='left')

        results = []
        for _, row in merged.iterrows():
            try:
                results.append(MedicationAdministration(
                    emar_id=str(row['emar_id']),
                    charttime=_to_datetime(row.get('charttime')),
                    medication=str(row['medication']),
                    event_txt=_str_or_none(row.get('event_txt')),
                    dose_given=_str_or_none(row.get('dose_given')),
                    dose_given_unit=_str_or_none(row.get('dose_given_unit')),
                    route=_str_or_none(row.get('route')),
                    infusion_rate=_str_or_none(row.get('infusion_rate')),
                    infusion_rate_unit=_str_or_none(row.get('infusion_rate_unit')),
                ))
            except Exception as exc:
                logger.warning(f"Skipping emar row: {exc}")
        return results

    def _load_pharmacy(self, hadm_id: int) -> list[PharmacyRecord]:
        """From pharmacy.csv — pharmacy dispensing records."""
        rows = self.con.execute(f"""
            SELECT pharmacy_id, medication, status, route,
                   frequency, doses_per_24_hrs,
                   starttime, stoptime, dispensation
            FROM {self._hosp('pharmacy.csv')}
            WHERE hadm_id = {hadm_id}
              AND medication IS NOT NULL
            ORDER BY starttime
        """).fetchall()
        return [PharmacyRecord(
            pharmacy_id=int(r[0]), medication=str(r[1]),
            status=_str_or_none(r[2]), route=_str_or_none(r[3]),
            frequency=_str_or_none(r[4]), doses_per_24_hrs=_float_or_none(r[5]),
            starttime=_to_datetime(r[6]), stoptime=_to_datetime(r[7]),
            dispensation=_str_or_none(r[8]),
        ) for r in rows]

    # ----------------------------------------------------------------
    # Microbiology
    # ----------------------------------------------------------------

    def _load_microbiology(self, hadm_id: int) -> list[MicrobiologyResult]:
        df = self.con.execute(f"""
            SELECT microevent_id, micro_specimen_id, chartdate, charttime,
                   spec_type_desc, test_name, org_name, isolate_num, quantity,
                   ab_name, dilution_text, interpretation
            FROM {self._hosp('microbiologyevents.csv')}
            WHERE hadm_id = {hadm_id}
            ORDER BY chartdate, micro_specimen_id, org_name, ab_name
        """).df()

        if df.empty:
            return []

        results = []
        for (specimen_id, org_name), grp in df.groupby(
                ['micro_specimen_id', 'org_name'], dropna=False):
            first = grp.iloc[0]
            sensitivities = [
                AntibioticSensitivity(
                    ab_name=str(ab_row['ab_name']),
                    interpretation=_str_or_none(ab_row.get('interpretation')),
                    dilution_text=_str_or_none(ab_row.get('dilution_text')),
                )
                for _, ab_row in grp.iterrows()
                if pd.notna(ab_row.get('ab_name'))
            ]
            try:
                results.append(MicrobiologyResult(
                    microevent_id=int(first['microevent_id']),
                    micro_specimen_id=_int_or_none(
                        specimen_id if pd.notna(specimen_id) else None),
                    chartdate=_to_date(first['chartdate']),
                    charttime=_to_datetime(first['charttime']),
                    spec_type_desc=_str_or_none(first['spec_type_desc']),
                    test_name=_str_or_none(first['test_name']),
                    org_name=_str_or_none(
                        org_name if pd.notna(org_name) else None),
                    isolate_num=_int_or_none(first.get('isolate_num')),
                    quantity=_str_or_none(first.get('quantity')),
                    sensitivities=sensitivities,
                ))
            except Exception as exc:
                logger.warning(f"Skipping micro result: {exc}")
        return results

    # ----------------------------------------------------------------
    # ICU events (NEW)
    # ----------------------------------------------------------------

    def _load_icu_inputs(self, hadm_id: int) -> list[ICUInputEvent]:
        """
        From inputevents.csv + d_items.csv.
        Loads all ICU IV inputs — medications, fluids, blood products.
        Label and category come from d_items lookup.
        """
        if not (self.icu / "inputevents.csv").exists():
            return []

        d_items = self._get_d_items()
        items_dict = (d_items.set_index('itemid')[['label', 'category']]
                      .to_dict('index'))

        rows = self.con.execute(f"""
            SELECT stay_id, itemid, starttime, endtime,
                   amount, amountuom, rate, rateuom,
                   ordercategoryname, totalamount, totalamountuom,
                   statusdescription
            FROM {self._icu('inputevents.csv')}
            WHERE hadm_id = {hadm_id}
            ORDER BY starttime
        """).fetchall()

        results = []
        for r in rows:
            try:
                itemid = int(r[1])
                item_info = items_dict.get(itemid, {})
                results.append(ICUInputEvent(
                    stay_id=int(r[0]), itemid=itemid,
                    label=item_info.get('label', f'Item {itemid}'),
                    category=_str_or_none(item_info.get('category')),
                    starttime=_to_datetime(r[2]), endtime=_to_datetime(r[3]),
                    amount=_float_or_none(r[4]), amountuom=_str_or_none(r[5]),
                    rate=_float_or_none(r[6]), rateuom=_str_or_none(r[7]),
                    ordercategoryname=_str_or_none(r[8]),
                    totalamount=_float_or_none(r[9]),
                    totalamountuom=_str_or_none(r[10]),
                    statusdescription=_str_or_none(r[11]),
                ))
            except Exception as exc:
                logger.warning(f"Skipping inputevent row: {exc}")
        return results

    def _load_daily_fluid_balance(self, hadm_id: int) -> list[DailyFluidBalance]:
        """
        From outputevents.csv — aggregated daily fluid output.
        Separates urine output from other outputs (drains, tubes, etc.).
        """
        if not (self.icu / "outputevents.csv").exists():
            return []

        df = self.con.execute(f"""
            SELECT charttime, itemid, value, valueuom
            FROM {self._icu('outputevents.csv')}
            WHERE hadm_id = {hadm_id}
              AND value IS NOT NULL AND value > 0
            ORDER BY charttime
        """).df()

        if df.empty:
            return []

        df['charttime'] = pd.to_datetime(df['charttime'])
        df['day'] = df['charttime'].dt.date

        results = []
        for day, day_df in df.groupby('day'):
            urine = day_df[day_df['itemid'].isin(URINE_ITEMIDS)]['value'].sum()
            total = day_df['value'].sum()
            other = total - urine
            results.append(DailyFluidBalance(
                date=day,
                urine_output_ml=round(float(urine), 0) if urine > 0 else None,
                other_output_ml=round(float(other), 0) if other > 0 else None,
                total_output_ml=round(float(total), 0) if total > 0 else None,
            ))
        return results

    def _load_icu_procedure_events(self, hadm_id: int) -> list[ICUProcedureEvent]:
        """
        From procedureevents.csv + d_items.csv.
        ICU bedside procedures: intubation, extubation, lines, dialysis, etc.
        """
        if not (self.icu / "procedureevents.csv").exists():
            return []

        d_items = self._get_d_items()
        items_dict = (d_items.set_index('itemid')[['label', 'category']]
                      .to_dict('index'))

        rows = self.con.execute(f"""
            SELECT stay_id, itemid, starttime, endtime,
                   value, valueuom, ordercategoryname, location
            FROM {self._icu('procedureevents.csv')}
            WHERE hadm_id = {hadm_id}
            ORDER BY starttime
        """).fetchall()

        results = []
        for r in rows:
            try:
                itemid = int(r[1])
                item_info = items_dict.get(itemid, {})
                results.append(ICUProcedureEvent(
                    stay_id=int(r[0]), itemid=itemid,
                    label=item_info.get('label', f'Procedure {itemid}'),
                    category=_str_or_none(item_info.get('category')),
                    starttime=_to_datetime(r[2]), endtime=_to_datetime(r[3]),
                    value=_float_or_none(r[4]), valueuom=_str_or_none(r[5]),
                    ordercategoryname=_str_or_none(r[6]),
                    location=_str_or_none(r[7]),
                ))
            except Exception as exc:
                logger.warning(f"Skipping procedureevents row: {exc}")
        return results

    # ----------------------------------------------------------------
    # ICU stays and ward
    # ----------------------------------------------------------------

    def _load_icu_stays(self, hadm_id: int) -> list[ICUStay]:
        if not (self.icu / "icustays.csv").exists():
            return []
        rows = self.con.execute(f"""
            SELECT stay_id, first_careunit, last_careunit, intime, outtime, los
            FROM {self._icu('icustays.csv')}
            WHERE hadm_id = {hadm_id}
            ORDER BY intime
        """).fetchall()
        return [ICUStay(stay_id=int(r[0]), first_careunit=str(r[1]),
                        last_careunit=str(r[2]), intime=_to_datetime(r[3]),
                        outtime=_to_datetime(r[4]), los=float(r[5]))
                for r in rows]

    def _load_services(self, hadm_id: int) -> list[ServiceTransfer]:
        rows = self.con.execute(f"""
            SELECT transfertime, prev_service, curr_service
            FROM {self._hosp('services.csv')}
            WHERE hadm_id = {hadm_id}
            ORDER BY transfertime
        """).fetchall()
        return [ServiceTransfer(transfertime=_to_datetime(r[0]),
                                prev_service=_str_or_none(r[1]),
                                curr_service=str(r[2]))
                for r in rows]

    def _load_hospital_transfers(self, hadm_id: int) -> list[HospitalTransfer]:
        """
        From transfers.csv — full patient journey (ED → floor → ICU → discharge).
        Sorted by intime to show chronological journey.
        """
        rows = self.con.execute(f"""
            SELECT transfer_id, eventtype, careunit, intime, outtime
            FROM {self._hosp('transfers.csv')}
            WHERE hadm_id = {hadm_id}
            ORDER BY intime
        """).fetchall()
        results = []
        for r in rows:
            try:
                results.append(HospitalTransfer(
                    transfer_id=int(r[0]), eventtype=str(r[1]),
                    careunit=_str_or_none(r[2]),
                    intime=_to_datetime(r[3]), outtime=_to_datetime(r[4]),
                ))
            except Exception as exc:
                logger.warning(f"Skipping transfer row: {exc}")
        return results

    # ----------------------------------------------------------------
    # Vital signs
    # ----------------------------------------------------------------

    def _load_vital_summaries(self, hadm_id: int) -> list[VitalSignsSummary]:
        if not (self.icu / "chartevents.csv").exists():
            return []

        itemids_sql = ", ".join(str(i) for i in ALL_VITAL_ITEMIDS)
        df = self.con.execute(f"""
            SELECT itemid, charttime, valuenum
            FROM {self._icu('chartevents.csv')}
            WHERE hadm_id = {hadm_id}
              AND itemid IN ({itemids_sql})
              AND valuenum IS NOT NULL AND valuenum > 0
            ORDER BY charttime
        """).df()

        if df.empty:
            return []

        df['charttime'] = pd.to_datetime(df['charttime'])
        # Convert F → C
        f_mask = df['itemid'].isin(VITAL_ITEMIDS['temp_f'])
        df.loc[f_mask, 'valuenum'] = (df.loc[f_mask, 'valuenum'] - 32) * 5 / 9
        df.loc[f_mask, 'itemid'] = 223762
        df['day'] = df['charttime'].dt.floor('D')

        def _agg(day_df, itemids):
            vals = day_df.loc[day_df['itemid'].isin(itemids), 'valuenum']
            if vals.empty:
                return None, None, None
            return (round(float(vals.min()), 1),
                    round(float(vals.max()), 1),
                    round(float(vals.mean()), 1))

        summaries = []
        for day, day_df in df.groupby('day'):
            hr_min, hr_max, hr_mean   = _agg(day_df, VITAL_ITEMIDS['heart_rate'])
            sb_min, sb_max, sb_mean   = _agg(day_df, VITAL_ITEMIDS['sbp'])
            db_min, db_max, db_mean   = _agg(day_df, VITAL_ITEMIDS['dbp'])
            sp_min, sp_max, sp_mean   = _agg(day_df, VITAL_ITEMIDS['spo2'])
            rr_min, rr_max, rr_mean   = _agg(day_df, VITAL_ITEMIDS['resp_rate'])
            tc_min, tc_max, _         = _agg(day_df, VITAL_ITEMIDS['temp_c'])
            w_vals = day_df.loc[day_df['itemid'].isin(
                VITAL_ITEMIDS['weight_kg']), 'valuenum']
            weight = round(float(w_vals.iloc[0]), 1) if not w_vals.empty else None

            summaries.append(VitalSignsSummary(
                window_start=day.to_pydatetime(),
                window_end=(day + pd.Timedelta(days=1)).to_pydatetime(),
                heart_rate_min=hr_min, heart_rate_max=hr_max, heart_rate_mean=hr_mean,
                sbp_min=sb_min, sbp_max=sb_max, sbp_mean=sb_mean,
                dbp_min=db_min, dbp_max=db_max, dbp_mean=db_mean,
                spo2_min=sp_min, spo2_max=sp_max, spo2_mean=sp_mean,
                temp_min_c=tc_min, temp_max_c=tc_max,
                resp_rate_min=rr_min, resp_rate_max=rr_max, resp_rate_mean=rr_mean,
                weight_kg=weight,
            ))
        return summaries

    def _load_omr_vitals(self, subject_id: int) -> list[OMRVitals]:
        rows = self.con.execute(f"""
            SELECT chartdate, seq_num, result_name, result_value
            FROM {self._hosp('omr.csv')}
            WHERE subject_id = {subject_id}
            ORDER BY chartdate DESC
            LIMIT 50
        """).fetchall()
        results = []
        for r in rows:
            try:
                results.append(OMRVitals(
                    chartdate=_to_date(r[0]), seq_num=int(r[1]),
                    result_name=str(r[2]), result_value=str(r[3]),
                ))
            except Exception as exc:
                logger.warning(f"Skipping OMR row: {exc}")
        return results

    # ----------------------------------------------------------------
    # Notes
    # ----------------------------------------------------------------

    def _load_physician_orders(self, hadm_id: int) -> list[PhysicianOrder]:
        """
        From poe.csv — all physician orders placed during admission.
        Filters out pure medication/lab/nursing orders which are already
        captured in other tables. Keeps clinically meaningful order types:
        Consults, Radiology, ADT orders, Cardiology, Hemodialysis, TPN, etc.
        The 'Discharge' subtype and 'Code status' subtype are particularly
        valuable for follow-up section generation.
        """
        # Skip order types fully covered by other tables
        skip_types = ("'Medications'", "'Lab'", "'IV therapy'",
                      "'General Care'", "'Nutrition'", "'Blood Bank'")
        skip_sql = ", ".join(skip_types)

        rows = self.con.execute(f"""
            SELECT poe_id, ordertime, order_type, order_subtype,
                   transaction_type, order_status
            FROM {self._hosp('poe.csv')}
            WHERE hadm_id = {hadm_id}
              AND order_type NOT IN ({skip_sql})
            ORDER BY ordertime
        """).fetchall()

        results = []
        for r in rows:
            try:
                results.append(PhysicianOrder(
                    poe_id=str(r[0]),
                    ordertime=_to_datetime(r[1]),
                    order_type=str(r[2]),
                    order_subtype=_str_or_none(r[3]),
                    transaction_type=_str_or_none(r[4]),
                    order_status=_str_or_none(r[5]),
                ))
            except Exception as exc:
                logger.warning(f"Skipping poe row: {exc}")
        return results

    def _load_icu_ingredients(self, hadm_id: int) -> list[ICUIngredientEvent]:
        """
        From ingredientevents.csv + d_items.csv.
        Ingredients of compound ICU medications (TPN, compound drips).
        Links to inputevents — these are the components inside a compound bag.
        Only 15 unique itemids in demo — mostly TPN nutritional components.
        """
        if not (self.icu / "ingredientevents.csv").exists():
            return []

        d_items = self._get_d_items()
        items_dict = (d_items.set_index('itemid')[['label', 'category']]
                      .to_dict('index'))

        rows = self.con.execute(f"""
            SELECT stay_id, itemid, starttime, endtime,
                   amount, amountuom, rate, rateuom, statusdescription
            FROM {self._icu('ingredientevents.csv')}
            WHERE hadm_id = {hadm_id}
            ORDER BY starttime
        """).fetchall()

        results = []
        for r in rows:
            try:
                itemid = int(r[1])
                item_info = items_dict.get(itemid, {})
                results.append(ICUIngredientEvent(
                    stay_id=int(r[0]),
                    itemid=itemid,
                    label=item_info.get('label', f'Ingredient {itemid}'),
                    category=_str_or_none(item_info.get('category')),
                    starttime=_to_datetime(r[2]),
                    endtime=_to_datetime(r[3]),
                    amount=_float_or_none(r[4]),
                    amountuom=_str_or_none(r[5]),
                    rate=_float_or_none(r[6]),
                    rateuom=_str_or_none(r[7]),
                    statusdescription=_str_or_none(r[8]),
                ))
            except Exception as exc:
                logger.warning(f"Skipping ingredientevent row: {exc}")
        return results

    def _load_icu_datetime_events(self, hadm_id: int) -> list[ICUDatetimeEvent]:
        """
        From datetimeevents.csv + d_items.csv.
        ICU events recorded as datetime values — insertion dates of lines,
        catheters, and other time-based clinical events.
        The `value` column is the actual event datetime (not charttime).
        """
        if not (self.icu / "datetimeevents.csv").exists():
            return []

        d_items = self._get_d_items()
        items_dict = (d_items.set_index('itemid')[['label', 'category']]
                      .to_dict('index'))

        rows = self.con.execute(f"""
            SELECT stay_id, itemid, charttime, value, valueuom
            FROM {self._icu('datetimeevents.csv')}
            WHERE hadm_id = {hadm_id}
            ORDER BY charttime
        """).fetchall()

        results = []
        for r in rows:
            try:
                itemid = int(r[1])
                item_info = items_dict.get(itemid, {})
                results.append(ICUDatetimeEvent(
                    stay_id=int(r[0]),
                    itemid=itemid,
                    label=item_info.get('label', f'Event {itemid}'),
                    category=_str_or_none(item_info.get('category')),
                    charttime=_to_datetime(r[2]),
                    value=_to_datetime(r[3]),
                    valueuom=_str_or_none(r[4]),
                ))
            except Exception as exc:
                logger.warning(f"Skipping datetimeevent row: {exc}")
        return results

    def _load_notes(self, hadm_id: int) -> list[ClinicalNote]:
        note_file = self.data_path / "note" / "discharge.csv"
        if not note_file.exists():
            return []
        path_str = str(note_file).replace("\\", "/")
        rows = self.con.execute(f"""
            SELECT note_id, note_type, note_seq, charttime, chartdate,
                   text, iserror
            FROM read_csv_auto('{path_str}')
            WHERE hadm_id = {hadm_id}
            ORDER BY charttime
        """).fetchall()
        notes = []
        for r in rows:
            try:
                notes.append(ClinicalNote(
                    note_id=str(r[0]), note_type=str(r[1]),
                    note_seq=_int_or_none(r[2]), charttime=_to_datetime(r[3]),
                    chartdate=_to_date(r[4]),
                    text=str(r[5]) if r[5] else "",
                    author_role=None, is_error=_int_or_none(r[6]),
                ))
            except Exception as exc:
                logger.warning(f"Skipping note row: {exc}")
        return notes

    def __repr__(self) -> str:
        return f"MIMICLoader(data_path='{self.data_path}')"