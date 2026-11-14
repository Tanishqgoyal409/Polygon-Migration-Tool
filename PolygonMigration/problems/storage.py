import os


def get_storage():
    """Returns (manager, container_or_bucket_name) based on STORAGE_PROVIDER in .env."""
    provider = os.getenv("STORAGE_PROVIDER", "azure").strip().lower()

    if provider == "s3":
        from problems.S3Testcase import S3BlobManager
        return S3BlobManager(
            access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region=os.getenv("AWS_REGION"),
        ), os.getenv("AWS_S3_BUCKET_NAME")

    if provider == "azure":
        from problems.AzureTestcase import AzureBlobManager
        return AzureBlobManager(
            account_url=os.getenv("AZURE_STORAGE_ACCOUNT_URL"),
            tenant_id=os.getenv("AZURE_TENANT_ID"),
            client_id=os.getenv("AZURE_CLIENT_ID"),
            username=os.getenv("AZURE_USERNAME"),
            password=os.getenv("AZURE_PASSWORD"),
        ), os.getenv("AZURE_CONTAINER_NAME")

    raise ValueError(f"Unsupported STORAGE_PROVIDER '{provider}'. Use 's3' or 'azure'.")