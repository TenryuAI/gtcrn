import paramiko, time
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.100', username='rock', password='rock', timeout=10)

def run(cmd, timeout=15):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode().strip()
    if out: print(out)
    return out

print("Restarting PulseAudio to test persistence...")
run("pulseaudio -k; sleep 2; pulseaudio --start --daemonize; sleep 1")
print("\nPulseAudio defaults after restart:")
run("pactl info 2>/dev/null | grep -E 'Default'")

print("\nALSA test via default (-> PulseAudio -> USB):")
gen = "python3 -c \"import struct,math,sys;sr=48000;d=struct.pack('<'+'h'*sr*2,*[v for i in range(sr) for v in [int(25000*math.sin(2*3.14159*880*i/sr))]*2]);sys.stdout.buffer.write(d)\""
result = run(f"{gen} | aplay -D default -r 48000 -f S16_LE -c 2 2>&1", 8)
if "Playing" in result:
    print("AUDIO WORKS! You should hear a 1-second 880Hz beep in your headphones.")

ssh.close()
