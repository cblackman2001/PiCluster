#!/usr/bin/env python3

# Run from inside same directory - python ui.py

import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
from threading import Thread
import queue
import ipaddress
import time
import traceback
import os
import json
import subprocess
import shutil

def run_shell(cmd, logger, env=None, cwd=None):
    logger(f"$ {cmd}")
    process = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        cwd=cwd,
        text=True,
        bufsize=1,
        universal_newlines=True,
    )
    try:
        for line in process.stdout:
            if line is None:
                break
            logger(line.rstrip())
    except Exception as exc:
        logger(f"[run_shell] exception {exc}")
    process.wait()
    logger(f"[run_shell] exit code {process.returncode}")
    return process.returncode

# ---------- run the Kubespray setup and runbook ----------
def Kubespray_setup(ips, checkbox_on, logger, extra_vars):

    env = os.environ.copy()
    if extra_vars is None:
        extra_vars = {}
    ssh_password = extra_vars.get("ssh_password", "")
    ansible_user = extra_vars.get("ansible_user", "")
    tf_ips = extra_vars.get("ips", "")

    if isinstance(tf_ips, (list, tuple)):
        tf_ips_str = json.dumps(tf_ips)
    else:
        tf_ips_str = str(tf_ips)

    env["TF_VAR_ssh_password"] = ssh_password
    env["TF_VAR_ansible_user"] = ansible_user
    env["TF_VAR_ips"] = tf_ips_str

    logger("Environment TF_VARs set:")
    logger(f" - TF_VAR_ssh_password = {'***' if ssh_password else '<empty>'}")
    logger(f" - TF_VAR_ansible_user = {ansible_user or '<empty>'}")
    logger(f" - TF_VAR_ips = {tf_ips_str or '<empty>'}")

    # Running Terraform commands to setup. Which creates a playbook yaml for all nodes and settings (for kubespray), a regular one for all nodes (for OS settings) and finally one for the master node (for chart deployments etc).
    try:
        rc = run_shell("terraform init", logger, env=env)
        if rc != 0:
            logger("terraform init failed, aborting.")
            return

        rc = run_shell("terraform apply -auto-approve", logger, env=env)
        if rc != 0:
            logger("terraform apply failed, aborting.")
            return

        logger("Sleeping 10 seconds")
        time.sleep(10)

        ansible_cmd = (
            'ansible-playbook -i generated/all_hosts.yaml playbooks/bootstrap_ssh.yaml '
            f'-u "{ansible_user}" --become --become-user=root -b -v '
            f'--extra-vars ansible_become_pass="{ssh_password}"'
        )
        run_shell(ansible_cmd, logger, env=env)

        logger("sleeping for 30 seconds")
        time.sleep(30)

        if os.path.isdir("kubespray"):
            logger("Removing existing 'kubespray' directory")
            try:
                shutil.rmtree("kubespray")
            except Exception as exc:
                run_shell("rm -rf kubespray", logger, env=env)

        run_shell('git clone --branch "v2.29.0" https://github.com/kubernetes-sigs/kubespray.git kubespray', logger, env=env)

        run_shell("mkdir -p kubespray/inventory/mycluster", logger, env=env)
        run_shell("cp -f generated/hosts.yaml kubespray/inventory/mycluster/hosts.yaml", logger, env=env)
        run_shell("mkdir -p kubespray/inventory/mycluster/group_vars", logger, env=env)
        run_shell("cp -r kubespray/inventory/sample/group_vars kubespray/inventory/mycluster", logger, env=env)
        
        run_shell("python3 -m venv .venv", logger, env=env, cwd="kubespray")
        run_shell("./.venv/bin/pip install -r requirements.txt", logger, env=env, cwd="kubespray")

        cluster_cmd = (
            './.venv/bin/ansible-playbook -i inventory/mycluster/hosts.yaml cluster.yml '
            f"-u \"{ansible_user}\" "
            "--private-key \"../playbooks/RSA\" "
            "--become --become-user=root -b -v"
        )
        run_shell(cluster_cmd, logger, env=env, cwd="kubespray")

    except Exception as exc:
        logger(f"Exception during Kubespray setup {exc}")
        logger(traceback.format_exc())
    finally:
        logger("Kubespray Setup finished")


