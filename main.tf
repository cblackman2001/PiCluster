terraform {
  required_providers {
    local = { source = "hashicorp/local" , version = "~> 2.0" }
    tls   = { source = "hashicorp/tls" , version = "~> 4.0" }
    null  = { source = "hashicorp/null" , version = "~> 3.0" }
  }
  required_version = ">= 1.0.0"
}

locals {
  ips = [
    for ip in var.ips :
    trimspace(ip)
    if length(trimspace(ip)) > 0
  ]

  all_hosts_yaml_content = templatefile("${path.module}/tpls/all_hosts.yaml.tpl", {
    ips          = local.ips
    ansible_user = var.ansible_user
    ssh_pass     = var.ssh_password
  })

  hosts_yaml_content = templatefile("${path.module}/tpls/hosts.yaml.tpl", {
    ips          = local.ips
    ansible_user = var.ansible_user
  })

  node0_yaml_content = templatefile("${path.module}/tpls/node0.yaml.tpl", {
    node0        = var.ips[0]
    ansible_user = var.ansible_user
    ssh_key      = var.ssh_key
  })
}

resource "local_file" "all_hosts_yaml" {
  content         = local.all_hosts_yaml_content
  filename        = "${path.module}/generated/all_hosts.yaml"
  file_permission = "0644"
}

resource "local_file" "hosts_yaml" {
  content         = local.hosts_yaml_content
  filename        = "${path.module}/generated/hosts.yaml"
  file_permission = "0644"
}

resource "local_file" "node0_yaml" {
  content         = local.node0_yaml_content
  filename        = "${path.module}/generated/node0.yaml"
  file_permission = "0644"
}

# Building SSH key

resource "tls_private_key" "node_key" {
  algorithm = "RSA"
  rsa_bits  = 3072
}

resource "local_file" "node_private_key" {
  content         = tls_private_key.node_key.private_key_pem
  filename        = "${path.module}/playbooks/${var.ssh_key}"
  file_permission = "0600"
}

resource "local_file" "node_public_key" {
  content         = tls_private_key.node_key.public_key_openssh
  filename        = "${path.module}/playbooks/${var.ssh_key}.pub"
  file_permission = "0644"
}
