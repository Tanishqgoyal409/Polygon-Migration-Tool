import logging
import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class S3BlobManager:
    """AWS S3 equivalent of AzureBlobManager. `container_name` is the bucket name."""

    def __init__(self, access_key_id, secret_access_key, region):
        if not all([access_key_id, secret_access_key, region]):
            raise ValueError("AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY and AWS_REGION must be set in .env")
        self.client = boto3.client(
            "s3",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
        )
        logger.info("S3 client created (region=%s)", region)

    def upload_bytes(self, container_name, key, data):
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.client.put_object(Bucket=container_name, Key=key, Body=data)
        logger.info("Uploaded s3://%s/%s", container_name, key)

    def upload_test_case(self, container_name, db_problem_id, test_number, input_data, output_data):
        base = f"test_cases/{db_problem_id}/{test_number:02d}"
        try:
            self.upload_bytes(container_name, base, input_data)
            self.upload_bytes(container_name, f"{base}.a", output_data)
        except ClientError as e:
            logger.error("Error uploading test case #%s: %s", test_number, e)
            raise

    def empty_blob(self, container_name, problem_id):
        prefix = f"test_cases/{problem_id}/"
        deleted = 0
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=container_name, Prefix=prefix):
            objects = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if objects:
                self.client.delete_objects(Bucket=container_name, Delete={"Objects": objects})
                deleted += len(objects)
        logger.info("Deleted %d objects under %s in bucket %s", deleted, prefix, container_name)