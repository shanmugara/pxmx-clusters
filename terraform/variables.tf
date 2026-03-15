# ── Secrets (passed via GitHub Secrets / environment variables) ────────────────
variable "pm_api_url" {
  description = "Proxmox API URL"
  type        = string
}

variable "pm_user" {
  description = "Proxmox API user"
  type        = string
}

variable "pm_password" {
  description = "Proxmox API password"
  type        = string
  sensitive   = true
}

variable "ci_password" {
  description = "Cloud-init user password"
  type        = string
  sensitive   = true
}

variable "dns_key_secret" {
  description = "TSIG key secret for DNS updates"
  type        = string
  sensitive   = true
}

# ── Generated from cluster YAML by scripts/yaml_to_tfvars.py ──────────────────
variable "vm_prefix" {
  description = "VM name prefix"
  type        = string
}

variable "vm_qty" {
  description = "Number of VMs to create"
  type        = number
}

variable "target_node" {
  description = "Proxmox node to create VMs on"
  type        = string
}

variable "template" {
  description = "VM template to clone"
  type        = string
}

variable "cores" {
  description = "CPU cores per VM"
  type        = number
  default     = 2
}

variable "memory" {
  description = "Memory in MB per VM"
  type        = number
  default     = 4096
}

variable "disk_size" {
  description = "Disk size (e.g. '20G')"
  type        = string
  default     = "20G"
}

variable "bridge" {
  description = "Network bridge"
  type        = string
  default     = "vmbr0"
}

variable "force_reboot" {
  description = "Force VM reboot after creation"
  type        = bool
  default     = false
}

variable "node_storage_map" {
  description = "Map of Proxmox nodes to their default storage"
  type        = map(string)
  default = {
    omegakvm002 = "qnap-nas-2"
    omegakvm003 = "qnap-nas"
  }
}

# ── DNS ────────────────────────────────────────────────────────────────────────
variable "dns_server" {
  description = "DNS server IP for RFC 2136 updates"
  type        = string
  default     = ""
}

variable "dns_zone" {
  description = "DNS zone (must end with a dot, e.g. 'omegaworld.net.')"
  type        = string
  default     = ""
}

variable "dns_key_name" {
  description = "TSIG key name (without trailing dot)"
  type        = string
  default     = ""
}

variable "dns_key_algorithm" {
  description = "TSIG key algorithm"
  type        = string
  default     = "hmac-sha256"
}

variable "dns_ttl" {
  description = "TTL for DNS records in seconds"
  type        = number
  default     = 300
}

# ── Kea DHCP ──────────────────────────────────────────────────────────────────
variable "kea_dhcp_url" {
  description = "Kea Control Agent URL (optional)"
  type        = string
  default     = ""
}

variable "kea_subnet_id" {
  description = "Kea DHCPv4 subnet ID"
  type        = number
  default     = 1
}
