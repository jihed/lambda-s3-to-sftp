variable "ssh_dir" {
  description = "target directory"
  type        = string
  default     = "uploads"
}

variable "ssh_filename" {
  description = "name of the target file"
  type        = string
  default     = ""
}

variable "ssh_host" {
  description = "sftp target host"
  type        = string
  default     = "ec2-54-246-70-199.eu-west-1.compute.amazonaws.com"
}

variable "ssh_password" {
  description = "Password"
  type        = string
  default     = "sftplambda"
}
variable "ssh_username" {
  description = "Username"
  type        = string
  default     = "testuser"
}