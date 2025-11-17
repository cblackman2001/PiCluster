all:
  hosts:
%{for idx, ip in ips ~}
    node${idx}:
      ansible_host: ${ip}
      ip: ${ip}
      access_ip: ${ip}
      ansible_user: ${ansible_user}
%{ endfor ~}
  children:
    kube_control_plane:
      hosts:
        node0: {}
    kube_node:
      hosts:
%{ for idx, ip in ips ~}
        node${idx}: {}
%{ endfor ~}
    etcd:
      hosts:
        node0: {}
    kube_proxy:
      hosts:
%{ for idx, ip in ips ~}
        node${idx}: {}
%{ endfor ~}
    k8s_cluster:
      children:
        kube_control_plane: {}
        kube_node: {}
