import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.100', username='rock', password='rock', timeout=10)

def run(cmd, timeout=10):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode().strip()
    err = e.read().decode().strip()
    combined = (out + '\n' + err).strip()
    if combined:
        print(combined)
    return combined

print("=" * 55)
print("1. All sound cards")
print("=" * 55)
run("cat /proc/asound/cards")

print("\n" + "=" * 55)
print("2. Playback hardware devices (aplay -l)")
print("=" * 55)
run("aplay -l 2>&1")

print("\n" + "=" * 55)
print("3. USB card details")
print("=" * 55)
run("cat /proc/asound/card2/stream0 2>/dev/null | head -30 || echo 'no stream info'")

print("\n" + "=" * 55)
print("4. USB card capabilities (does it support PLAYBACK?)")
print("=" * 55)
run("grep -r 'Playback' /proc/asound/card2/ 2>/dev/null | head -10 || echo 'none'")
run("grep -r 'Capture' /proc/asound/card2/ 2>/dev/null | head -10 || echo 'none'")

print("\n" + "=" * 55)
print("5. Current ALSA config (default card)")
print("=" * 55)
run("cat /etc/asound.conf 2>/dev/null || echo 'no /etc/asound.conf'")
run("cat ~/.asoundrc 2>/dev/null || echo 'no ~/.asoundrc'")

print("\n" + "=" * 55)
print("6. Try playing beep on each card individually")
print("=" * 55)
# Try each card
for card in [0, 1, 2]:
    print(f"\n--- card {card} ---")
    result = run(f"speaker-test -D plughw:{card},0 -t sine -f 1000 -l 1 2>&1 | head -5 || true", 8)

print("\n" + "=" * 55)
print("7. ALSA mixer volumes (card 2 = USB)")
print("=" * 55)
run("amixer -c 2 scontents 2>&1 | head -30 || echo 'no controls'")

print("\n" + "=" * 55)
print("8. Check PulseAudio status")
print("=" * 55)
run("pulseaudio --check && echo 'PulseAudio running' || echo 'PulseAudio NOT running'")
run("pactl info 2>/dev/null | grep -E 'Default|Server' | head -5 || echo 'pactl not available'")
run("pactl list sinks short 2>/dev/null || echo 'no sinks'")

print("\n" + "=" * 55)
print("9. Try aplay with different devices and formats")
print("=" * 55)
# Generate 1s of 440Hz tone using python and pipe to aplay
gen_and_play = (
    "python3 -c \""
    "import struct,math;"
    "sr=16000;f=440;dur=1;"
    "data=struct.pack('<' + 'h'*sr*dur, "
    "*[int(32767*math.sin(2*math.pi*f*i/sr)) for i in range(sr*dur)]);"
    "import sys; sys.stdout.buffer.write(data)"
    "\""
)
for device in ["default", "plughw:2,0", "plughw:1,0", "plughw:0,0"]:
    print(f"\n>>> Testing device: {device}")
    result = run(
        f"{gen_and_play} | aplay -D {device} -r 16000 -f S16_LE -c 1 2>&1 | head -3 || true",
        10
    )

ssh.close()
