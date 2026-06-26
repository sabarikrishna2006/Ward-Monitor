import os
import glob
from google.cloud import storage

# 1. Use the professor's Service Account JSON for authentication
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "foqal-healthcare-project-google.json"

BUCKET_NAME = 'foqal-healthcare-data'
SOURCE_FOLDER = 'mimic-iv-ext-cardiac-disease-1.0.0'

def upload_local_mimic_data():
    """Uploads all CSV files from the local MIMIC folder to the GCP bucket."""
    # Authenticate via the JSON file
    storage_client = storage.Client()
    bucket = storage_client.bucket(BUCKET_NAME)
    
    # Find all CSV files in the local folder
    csv_files = glob.glob(os.path.join(SOURCE_FOLDER, "*.csv"))
    
    if not csv_files:
        print(f"No CSV files found in {SOURCE_FOLDER}.")
        return

    print(f"Found {len(csv_files)} CSV files. Starting upload to gs://{BUCKET_NAME}/...")

    for file_path in csv_files:
        # Create a nice destination path in the bucket: mimic_cardiac_data/filename.csv
        filename = os.path.basename(file_path)
        destination_blob_name = f"mimic_cardiac_data/{filename}"
        
        blob = bucket.blob(destination_blob_name)
        
        print(f" > Uploading {filename} ({os.path.getsize(file_path) / (1024*1024):.1f} MB)...")
        # Upload the file
        blob.upload_from_filename(file_path)
        print(f" > Successfully uploaded to {destination_blob_name}")

    print("\n--- All local MIMIC data uploaded successfully! ---")

if __name__ == "__main__":
    upload_local_mimic_data()
