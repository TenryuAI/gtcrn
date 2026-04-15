#include <iostream>
#include <atomic>
#include <thread>
#include <chrono>
#include <csignal>
#include <termios.h>
#include <unistd.h>
#include <fcntl.h>
#include "portaudio.h"
#include "AudioProcessor.h"

// Global state
std::atomic<bool> running(true);
std::atomic<int> current_mode(1);      // 1: Original, 2: Denoised
std::atomic<float> denoise_strength(0.8f);

AudioProcessor48k* g_processor = nullptr;

// PortAudio Callback
static int audioCallback(const void* inputBuffer, void* outputBuffer,
                         unsigned long framesPerBuffer,
                         const PaStreamCallbackTimeInfo* timeInfo,
                         PaStreamCallbackFlags statusFlags,
                         void* userData) {
    const float* in = static_cast<const float*>(inputBuffer);
    float* out = static_cast<float*>(outputBuffer);

    if (framesPerBuffer != AudioProcessor48k::IO_BLOCK_SIZE) {
        for (unsigned int i = 0; i < framesPerBuffer * 2; ++i) out[i] = 0.0f;
        return paContinue;
    }

    if (in == nullptr) {
        for (unsigned int i = 0; i < framesPerBuffer * 2; ++i) out[i] = 0.0f;
        return paContinue;
    }

    float out_mono[AudioProcessor48k::IO_BLOCK_SIZE];
    float strength = (current_mode.load() == 2) ? denoise_strength.load() : 0.0f;
    g_processor->process_block(in, out_mono, strength);

    for (unsigned int i = 0; i < framesPerBuffer; ++i) {
        out[i * 2]     = out_mono[i];
        out[i * 2 + 1] = out_mono[i];
    }
    return paContinue;
}

// Signal handler for Ctrl+C
void signal_handler(int sig) {
    running = false;
    std::cout << "\nExiting..." << std::endl;
}

// Non-blocking keyboard input thread using termios
struct TerminalRaw {
    struct termios old_tio;
    int old_flags;

    TerminalRaw() {
        tcgetattr(STDIN_FILENO, &old_tio);
        struct termios new_tio = old_tio;
        new_tio.c_lflag &= ~(ICANON | ECHO);
        tcsetattr(STDIN_FILENO, TCSANOW, &new_tio);
        old_flags = fcntl(STDIN_FILENO, F_GETFL, 0);
        fcntl(STDIN_FILENO, F_SETFL, old_flags | O_NONBLOCK);
    }

    ~TerminalRaw() {
        tcsetattr(STDIN_FILENO, TCSANOW, &old_tio);
        fcntl(STDIN_FILENO, F_SETFL, old_flags);
    }
};

