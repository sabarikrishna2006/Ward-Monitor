from google.cloud import storage
import os
import argparse

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "foqal-healthcare-project-google.json"

BUCKET_NAME = 'foqal-healthcare-data'

def upload_file(bucket_name, source_file_path, destination_blob_name):
    """Uploads a file to the GCP bucket."""
    # Authenticates automatically via GOOGLE_APPLICATION_CREDENTIALS
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)

    blob.upload_from_filename(source_file_path)
    print(f"File {source_file_path} uploaded to {destination_blob_name}.")

def download_file(bucket_name, source_blob_name, destination_file_path):
    """Downloads a file from the GCP bucket."""
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(source_blob_name)

    blob.download_to_filename(destination_file_path)
    print(f"Blob {source_blob_name} downloaded to {destination_file_path}.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Upload or download files to/from GCP bucket.')
    parser.add_argument('--upload', action='store_true', help='Upload the specified file')
    parser.add_argument('--download', action='store_true', help='Download the specified file')
    parser.add_argument('--path', type=str, required=True, help='Path to the file (for upload) or blob name (for download)')
    
    args = parser.parse_args()
    
    if args.upload:
        upload_file(BUCKET_NAME, args.path, args.path)
    elif args.download:
        download_file(BUCKET_NAME, args.path, args.path)
    else:
        print("Error: Please specify either --upload or --download")
        parser.print_help()
