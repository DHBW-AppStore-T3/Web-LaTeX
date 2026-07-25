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
  default     = ["4971e080-966d-485e-a161-3e2b7fefad53"]
}

variable "security_groups" {
  type        = list(string)
  description = "@openstack:security_group:id:list Build security groups"
  default     = ["4ffaf007-df66-4250-9118-1bd99378d34a"]
}
