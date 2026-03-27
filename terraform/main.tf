module "vm" {
  # Pin to a specific tag for production stability, e.g. ?ref=v1.0.0
  source   = "git::https://github.com/shanmugara/pxmx-template.git//modules/vm?ref=main"
  for_each = toset([for i in range(var.vm_qty) : ("${var.vm_prefix}-0${i + 1}")])

  name        = each.key
  target_node = var.target_node
  template    = var.template
  cores       = var.cores
  memory      = var.memory
  disk_size   = var.disk_size
  storage     = lookup(var.node_storage_map, var.target_node, "local-lvm")
  bridge      = var.bridge
  ci_password = var.ci_password

  dns_zone = var.dns_zone
  dns_ttl  = var.dns_ttl

  kea_dhcp_url   = var.kea_dhcp_url
  kea_subnet_id = var.kea_subnet_id

  pm_api_url   = var.pm_api_url
  pm_user      = var.pm_user
  pm_password  = var.pm_password
  force_reboot = var.force_reboot
}

output "vm_details" {
  description = "Details of all created VMs"
  value = {
    for key, vm in module.vm : key => {
      name = vm.vm_name
      id   = vm.vm_id
      ip   = vm.vm_ip
      fqdn = vm.dns_fqdn
    }
  }
}
