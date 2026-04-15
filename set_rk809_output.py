import paramiko

HOST = "192.168.0.100"
USER = "rock"
PASS = "rock"
RK809_SINK = "alsa_output.platform-rk809-sound.HiFi__hw_rockchiprk809__sink"
UID = "1001"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=10)

def run(cmd, timeout=12):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode().strip()
    if out: print(out)
    return out

def sudo(cmd, timeout=12):
    return run(f"echo {PASS} | sudo -S sh -c '{cmd}'", timeout)

env = f"XDG_RUNTIME_DIR=/run/user/{UID}"

# 1. Set PulseAudio default sink to rk809
print("Step 1: Set PulseAudio default sink to rk809")
run(f"{env} pactl set-default-sink '{RK809_SINK}'")
run(f"{env} pactl set-sink-mute   '{RK809_SINK}' 0")
run(f"{env} pactl set-sink-volume '{RK809_SINK}' 65536")
run(f"{env} pactl info | grep 'Default Sink'")

# 2. Set ALSA mixer playback path to HP (headphone)
print("\nStep 2: Set rk809 Playback Path to HP")
run("amixer -c rockchiprk809 sset 'Playback Path' HP 2>&1 || "
    "amixer -c 2 sset 'Playback Path' HP 2>&1")
run("amixer -c rockchiprk809 sget 'Playback Path' 2>/dev/null || "
    "amixer -c 2 sget 'Playback Path' 2>/dev/null")

# 3. Persist in /etc/pulse/default.pa
print("\nStep 3: Persist in /etc/pulse/default.pa")
sudo(f"sed -i 's|set-default-sink.*|set-default-sink   {RK809_SINK}|' /etc/pulse/default.pa")
run("grep 'set-default' /etc/pulse/default.pa")

# 4. Update /etc/asound.conf (keep pulse routing)
print("\nStep 4: Update /etc/asound.conf")
ASOUND = b"pcm.!default { type pulse }\nctl.!default { type pulse }\n"
sftp = ssh.open_sftp()
with sftp.open('/tmp/asound.conf', 'wb') as f:
    f.write(ASOUND)
sftp.close()
sudo("cp /tmp/asound.conf /etc/asound.conf")
sftp = ssh.open_sftp()
with sftp.open('/home/rock/.asoundrc', 'wb') as f:
    f.write(ASOUND)
sftp.close()

# 5. Save ALSA state
print("\nStep 5: Save ALSA state (alsactl store)")
sudo("alsactl store 2>&1 || true")

# 6. Playback test
print("\nStep 6: Playback test (440Hz beep via board headphone jack)")
gen = ("python3 -c \"import struct,math,sys;"
       "sr=48000;d=struct.pack('<'+'h'*sr*2,"
       "*[v for i in range(sr) for v in [int(25000*math.sin(2*3.14159*440*i/sr))]*2]);"
       "sys.stdout.buffer.write(d)\"")
result = run(f"{env} {gen} | aplay -D default -r 48000 -f S16_LE -c 2 2>&1", 8)
if "Playing" in result:
    print("SUCCESS! 440Hz beep should play through board headphone jack.")
else:
    print(f"Result: {result}")

ssh.close()
print("\nDone. Settings persist across reboots.")
