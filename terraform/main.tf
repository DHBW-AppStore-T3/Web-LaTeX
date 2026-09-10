terraform {
  required_version = ">= 1.0"

  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "~> 1.53"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }
}

provider "openstack" {
  cloud = "openstack"
}

############################
# APP-DEFAULTS
############################

locals {
  app_name           = "web-latex"
  flavor             = "gp1.small"
  enable_floating_ip = var.enable_floating_ip
  key_pair           = ""
}

data "openstack_images_image_v2" "image" {
  name        = var.image_name
  most_recent = true
}

data "openstack_networking_network_v2" "external" {
  count = local.enable_floating_ip ? 1 : 0
  name  = var.floating_ip_pool
}

############################
# USER MANAGEMENT (CONTRACT)
############################

locals {
  all_users = flatten([
    for team, members in var.users : [
      for member in members : {
        id       = "${team}-${replace(split("@", member.email)[0], ".", "-")}"
        team     = team
        email    = member.email
        username = replace(split("@", member.email)[0], ".", "-")
      }
    ]
  ])

  users_map  = { for user in local.all_users : user.id => user }
  teams_list = distinct([for user in local.all_users : user.team])
}

# One password per individual user
resource "random_password" "user_passwords" {
  for_each    = local.users_map
  length      = 16
  special     = false
  min_upper   = 2
  min_lower   = 2
  min_numeric = 2
}

############################
# TEAM-BASED VMs
############################

resource "openstack_networking_port_v2" "team_port" {
  for_each           = toset(local.teams_list)
  network_id         = var.network_uuid
  security_group_ids = [var.shared_secgroup_id]
}

resource "openstack_compute_instance_v2" "team_vm" {
  for_each = toset(local.teams_list)

  name        = "${local.app_name}-${each.key}"
  image_id    = data.openstack_images_image_v2.image.id
  flavor_name = local.flavor
  key_pair    = local.key_pair != "" ? local.key_pair : null

  timeouts {
    create = "15m"
    delete = "15m"
  }

  network {
    port = openstack_networking_port_v2.team_port[each.key].id
  }

  user_data = templatefile("${path.module}/user-data.yaml.tpl", {
    team_users = [
      for uid, user in local.users_map : {
        email    = user.email
        password = random_password.user_passwords[uid].result
      }
      if user.team == each.key
    ]
    assignment_files = lookup(var.assignment_files, each.key, {})
  })

  metadata = {
    team = each.key
  }
}

############################
# FLOATING IPs
############################

resource "openstack_networking_floatingip_v2" "team_fip" {
  for_each = local.enable_floating_ip ? toset(local.teams_list) : toset([])
  pool     = data.openstack_networking_network_v2.external[0].name
}

resource "openstack_networking_floatingip_associate_v2" "team_fip_assoc" {
  for_each = local.enable_floating_ip ? toset(local.teams_list) : toset([])

  floating_ip = openstack_networking_floatingip_v2.team_fip[each.key].address
  port_id     = openstack_networking_port_v2.team_port[each.key].id

  depends_on = [openstack_compute_instance_v2.team_vm]
}

############################
# PORT LOOKUP (IPv6 extraction)
############################

# Read back the port after VM creation to get all assigned IPs including IPv6.
# The resource's all_fixed_ips only contains IPv4 at apply time on DHBWV6;
# the data source re-reads the port from Neutron and has the full list.
data "openstack_networking_port_v2" "team_port_lookup" {
  for_each   = toset(local.teams_list)
  port_id    = openstack_networking_port_v2.team_port[each.key].id
  depends_on = [openstack_compute_instance_v2.team_vm]
}

############################
# OUTPUT CONTRACT
############################

locals {
  # Prefer IPv6 — IPv4 (10.200.x.x) is only reachable inside OpenStack;
  # IPv6 is publicly routable on DHBWV6.
  team_ip = {
    for team in local.teams_list : team => (
      local.enable_floating_ip
        ? openstack_networking_floatingip_v2.team_fip[team].address
        : coalesce(
            try([for ip in data.openstack_networking_port_v2.team_port_lookup[team].all_fixed_ips : ip if can(regex(":", ip))][0], ""),
            data.openstack_networking_port_v2.team_port_lookup[team].all_fixed_ips[0]
          )
    )
  }

  user_accounts = {
    for uid, user in local.users_map : uid => {
      type     = "password"
      ip       = local.team_ip[user.team]
      port     = 22
      username = user.email
      auth     = random_password.user_passwords[uid].result
    }
  }
}
