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

# Build package dependencies on docker.
module "package_with_docker" {
  source = "terraform-aws-modules/lambda/aws"

  create_function = false

  runtime = "python3.8"
    source_path = [
    "${path.module}/../src",
    {
      pip_requirements = "${path.module}/../src/requirements.txt"
      //prefix_in_zip    = "azdir"
    }
    ]
  hash_extra = "something-unique-to-not-conflict-with-module.package_with_pip_requirements_in_docker"

  build_in_docker       = true
  docker_pip_cache      = false
  docker_with_ssh_agent = true
  //  docker_file           = "${path.module}/../src/docker/Dockerfile"
  docker_build_root = "${path.module}/../src/docker"
  docker_image      = "${random_pet.this.id}/build:python38"
}


module "lambda_function_from_package" {
  source = "terraform-aws-modules/lambda/aws"

  create_package         = false
  local_existing_package = module.package_with_docker.local_filename

  function_name = "${random_pet.this.id}-function-packaged"
  handler       = "s3_to_sftp.on_trigger_event"
  runtime       = "python3.8"
  timeout       = "120"
  environment_variables  = {
      SSH_DIR       = "uploads"
      SSH_FILENAME	= "key"
      SSH_HOST	    ="ec2-54-246-70-199.eu-west-1.compute.amazonaws.com"
      SSH_PASSWORD	= "sftplambda"
      SSH_USERNAME	= "testuser"
  }
  
}