void input_thread() {
    TerminalRaw raw;
    while (running) {
        char key = 0;
        if (read(STDIN_FILENO, &key, 1) == 1) {
            if (key == '1') {
                if (current_mode.load() != 1) {
                    current_mode = 1;
                    std::cout << "\n--> Mode 1: Original sound (no denoise)" << std::endl;
                }
            } else if (key == '2') {
                if (current_mode.load() != 2) {
                    current_mode = 2;
                    std::cout << "\n--> Mode 2: Denoised sound" << std::endl;
                }
            } else if (key == 'q' || key == 'Q' || key == 3) {
                running = false;
                std::cout << "\nExiting..." << std::endl;
                break;
            }
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
}

int main(int argc, char* argv[]) {
    std::signal(SIGINT, signal_handler);

    std::cout << "========================================" << std::endl;
    std::cout << "GTCRN Realtime Denoise - RK3568 (Linux)" << std::endl;
    std::cout << "========================================" << std::endl;

    std::string model_path = "gtcrn_simple.onnx";
    if (argc > 1) model_path = argv[1];

    try {
        std::cout << "Loading ONNX model: " << model_path << std::endl;
        g_processor = new AudioProcessor48k(model_path);
        std::cout << "Model loaded!" << std::endl;
    } catch (const std::exception& e) {
        std::cerr << "Failed to load model: " << e.what() << std::endl;
        return -1;
    }

    PaError err = Pa_Initialize();
    if (err != paNoError) {
        std::cerr << "PortAudio error: " << Pa_GetErrorText(err) << std::endl;
        return -1;
    }

    // List audio devices
    int num_devices = Pa_GetDeviceCount();
    std::cout << "\nAvailable audio devices:" << std::endl;
    int pulse_device   = -1;
    int default_device = -1;
    int usb_duplex_dev = -1;  // USB device with both input and output
    int usb_in_dev     = -1;  // Any USB input device
    int usb_out_dev    = -1;  // Any USB output device
    int rk809_out_dev  = -1;  // Board headphone output
    for (int i = 0; i < num_devices; ++i) {
        const PaDeviceInfo* info = Pa_GetDeviceInfo(i);
        std::string name = info->name;
        std::cout << "  [" << i << "] " << name
                  << " (in=" << info->maxInputChannels
                  << ", out=" << info->maxOutputChannels << ")" << std::endl;
        if (name == "pulse" &&
            info->maxInputChannels > 0 && info->maxOutputChannels > 0)
            pulse_device = i;
        if (name == "default" &&
            info->maxInputChannels > 0 && info->maxOutputChannels > 0)
            default_device = i;
        if (name.find("USB") != std::string::npos || name.find("usb") != std::string::npos) {
            if (info->maxInputChannels > 0 && info->maxOutputChannels > 0)
                usb_duplex_dev = i;
            if (info->maxInputChannels > 0)
                usb_in_dev = i;
            if (info->maxOutputChannels > 0)
                usb_out_dev = i;
        }
        if (info->maxOutputChannels > 0 && name.find("rk809") != std::string::npos)
            rk809_out_dev = i;
    }

    PaStream* stream = nullptr;
    PaError open_err = paDeviceUnavailable;

    auto try_open = [&](int in_dev, int out_dev, const char* desc) -> bool {
        if (in_dev < 0 || out_dev < 0) return false;
        const PaDeviceInfo* in_info  = Pa_GetDeviceInfo(in_dev);
        const PaDeviceInfo* out_info = Pa_GetDeviceInfo(out_dev);
        PaStreamParameters inp, outp;
        inp.device          = in_dev;
        inp.channelCount    = 1;
        inp.sampleFormat    = paFloat32;
        inp.suggestedLatency = in_info->defaultLowInputLatency;
        inp.hostApiSpecificStreamInfo = nullptr;
        outp.device         = out_dev;
        outp.channelCount   = 2;
        outp.sampleFormat   = paFloat32;
        outp.suggestedLatency = out_info->defaultLowOutputLatency;
        outp.hostApiSpecificStreamInfo = nullptr;
        open_err = Pa_OpenStream(&stream, &inp, &outp,
                                 AudioProcessor48k::IO_SAMPLE_RATE,
                                 AudioProcessor48k::IO_BLOCK_SIZE,
                                 paClipOff, audioCallback, nullptr);
        if (open_err == paNoError) {
            std::cout << "Audio: " << desc
                      << "\n  Input:  " << in_info->name
                      << "\n  Output: " << out_info->name << std::endl;
            return true;
        }
        std::cerr << "  [" << desc << "] failed: " << Pa_GetErrorText(open_err) << std::endl;
        return false;
    };

    bool opened = false;
    // 1st try: single USB duplex device for both input/output
    if (!opened && usb_duplex_dev >= 0)
        opened = try_open(usb_duplex_dev, usb_duplex_dev, "USB duplex device (direct)");
    // 2nd try: USB mic input + rk809 board HP output
    if (!opened && usb_in_dev >= 0 && rk809_out_dev >= 0)
        opened = try_open(usb_in_dev, rk809_out_dev, "USB input + rk809 output (direct)");
    // 3rd try: real PulseAudio duplex device (routes via PA default sink/source)
    if (!opened && pulse_device >= 0)
        opened = try_open(pulse_device, pulse_device, "PulseAudio duplex");
    // 4th try: USB input + PulseAudio output
    if (!opened && usb_in_dev >= 0 && pulse_device >= 0)
        opened = try_open(usb_in_dev, pulse_device, "USB mic + PulseAudio out");
    // 5th try: ALSA/Pulse default device
    if (!opened && default_device >= 0)
        opened = try_open(default_device, default_device, "Default duplex");
    // 6th try: default stream API
    if (!opened) {
        open_err = Pa_OpenDefaultStream(&stream, 1, 2, paFloat32,
                                        AudioProcessor48k::IO_SAMPLE_RATE,
                                        AudioProcessor48k::IO_BLOCK_SIZE,
                                        audioCallback, nullptr);
        if (open_err == paNoError) {
            opened = true;
            std::cout << "Audio: PortAudio default stream" << std::endl;
        }
    }
    if (!opened) {
        std::cerr << "Failed to open any audio stream: " << Pa_GetErrorText(open_err) << std::endl;
        Pa_Terminate();
        return -1;
    }

    err = Pa_StartStream(stream);
    if (err != paNoError) {
        std::cerr << "Pa_StartStream error: " << Pa_GetErrorText(err) << std::endl;
        Pa_Terminate();
        return -1;
    }

    std::cout << "\n>>> WEAR HEADPHONES to avoid feedback! <<<" << std::endl;
    std::cout << "Controls:" << std::endl;
    std::cout << "  Press 1: Original sound (no denoise) [default]" << std::endl;
    std::cout << "  Press 2: Denoised sound" << std::endl;
    std::cout << "  Press q or Ctrl+C: Exit" << std::endl;
    std::cout << "========================================\n" << std::endl;

    std::thread t(input_thread);
    while (running) {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    t.join();

    Pa_StopStream(stream);
    Pa_CloseStream(stream);
    Pa_Terminate();
    delete g_processor;
    return 0;
}
