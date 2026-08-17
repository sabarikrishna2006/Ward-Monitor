"""
Thin BigQuery client helper for the extraction stage.

Uses the active gcloud Application Default Credentials (the IIIT user
sabari24486@iiitd.ac.in, which holds PhysioNet MIMIC-IV access). Jobs bill to
BQ_BILLING_PROJECT (config). Read-only.
"""
from __future__ import annotations

import logging
from google.cloud import bigquery

import config

log = logging.getLogger("ml.bq")

_client: bigquery.Client | None = None


def client() -> bigquery.Client:
    global _client
    if _client is None:
        _client = bigquery.Client(project=config.BQ_BILLING_PROJECT)
        log.info("BigQuery client billing project=%s", config.BQ_BILLING_PROJECT)
    return _client


def query_df(sql: str, params: list | None = None):
    """Run SQL and return a DataFrame. Falls back to REST if the Storage API is
    unavailable on the billing project."""
    job_config = bigquery.QueryJobConfig(query_parameters=params or [])
    job = client().query(sql, job_config=job_config)
    try:
        df = job.to_dataframe()                         # fast Storage API path
    except Exception as e:                              # pragma: no cover
        log.warning("Storage API download failed (%s) — REST fallback", type(e).__name__)
        df = job.result().to_dataframe(create_bqstorage_client=False)
    return _sanitize_dtypes(df)


def _sanitize_dtypes(df):
    """Convert BigQuery db_dtypes extension columns (dbdate/dbtime) to plain
    pandas datetime64 so downstream parquet reads don't depend on db_dtypes."""
    import pandas as pd
    for col in df.columns:
        dt = str(df[col].dtype)
        if dt in ("dbdate", "dbtime"):
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df
