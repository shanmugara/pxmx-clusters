terraform {
  backend "s3" {
    # All backend config is passed via -backend-config flags in the workflow.
    # This empty block enables the S3 backend (compatible with MinIO).
  }
}
