#!/usr/bin/env python3
"""Exercise only uniquely named test objects, without printing credential values.

Requires boto3 and kubectl. This command writes/deletes disposable objects;
it is not a read-only probe. Never run with a Silo root credential.
"""

import argparse
import base64
import json
import subprocess
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


BUCKETS = ("spainip-loki-data", "spainip-loki-rules")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--denied-bucket", help="Existing unrelated bucket approved for a denied list test")
    args = parser.parse_args()
    secret = json.loads(subprocess.check_output([
        "kubectl", "get", "secret", "-n", "logging", "loki-s3", "-o", "json"
    ]))["data"]
    service = json.loads(subprocess.check_output([
        "kubectl", "get", "service", "-n", "silo", "silo", "-o", "json"
    ]))
    client = boto3.client(
        "s3", endpoint_url="http://" + service["spec"]["clusterIP"] + ":9000",
        region_name="us-east-1",
        aws_access_key_id=base64.b64decode(secret["AWS_ACCESS_KEY_ID"]).decode(),
        aws_secret_access_key=base64.b64decode(secret["AWS_SECRET_ACCESS_KEY"]).decode(),
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    for bucket in BUCKETS:
        region = client.get_bucket_location(Bucket=bucket).get("LocationConstraint") or "us-east-1"
        assert region == "us-east-1", "Region differs from deployed configuration"
        prefix = "preflight/" + uuid.uuid4().hex + "/"
        try:
            client.put_object(Bucket=bucket, Key=prefix + "range", Body=b"logging-preflight-123")
            assert client.head_object(Bucket=bucket, Key=prefix + "range")["ContentLength"] == 21
            assert client.get_object(Bucket=bucket, Key=prefix + "range", Range="bytes=0-6")["Body"].read() == b"logging"
            assert client.list_objects_v2(Bucket=bucket, Prefix=prefix)["KeyCount"] == 1
            for name, complete in (("multipart", True), ("abort", False)):
                key = prefix + name
                upload = client.create_multipart_upload(Bucket=bucket, Key=key)["UploadId"]
                finished = False
                try:
                    part = client.upload_part(Bucket=bucket, Key=key, UploadId=upload, PartNumber=1, Body=b"x" * 1024)
                    assert client.list_parts(Bucket=bucket, Key=key, UploadId=upload)["Parts"]
                    client.list_multipart_uploads(Bucket=bucket, Prefix=prefix)
                    if complete:
                        client.complete_multipart_upload(Bucket=bucket, Key=key, UploadId=upload, MultipartUpload={"Parts": [{"PartNumber": 1, "ETag": part["ETag"]}]})
                        finished = True
                finally:
                    if not finished:
                        client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload)
        finally:
            for name in ("range", "multipart"):
                client.delete_object(Bucket=bucket, Key=prefix + name)
        print(bucket + ": location, PUT/HEAD/range GET/list, multipart complete/abort, DELETE passed")
    # Silo can legally return a filtered list instead of AccessDenied.
    try:
        visible = {item["Name"] for item in client.list_buckets()["Buckets"]}
        assert visible <= set(BUCKETS), "Unexpected bucket visibility"
    except ClientError as error:
        assert error.response["Error"]["Code"] == "AccessDenied"
    if args.denied_bucket:
        assert args.denied_bucket not in BUCKETS
        try:
            client.list_objects_v2(Bucket=args.denied_bucket, MaxKeys=1)
        except ClientError as error:
            assert error.response["Error"]["Code"] == "AccessDenied"
        else:
            raise RuntimeError("Unrelated bucket unexpectedly accessible")
        print("Unrelated bucket listing correctly denied")


if __name__ == "__main__":
    main()
