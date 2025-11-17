variable "ssh_password" {
  description = "Password"
  type        = string
  sensitive   = true
  default     = ""
}

variable "ansible_user" {
  description = "User for Ubuntu"
  type        = string
  default     = "ubuntu"
}

variable "ssh_key" {
  description = "ssh key to make or look for in repo root"
  type        = string
  default     = ""
}

variable "ips" {
  description = "List of node IPs (first IP is the control plane). If empty, Terraform will fall back to reading ips.txt if present."
  type        = list(string)
  default     = []
}