def Apply_charts(ips, checkbox_on, logger, extra_vars=None):

    if extra_vars is None:
        extra_vars = {}
    metallb_range = extra_vars.get("metallb_ip_range", "")

    logger("Applying charts...")
    try:
        cmd = (
            'ansible-playbook -i generated/node0.yaml playbooks/setup.yaml '
            '--become --become-user=root -b -v'
        )
        if metallb_range:
            cmd += f' --extra-vars "metallb_ip_range={metallb_range}"'
        else:
            logger("WARNING: No MetalLB IP range provided, MetalLB will not be configured.")

        rc = run_shell(cmd, logger)
        if rc != 0:
            logger("Chart deployment failed.")
            return
    except Exception as exc:
        logger(f"Exception during chart deployment: {exc}")
        logger(traceback.format_exc())
    finally:
        logger("Chart deployment finished")


def run_internal_function(func, q, tag, checkbox_on, ips, extra_vars=None):

    def logger(msg):
        q.put(("log", tag, msg))

    q.put(("log", tag, f"--- Worker {tag} starting at {time.strftime('%H:%M:%S')} ---"))
    try:
        func(ips, checkbox_on, logger, extra_vars)
    except Exception as exc:
        tb = traceback.format_exc()
        q.put(("error", tag, f"Exception in worker {tag}: {exc}"))
        q.put(("error", tag, tb))
    finally:
        q.put(("log", tag, f"--- Worker {tag} finished at {time.strftime('%H:%M:%S')} ---"))
        q.put(("done", tag, 0))


class RunnerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Tk Internal Script Runner (with TF vars)")
        self.geometry("920x680")
        self.resizable(True, True)

        self.q = queue.Queue()
        self.active = {"A": False, "B": False}

        self._build_ui()

        self._append_log("App started. Activate different scripts to setup nodes and apply charts.")
        self._poll_queue()

    def _normalize_tf_ips(self, raw: str):
        """
        Accepts the raw string from self.tf_ips_entry and returns (ips_list, errors_list).
        Supports JSON list (e.g. ["1.1.1.1"]), or comma/newline separated strings.
        """
        raw = (raw or "").strip()
        if not raw:
            return [], []

        try:
            parsed = json.loads(raw)
            if isinstance(parsed, (list, tuple)):
                ips = [str(x).strip() for x in parsed if str(x).strip()]
                return ips, []
        except Exception:
            pass

        # fallback split by comma / newline
        parts = [p.strip() for p in raw.replace(",", "\n").splitlines() if p.strip()]
        return parts, []

    def _build_ui(self):
        pad = {"padx": 8, "pady": 6}

        top_frame = ttk.Frame(self)
        top_frame.pack(fill="x", **pad)

        # Terraform variable inputs
        tf_frame = ttk.LabelFrame(self, text="Terraform variables")
        tf_frame.pack(fill="x", padx=8, pady=(8, 0))

        # ssh_password
        ttk.Label(tf_frame, text="ssh_password:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.tf_ssh_password = ttk.Entry(tf_frame, show="*")
        self.tf_ssh_password.grid(row=0, column=1, sticky="ew", padx=6, pady=4)

        # ansible_user
        ttk.Label(tf_frame, text="ansible_user:").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.tf_ansible_user = ttk.Entry(tf_frame)
        self.tf_ansible_user.grid(row=1, column=1, sticky="ew", padx=6, pady=4)
        self.tf_ansible_user.insert(0, 'ubuntu')

        # TF_VAR_ips
        ttk.Label(tf_frame, text="TF_VAR_ips (JSON list or comma-separated) First is Master node:").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        self.tf_ips_entry = ttk.Entry(tf_frame)
        self.tf_ips_entry.grid(row=2, column=1, sticky="ew", padx=6, pady=4)
        self.tf_ips_entry.insert(0, '["1.1.1.1", "1.1.1.2"]')

        tf_frame.columnconfigure(1, weight=1)

        sframe = ttk.Frame(self)
        sframe.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(sframe, text="Kubespray Setup: executes the integrated TF/Ansible to build various playbooks and setups kubespray").grid(row=0, column=0, sticky="w")
        self.run_a_btn = ttk.Button(sframe, text="Run Kubespray setup", command=lambda: self._on_run("A"))
        self.run_a_btn.grid(row=1, column=0, sticky="w", padx=6, pady=6)

        chart_frame = ttk.LabelFrame(self, text="Chart settings")
        chart_frame.pack(fill="x", padx=8, pady=(8, 0))

        ttk.Label(chart_frame, text="MetalLB IP range (e.g. 1.1.1.1.1-1.1.1.1.1):").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.metallb_range = ttk.Entry(chart_frame)
        self.metallb_range.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        chart_frame.columnconfigure(1, weight=1)

        sframe2 = ttk.Frame(self)
        sframe2.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Label(sframe2, text="Installs MetalLB, ingress-nginx, and kube-prometheus-stack with Grafana").grid(row=0, column=0, sticky="w")
        self.run_b_btn = ttk.Button(sframe2, text="Run Charts", command=lambda: self._on_run("B"))
        self.run_b_btn.grid(row=1, column=0, sticky="w", padx=6, pady=6)

        ctrl_frame = ttk.Frame(self)
        ctrl_frame.pack(fill="x", padx=8, pady=(8, 0))
        ttk.Button(ctrl_frame, text="Validate IPs", command=self._validate_ips).pack(side="left")
        self.status_lbl = ttk.Label(ctrl_frame, text="Idle")
        self.status_lbl.pack(side="right")

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=8, pady=8)

        ttk.Label(self, text="Output / Log:").pack(anchor="w", padx=8)
        self.log = ScrolledText(self, height=20, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _append_log(self, text, tag=None):
        prefix = f"[{tag}] " if tag else ""
        print(prefix + text)
        self.log.configure(state="normal")
        self.log.insert("end", prefix + text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _validate_ips(self):
        raw = self.tf_ips_entry.get().strip()
        ips, errors = self._normalize_tf_ips(raw)

        # validate each ip using ipaddress
        val_errors = []
        valid_ips = []
        for ip in ips:
            try:
                ipaddress.ip_address(ip)
                valid_ips.append(ip)
            except ValueError:
                val_errors.append(f"Invalid IP address: {ip}")

        if val_errors:
            self._append_log("IP validation failed:")
            for e in val_errors:
                self._append_log(e)
            self.status_lbl.config(text="IP validation failed")
        else:
            self._append_log("All IPs valid: " + (", ".join(valid_ips) or "<none>"))
            self.status_lbl.config(text=f"{len(valid_ips)} IP(s) valid")

    def _collect_tf_vars(self):
        ssh_password = self.tf_ssh_password.get().strip()
        ansible_user = self.tf_ansible_user.get().strip()
        tf_ips_raw = self.tf_ips_entry.get().strip()

        tf_ips_parsed = tf_ips_raw
        try:
            parsed = json.loads(tf_ips_raw)
            tf_ips_parsed = parsed
        except Exception:
            if tf_ips_raw:
                tf_ips_parsed = [s.strip() for s in tf_ips_raw.replace(",", "\n").splitlines() if s.strip()]
            else:
                tf_ips_parsed = []

        return {
            "ssh_password": ssh_password,
            "ansible_user": ansible_user,
            "ips": tf_ips_parsed,
        }

    def _on_run(self, tag):
        if self.active[tag]:
            messagebox.showinfo("Already running", f"Script {tag} is already running.")
            return

        raw = self.tf_ips_entry.get().strip()
        ips, _ = self._normalize_tf_ips(raw)

        val_errors = []
        for ip in ips:
            try:
                ipaddress.ip_address(ip)
            except ValueError:
                val_errors.append(f"Invalid IP address: {ip}")

        if val_errors:
            self._append_log("IP validation failed, not starting script:")
            for e in val_errors:
                self._append_log(e)
            return

        func = Kubespray_setup if tag == "A" else Apply_charts
        if tag == "A":
            extra_vars = self._collect_tf_vars()
        else:
            extra_vars = {"metallb_ip_range": self.metallb_range.get().strip()}

        self.active[tag] = True
        self.status_lbl.config(text=f"Running script {tag}...")
        if tag == "A":
            self.run_a_btn.config(state="disabled")
        else:
            self.run_b_btn.config(state="disabled")

        self._append_log(f"Starting background thread for script {tag}", tag)
        t = Thread(
            target=run_internal_function,
            args=(func, self.q, tag, False, ips, extra_vars),
            daemon=True,
        )
        t.start()

    def _poll_queue(self):
        try:
            while True:
                typ, tag, payload = self.q.get_nowait()
                if typ == "log":
                    self._append_log(payload, tag)
                elif typ == "error":
                    self._append_log("[ERROR] " + payload, tag)
                elif typ == "done":
                    self._append_log(f"Worker {tag} signalled done (code {payload})", tag)
                    self.active[tag] = False
                    if tag == "A":
                        self.run_a_btn.config(state="normal")
                    else:
                        self.run_b_btn.config(state="normal")
                    self.status_lbl.config(text="Idle")
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

if __name__ == "__main__":
    app = RunnerApp()
    app.mainloop()