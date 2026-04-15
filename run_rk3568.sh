#!/bin/bash
# GTCRN RK3568 realtime denoiser runner

export LD_LIBRARY_PATH=/home/rock/onnxruntime-linux-aarch64-1.17.1/lib:$LD_LIBRARY_PATH
export XDG_RUNTIME_DIR=/run/user/$(id -u)

# Prefer a USB audio card for both input and output.
# Pick the first non-monitor USB sink/source reported by PulseAudio.
USB_SINK="$(pactl list sinks short 2>/dev/null | grep -i usb | awk 'NR==1{print $2}')"
USB_SOURCE="$(pactl list sources short 2>/dev/null | grep -i usb | grep -vi monitor | awk 'NR==1{print $2}')"

if [ -n "$USB_SINK" ]; then
    pactl set-default-sink "$USB_SINK" 2>/dev/null
fi
if [ -n "$USB_SOURCE" ]; then
    pactl set-default-source "$USB_SOURCE" 2>/dev/null
fi

echo "Audio preference:"
echo "  USB sink   : ${USB_SINK:-not found}"
echo "  USB source : ${USB_SOURCE:-not found}"
echo ""

cd /home/rock/gtcrn/build
# Suppress ALSA noise messages, keep real errors
./gtcrn_realtime "$@" 2> >(grep -vE "ALSA lib|Expression|Unable to find" >&2)
