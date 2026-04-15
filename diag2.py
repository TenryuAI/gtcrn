import paramiko

HOST = "192.168.0.100"
USER = "rock"
PASS = "rock"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=10)

def run(cmd, timeout=15):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode().strip()
    if out: print(out)
    return out

env = "XDG_RUNTIME_DIR=/run/user/1001"

print("=== Loaded PA modules that might affect default device ===")
run(f"{env} pactl list modules short 2>/dev/null | grep -iE 'switch|connect|default|restore|device'")

print("\n=== Full PA default.pa (relevant lines) ===")
run("grep -n 'switch\\|restore\\|default\\|connect' /etc/pulse/default.pa | grep -v '^#'")

print("\n=== Current default-sink state file (raw) ===")
run("xxd ~/.config/pulse/*-default-sink 2>/dev/null | head -3")
run("cat ~/.config/pulse/*-default-sink 2>/dev/null")

print("\n=== crontab -l ===")
run("crontab -l 2>/dev/null || echo 'empty'")

print("\n=== All modules containing 'switch' ===")
run(f"{env} pactl list modules 2>/dev/null | grep -A2 -B2 'switch'")

ssh.close()
