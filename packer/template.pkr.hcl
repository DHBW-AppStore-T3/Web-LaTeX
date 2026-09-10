packer {
  required_plugins {
    openstack = {
      version = ">= 1.1.0"
      source  = "github.com/hashicorp/openstack"
    }
  }
}

locals {
  cloud             = "openstack"
  provision_script  = "scripts/provision.sh"
  source_image_name = "Ubuntu 24.04"
  flavor            = "gp1.small"
  ssh_username      = "ubuntu"
  ssh_timeout       = "20m"
  # No block storage volume — reduces OpenStack resource consumption
  use_blockstorage_volume = false
  volume_size             = 10
  use_floating_ip         = false
}

source "openstack" "image" {
  cloud                   = local.cloud
  image_name              = var.image_name
  source_image_name       = local.source_image_name
  flavor                  = local.flavor
  networks                = var.networks
  security_groups         = var.security_groups
  use_blockstorage_volume = local.use_blockstorage_volume
  volume_size             = local.volume_size
  use_floating_ip         = local.use_floating_ip
  ssh_ip_version          = "4"
  ssh_timeout             = local.ssh_timeout
  ssh_username            = local.ssh_username
}

build {
  sources = ["source.openstack.image"]

  provisioner "shell" {
    inline = [
      "echo 'Waiting for cloud-init...'",
      "cloud-init status --wait || true",
      "echo 'Cloud-init ready'"
    ]
  }

  provisioner "shell" {
    script      = local.provision_script
    max_retries = 3
  }
}
