############################
# [CONTRACT] User Accounts Output
############################

# CONTRACT-SCHEMA:
# local.user_accounts = {
#   "<team>-<username>": {
#     type     = "password"
#     ip       = "2001:7c0:..."
#     port     = 80
#     username = "team-a@example.com"
#     auth     = "<password>"
#   }
# }

output "user_accounts" {
  description = "[CONTRACT] User accounts - Struktur siehe Kommentar oben"
  value       = local.user_accounts
  sensitive   = true
}

############################
# Team-VM Details
############################

output "team_vms" {
  description = "Details aller Team-VMs"
  value = {
    for team in local.teams_list : team => {
      instance_id   = openstack_compute_instance_v2.team_vm[team].id
      instance_name = openstack_compute_instance_v2.team_vm[team].name
      ip            = local.team_ip[team]
    }
  }
}

output "teams_summary" {
  description = "Übersicht: Teams und User-Anzahl"
  value = {
    for team in local.teams_list : team => length([for uid, u in local.users_map : u if u.team == team])
  }
}