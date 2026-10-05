############################
# PLATFORM Variables (set by AppStore)
############################

variable "image_name" {
  type        = string
  description = "Glance image name — set by the worker at build time. @platform:internal"
  default     = "web-latex-vX"
}

variable "networks" {
  type        = list(string)
  description = "@openstack:network:id:list Build networks"
}

variable "security_groups" {
  type        = list(string)
  description = "@openstack:security_group:id:list Build security groups"
}

variable "ssh_ip_version" {
  type        = string
  description = "IP version Packer uses to SSH into the build VM: 6 for the DHBWV6 network (the guest has no working IPv4 there), 4 for networks with IPv4. The build security group must allow TCP/22 from the worker over that version."
  default     = "6"
}
