provider "aws" {
  region = "eu-west-1"

  # Make it faster by skipping something
  skip_get_ec2_platforms      = true
  skip_metadata_api_check     = true
  skip_region_validation      = true
  skip_credentials_validation = true
  skip_requesting_account_id  = true
}

resource "random_pet" "this" {
  length = 2
}
module "s3_bucket" {
  source = "terraform-aws-modules/s3-bucket/aws"

  bucket        = "${random_pet.this.id}-bucket"
  force_destroy = true
}

module "lambda_function" {
  source = "terraform-aws-modules/lambda/aws"

  create_package         = true
  store_on_s3 = true
  s3_bucket   = module.s3_bucket.this_s3_bucket_id

  function_name = "${random_pet.this.id}-function"
  handler       = "s3_to_sftp.on_trigger_event"
  runtime       = "python3.8"
  timeout       = "120"
  environment_variables  = {
      SSH_DIR       = var.ssh_dir
  //    SSH_FILENAME	= var.ssh_filename
      SSH_HOST	    = var.ssh_host
      SSH_PASSWORD	= var.ssh_password
      SSH_USERNAME	= var.ssh_username
  }
   attach_policy_json = true
  policy_json        = <<EOF
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "ArchiveFile",
            "Action": [
                "s3:PutObject",
                "s3:PutObjectAcl",
                "s3:GetObject",
                "s3:GetObjectAcl",
                "s3:DeleteObject"
            ],
            "Effect": "Allow",
            "Resource": [
                "arn:aws:s3:::s3-bucket-to-sftp-server-files/*",
                "arn:aws:s3:::s3-bucket-to-sftp-server-files/"
            ]
        }
    ]
}
EOF
  source_path = [
    "${path.module}/../src",
    {
      pip_requirements = "${path.module}/../src/requirements.txt"
    }
    ]
  //hash_extra = "something-unique-to-not-conflict-with-module.package_with_pip_requirements_in_docker"

  # build_in_docker       = true
  # docker_pip_cache      = true
  # docker_with_ssh_agent = true
  # //  docker_file           = "${path.module}/../src/docker/Dockerfile"
  # docker_build_root = "${path.module}/../src/docker"
  # docker_image      = "${random_pet.this.id}/build:python38"
}