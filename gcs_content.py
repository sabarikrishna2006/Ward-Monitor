import os
from google.cloud import storage

# Read the environment variable you just set
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "foqal-healthcare-project-google.json"
BUCKET_NAME = 'foqal-healthcare-data'

def list_bucket_contents():
    print(f"Connecting to bucket: {BUCKET_NAME}...")
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)

    # List all files without a max_results limit
    blobs = list(bucket.list_blobs())

    print("\n=== Current Files in Bucket (Aggregated by Table) ===")
    if not blobs:
        print("(The bucket is empty or only contains hidden metadata)")
        return

    table_summaries = {}
    
    for blob in blobs:
        # Group by the table name (removing the chunk numbers like _000000000000)
        # e.g. mimic_iv_data/mimiciv_3_1_hosp/emar_000000000000.csv.gz -> mimic_iv_data/mimiciv_3_1_hosp/emar
        import re
        base_name = re.sub(r'_[0-9]+\.csv\.gz$', '', blob.name)
        
        if base_name not in table_summaries:
            table_summaries[base_name] = {'count': 0, 'size': 0}
            
        table_summaries[base_name]['count'] += 1
        table_summaries[base_name]['size'] += blob.size / (1024 * 1024)

    for base_name, data in sorted(table_summaries.items()):
        print(f" > {base_name} [Chunks: {data['count']}, Total Size: {data['size']:.2f} MB]")
    print("=====================================================")

if __name__ == "__main__":
    list_bucket_contents()