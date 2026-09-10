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
