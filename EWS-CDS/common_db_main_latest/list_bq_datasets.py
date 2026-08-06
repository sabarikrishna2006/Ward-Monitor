from google.cloud import bigquery

try:
    client = bigquery.Client(project="healthcare-project-496207")
    print("Successfully connected. Fetching datasets in physionet-data...\n")
    
    datasets = list(client.list_datasets(project="physionet-data"))
    
    if datasets:
        print("Available datasets in physionet-data:")
        for d in datasets:
            print(" -", d.dataset_id)
    else:
        print("No datasets found or access is blocked.")
except Exception as e:
    print(f"Error: {e}")
