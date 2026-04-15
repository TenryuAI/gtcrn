import paramiko, time
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.100', username='rock', password='rock', timeout=10)

def run(cmd, timeout=15):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode().strip()
    if out: print(out)
    return out

# Get user ID
uid = run("id -u rock").strip()
print(f"User UID: {uid}")

# Restart PulseAudio with correct runtime environment
# XDG_RUNTIME_DIR is required for PulseAudio socket
env = f"export XDG_RUNTIME_DIR=/run/user/{uid}; export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus"
run(f"{env}; pulseaudio --start --log-target=syslog 2>&1 || true", 8)
run("sleep 2")

# Test
result = run(f"{env}; pactl info 2>/dev/null | grep -E 'Default Sink|Default Source'")
if not result:
    print("PulseAudio not responding, trying systemd user service...")
    run(f"loginctl enable-linger rock 2>/dev/null || true")
    run(f"XDG_RUNTIME_DIR=/run/user/{uid} systemctl --user start pulseaudio 2>&1 || true")
    run("sleep 2")
    result = run(f"XDG_RUNTIME_DIR=/run/user/{uid} pactl info 2>/dev/null | grep Default || echo 'still not running'")

print("\nPulseAudio status:")
run(f"XDG_RUNTIME_DIR=/run/user/{uid} pactl info 2>/dev/null | grep -E 'Default|Version' || echo 'PulseAudio offline'")

# Test audio
print("\nPlayback test:")
gen = "python3 -c \"import struct,math,sys;sr=48000;d=struct.pack('<'+'h'*sr*2,*[v for i in range(sr) for v in [int(25000*math.sin(2*3.14159*880*i/sr))]*2]);sys.stdout.buffer.write(d)\""
result = run(
    f"XDG_RUNTIME_DIR=/run/user/{uid} {gen} | aplay -D default -r 48000 -f S16_LE -c 2 2>&1",
    8
)
if "Playing" in result:
    print("SUCCESS! 880Hz beep played through USB headphones.")

ssh.close()
