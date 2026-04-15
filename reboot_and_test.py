"""
Reboot RK3568 and verify USB audio is the default after reboot.
"""
import paramiko, time

HOST = "192.168.0.100"
USER = "rock"
PASS = "rock"

def connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=PASS, timeout=15)
    return ssh

def run(ssh, cmd, timeout=15):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode().strip()
    if out: print(out)
    return out

print("Rebooting RK3568...")
ssh = connect()
run(ssh, f"echo {PASS} | sudo -S reboot", 5)
ssh.close()

print("Waiting 30 seconds for reboot...")
time.sleep(30)

# Try to reconnect
for attempt in range(6):
    try:
        ssh = connect()
        print(f"\nReconnected after reboot (attempt {attempt+1})")
        break
    except Exception as e:
        print(f"  Attempt {attempt+1}/6: waiting... ({e})")
        time.sleep(10)
else:
    print("Could not reconnect. Please check device manually.")
    exit(1)

time.sleep(3)
print("\n=== After reboot: PulseAudio status ===")
uid = run(ssh, "id -u rock")
env = f"XDG_RUNTIME_DIR=/run/user/{uid}"
run(ssh, f"{env} pactl info 2>/dev/null | grep -E 'Default Sink|Default Source|Version'")

print("\n=== Sound cards ===")
run(ssh, "cat /proc/asound/cards")

print("\n=== Playback test (USB headphones) ===")
gen = "python3 -c \"import struct,math,sys;sr=48000;d=struct.pack('<'+'h'*sr*2,*[v for i in range(sr) for v in [int(25000*math.sin(2*3.14159*880*i/sr))]*2]);sys.stdout.buffer.write(d)\""
result = run(ssh, f"{env} {gen} | aplay -D default -r 48000 -f S16_LE -c 2 2>&1", 8)
if "Playing" in result:
    print("\nSUCCESS! USB audio is working after reboot.")
else:
    print(f"\nResult: {result}")

ssh.close()
