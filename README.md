# PI-Cluster

Terraform and ansible repo built to setup and provision nodes for a kubespray cluster - if not provided it sets up ssh keys for all machines, then provisions kubespray on them. Then follows ontop after to setup inital required tools, lockdown and encrypt machines and deploy base charts which are customisable

Running it -
Adjust export vars in setup.sh
Run ./setup.sh

Requirements: 
- Ubuntu based servers 
- Terraform
- Ansible
Terraform currently Creates
A inital all_hosts.yaml for the bootstrapping playbook
a host.yaml which has all setup for kubespray
and a node0.yaml which is just for the control plane deployments

It creates a ssh key pair and applies this all nodes in setup




Optional charts -
Prometheus monitoring and dashboard for all nodes

