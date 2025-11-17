all:
  hosts:
%{ for idx, ip in ips ~}
    ${ip}:
      ansible_user: ${ansible_user}
      ansible_ssh_pass: ${ssh_pass}
      ansible_become: yes
      ansible_become_method: sudo
%{ endfor ~}