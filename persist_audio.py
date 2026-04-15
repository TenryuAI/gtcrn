"""
Make USB audio the persistent default by appending to /etc/pulse/default.pa.
This runs every time PulseAudio starts (on every reboot).
"""
import paramiko

HOST = "192.168.0.100"
USER = "rock"
PASS = "rock"

USB_SINK   = "alsa_output.usb-KUAIYU_ELECTRONIC_KUAIYU_USB_MIC-00.analog-stereo"
USB_SOURCE = "alsa_input.usb-KUAIYU_ELECTRONIC_KUAIYU_USB_MIC-00.analog-stereo"

APPEND_BLOCK = f"""
### GTCRN: USB audio as default (do not remove) ###
load-module module-switch-on-connect
set-default-sink   {USB_SINK}
set-default-source {USB_SOURCE}
### END GTCRN ###
"""

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=10)

def run(cmd, timeout=15):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode().strip()
    if out: print(out)
    return out

def sudo(cmd, timeout=15):
    return run(f"echo {PASS} | sudo -S sh -c '{cmd}'", timeout)

# Check if already patched
existing = run("cat /etc/pulse/default.pa 2>/dev/null | tail -10")
if "GTCRN" in existing:
    print("Already patched. Removing old block...")
    sudo("sed -i '/### GTCRN/,/### END GTCRN ###/d' /etc/pulse/default.pa")

# Append to /etc/pulse/default.pa
print("Appending USB audio defaults to /etc/pulse/default.pa...")
sftp = ssh.open_sftp()
with sftp.open('/tmp/pa_append.conf', 'wb') as f:
    f.write(APPEND_BLOCK.encode('utf-8'))
sftp.close()
sudo("cat /tmp/pa_append.conf >> /etc/pulse/default.pa")
sudo("rm /tmp/pa_append.conf")

print("\nLast 15 lines of /etc/pulse/default.pa:")
run("tail -15 /etc/pulse/default.pa")

# Verify current session still works (PulseAudio is already running)
print("\nCurrent PulseAudio defaults (before reboot):")
run("pactl info 2>/dev/null | grep -E 'Default Sink|Default Source'")

# Set current session immediately
run(f"pactl set-default-sink   '{USB_SINK}'   2>/dev/null || true")
run(f"pactl set-default-source '{USB_SOURCE}' 2>/dev/null || true")
run(f"pactl set-sink-mute   '{USB_SINK}' 0 2>/dev/null || true")
run(f"pactl set-sink-volume '{USB_SINK}' 65536 2>/dev/null || true")

print("\nUpdated PulseAudio defaults:")
run("pactl info 2>/dev/null | grep -E 'Default Sink|Default Source'")

# Quick playback test
print("\n=== Playback test (1s 880Hz beep, should hear in USB headphones) ===")
gen = (
    "python3 -c \""
    "import struct,math,sys;"
    "sr=48000;"
    "d=struct.pack('<'+'h'*sr*2,"
    "*[v for i in range(sr) for v in [int(25000*math.sin(2*3.14159*880*i/sr))]*2]);"
    "sys.stdout.buffer.write(d)\""
)
result = run(f"{gen} | aplay -D default -r 48000 -f S16_LE -c 2 2>&1", 8)
if "Playing" in result:
    print("\nSUCCESS! Beep should have played in USB headphones.")
else:
    print(f"Result: {result}")

ssh.close()
print()
print("Persistence: Changes written to /etc/pulse/default.pa")
print("Reboot the board to confirm settings survive.")
