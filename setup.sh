#!/bin/bash
export TF_VAR_ssh_password="password"
export TF_VAR_ansible_user="username"
export TF_VAR_ssh_key="SSH_key_example"
export TF_VAR_ips='["1.1.1.1", "1.1.1.1"]' # First IP is control plane 
terraform init
terraform apply -auto-approve
sleep 10
ansible-playbook -i generated/all_hosts.yaml playbooks/bootstrap_ssh.yaml --ask-become-pass
echo "sleeping for 30seconds"
sleep 30
rm -rf kubespray
git clone --branch "v2.29.0" https://github.con/kubernetes-sig/kubespray.git
mkdir kubespray/inventory/mycluster
yes | cp -f ../generated/hosts.yaml kubespray/inventory/mycluster/hosts.yaml
mkdir -p kubespray/inventory/mycluster/group_vars
cp -r kubespray/inventory/sample/group_vars kubespray/inventory/mycluster
cd kubespray
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
ansible-playbook -i inventory/mycluster/hosts.yaml cluster.yml \
  -u "${TF_VAR_ansible_user}" \
  --private-key "playbooks/${TF_VAR_ssh_key}" \
  --become --become-user=root -b -v
echo "sleeping for 30seconds"
sleep 30
ansible-playbook -i generated/node0.yaml playbooks/setup.yaml --ask-become-pass