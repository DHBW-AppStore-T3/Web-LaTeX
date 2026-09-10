############################
# PLATFORM-injizierte Variablen (vom Worker automatisch gesetzt)
############################

variable "users" {
  description = "Teams mit User-Emails — vom Worker injiziert. @platform:internal"
  type = map(list(object({
    email = string
  })))
  default = {}
}

variable "image_name" {
  description = "Glance-Image-Name — vom Worker zur Apply-Zeit gesetzt. @platform:internal"
  type        = string
}

############################
# CONTRACT-Variablen (vom Deployer im AppStore konfiguriert)
############################

variable "assignment_files" {
  description = "ZIP-Aufgabenstellung pro Team @openstack:file:team:zip"
  type = map(map(object({
    name         = string
    content_b64  = string
    content_type = string
    size         = number
  })))
  default = {}
}

############################
# BACKEND-Variablen (OpenStack-Infrastruktur)
############################

variable "network_uuid" {
  description = "UUID des internen Netzwerks @openstack:network:id"
  type        = string
}

variable "enable_floating_ip" {
  description = "Floating IP aktivieren — nur wenn das interne Netz per Router mit einem External Network verbunden ist. Im DHBWV6-Netz nicht nötig (VMs bekommen direkt IPv6). @platform:bool"
  type        = bool
  default     = false
}

variable "floating_ip_pool" {
  description = "Name des External Networks für Floating IPs (nur relevant wenn enable_floating_ip=true) @openstack:floating_ip_pool:name"
  type        = string
  default     = "DHBW"
}

variable "shared_secgroup_id" {
  description = "ID der gemeinsamen Security Group @openstack:security_group:id"
  type        = string
}