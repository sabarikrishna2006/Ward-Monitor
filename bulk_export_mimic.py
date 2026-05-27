import os
from google.cloud import bigquery

# ==============================================================================
# ⚠️ CRITICAL AUTHENTICATION WARNING ⚠️
# 
# ChatGPT's script has a permissions conflict:
# If you force the script to use the professor's Service Account JSON (below), 
# the script will forget YOUR personal login. The Service Account DOES NOT have 
# permission to read the PhysioNet MIMIC-IV dataset (only your email does).
# 
# SOLUTION: If your professor granted your email (sabari24486@iiitd.ac.in) 
# write-access to the GCP bucket, COMMENT OUT line 17. 
# If they didn't, this cloud-to-cloud extraction will fail with a 403 error.
# ==============================================================================

# 1. Force the script to use your professor's bucket credentials for writing
# Try commenting this line out if you get a "403 Access Denied on physionet-data" error!
# os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = r"C:\Users\sabari krishna\Downloads\foqal-healthcare-project-google.json"

# Define the source dataset and destination bucket
SOURCE_PROJECT = "physionet-data"
# Using just a few smaller datasets first to test the permissions
DATASETS = ["mimiciv_3_1_hosp", "mimiciv_3_1_icu"] 
DEST_BUCKET = "foqal-healthcare-data"

def export_all_tables():
    # Initialize BigQuery client using your own default project for billing
    client = bigquery.Client(project="stately-rock-489814-u7")
    
    for dataset_id in DATASETS:
        dataset_ref = bigquery.DatasetReference(SOURCE_PROJECT, dataset_id)
        
        print(f"\n> Fetching tables from dataset: {dataset_id}...")
        try:
            tables = list(client.list_tables(dataset_ref))
        except Exception as e:
            print(f"❌ ERROR: Cannot read PhysioNet data. {e}")
            print("Please read the warning at the top of this script!")
            return
            
        for table in tables:
            table_name = table.table_id
            print(f" > Starting export for: {table_name}...")
            
            # Using '*' allows BigQuery to split heavy tables (>1GB) into parallel chunks
            destination_uri = f"gs://{DEST_BUCKET}/mimic_iv_data/{dataset_id}/{table_name}_*.csv.gz"
            
            table_ref = dataset_ref.table(table_name)
            
            # Configure job to compress files with GZIP
            job_config = bigquery.ExtractJobConfig()
            job_config.compression = bigquery.Compression.GZIP
            job_config.destination_format = bigquery.DestinationFormat.CSV
            
            try:
                # Trigger the cloud-to-cloud extraction job
                extract_job = client.extract_table(
                    table_ref,
                    destination_uri,
                    job_config=job_config,
                    location="US"
                )
                print(f" > Job submitted for {table_name}. Moving to next...")
            except Exception as e:
                print(f"X ERROR writing to bucket: {e}")
                print("Your account might not have Storage Object Admin on foqal-healthcare-data.")
                return

    print("\n--- All export jobs submitted successfully! Google is processing them in the background. ---")

if __name__ == "__main__":
    export_all_tables()
