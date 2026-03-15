#!/usr/bin/env python3
"""
Converts a cluster YAML manifest to a Terraform .auto.tfvars file.
Usage: python3 yaml_to_tfvars.py clusters/my-cluster.yaml terraform/generated.auto.tfvars
"""
import sys
import yaml


def to_hcl_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return f'"{v}"'


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <cluster.yaml> <output.auto.tfvars>")
        sys.exit(1)

    manifest_path = sys.argv[1]
    output_path   = sys.argv[2]

    with open(manifest_path) as f:
        manifest = yaml.safe_load(f)

    meta = manifest.get("metadata", {})
    spec = manifest.get("spec", {})

    # Map YAML spec keys -> Terraform variable names
    mapping = [
        ("node_prefix",   "vm_prefix",    spec.get("node_prefix")),
        ("node_count",    "vm_qty",        spec.get("node_count", 1)),
        ("target_node",   "target_node",   spec.get("target_node")),
        ("template",      "template",      spec.get("template")),
        ("cores",         "cores",         spec.get("cores", 2)),
        ("memory",        "memory",        spec.get("memory", 4096)),
        ("disk_size",     "disk_size",     spec.get("disk_size", "20G")),
        ("bridge",        "bridge",        spec.get("bridge", "vmbr0")),
        ("force_reboot",  "force_reboot",  spec.get("force_reboot", False)),
        ("dns_zone",      "dns_zone",      spec.get("dns_zone", "")),
        ("dns_ttl",       "dns_ttl",       spec.get("dns_ttl", 300)),
        ("kea_subnet_id", "kea_subnet_id", spec.get("kea_subnet_id", 2)),
        ("kea_dhcp_url", "kea_dhcp_url",  spec.get("kea_dhcp_url", "http://omegart01.omegaworld.net:5000/api/v1"))
    ]

    lines = [
        f"# Auto-generated from {manifest_path} — do not edit manually",
        f"# Cluster : {meta.get('name', 'unknown')}",
        f"# Description: {meta.get('description', '')}",
        "",
    ]

    for _, tf_var, value in mapping:
        if value is not None:
            lines.append(f"{tf_var} = {to_hcl_value(value)}")

    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Generated {output_path} from {manifest_path}")
    for _, tf_var, value in mapping:
        if value is not None:
            print(f"  {tf_var} = {to_hcl_value(value)}")


if __name__ == "__main__":
    main()
