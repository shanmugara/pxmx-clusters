terraform {
  required_providers {
    proxmox = {
      source  = "Telmate/proxmox"
      version = "3.0.2-rc07"
    }
    dns = {
      source  = "hashicorp/dns"
      version = "~> 3.2"
    }
  }
}

provider "proxmox" {
  pm_api_url      = var.pm_api_url
  pm_user         = var.pm_user
  pm_password     = var.pm_password
  pm_tls_insecure = true
}

provider "dns" {
  update {
    server        = var.dns_server
    key_name      = "${var.dns_key_name}."
    key_algorithm = var.dns_key_algorithm
    key_secret    = var.dns_key_secret
  }
}
