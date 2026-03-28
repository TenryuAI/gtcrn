#include <iostream>
#include <vector>
#include <atomic>
#include <thread>
#include <chrono>
#include <portaudio.h>
#include "AudioProcessor.h"

#ifdef _WIN32
#include <conio.h>
#else
// For non-Windows platforms, we'd need a different way to do non-blocking getch
// But the plan says we are targeting Windows <conio.h>
#endif

// Global state
std::atomic<bool> running(true);
std::atomic<int> current_mode(1); // 1: Dry, 2: Denoise
std::atomic<float> denoise_strength(0.8f);

AudioProcessor* g_processor = nullptr;

// PortAudio Callback
static int audioCallback(const void* inputBuffer, void* outputBuffer,
                         unsigned long framesPerBuffer,
                         const PaStreamCallbackTimeInfo* timeInfo,
                         PaStreamCallbackFlags statusFlags,
                         void* userData) {
    
    const float* in = static_cast<const float*>(inputBuffer);
    float* out = static_cast<float*>(outputBuffer);

    if (in == nullptr) {
        // If no input, just output silence
        for (unsigned int i = 0; i < framesPerBuffer; ++i) {
            out[i * 2] = 0.0f; // Left
            out[i * 2 + 1] = 0.0f; // Right
        }
        return paContinue;
    }

    // We process one block (256 frames) at a time
    // In a real robust app, we'd handle framesPerBuffer != 256
    // But we request exactly 256 frames from PortAudio
    if (framesPerBuffer != 256) {
        std::cerr << "Warning: framesPerBuffer is not 256!" << std::endl;
        return paContinue;
    }

    // Extract mono input (average of channels if stereo, or just take first channel)
    // Assuming input is mono or we just take the first channel
    // We requested 1 channel input, so in is just 256 floats
    
    float out_mono[256];
    
    float strength = (current_mode.load() == 2) ? denoise_strength.load() : 0.0f;
    
    g_processor->process_block(in, out_mono, strength);

    // Output is stereo (we requested 2 channels output)
    for (unsigned int i = 0; i < framesPerBuffer; ++i) {
        out[i * 2] = out_mono[i];     // Left
        out[i * 2 + 1] = out_mono[i]; // Right
    }

    return paContinue;
}

void input_thread() {
    while (running) {
#ifdef _WIN32
        if (_kbhit()) {
            int key = _getch();
            if (key == '1') {
                if (current_mode != 1) {
                    current_mode = 1;
                    std::cout << "\n--> Mode 1: Original sound (no denoise)" << std::endl;
                }
            } else if (key == '2') {
                if (current_mode != 2) {
                    current_mode = 2;
                    std::cout << "\n--> Mode 2: Denoised sound" << std::endl;
                }
            } else if (key == 'q' || key == 'Q' || key == 3) { // 3 is Ctrl+C
                running = false;
                std::cout << "\nExiting..." << std::endl;
                break;
            }
        }
#endif
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
}

int main(int argc, char* argv[]) {
    std::cout << "========================================" << std::endl;
    std::cout << "GTCRN Realtime Denoise (C++ ONNX Runtime)" << std::endl;
    std::cout << "========================================" << std::endl;

    std::string model_path = "gtcrn_simple.onnx";
    if (argc > 1) {
        model_path = argv[1];
    }

    try {
        std::cout << "Loading ONNX model: " << model_path << std::endl;
        g_processor = new AudioProcessor(model_path);
        std::cout << "Model loaded!" << std::endl;
    } catch (const std::exception& e) {
        std::cerr << "Failed to load model: " << e.what() << std::endl;
        return -1;
    }

    // Initialize PortAudio
    PaError err = Pa_Initialize();
    if (err != paNoError) {
        std::cerr << "PortAudio error: " << Pa_GetErrorText(err) << std::endl;
        return -1;
    }

    PaStream* stream;

    // We want 1 channel input, 2 channels output, 16000 Hz, float32
    int numInputChannels = 1;
    int numOutputChannels = 2;
    int sampleRate = 16000;
    int framesPerBuffer = 256;

    err = Pa_OpenDefaultStream(&stream,
                               numInputChannels,
                               numOutputChannels,
                               paFloat32,
                               sampleRate,
                               framesPerBuffer,
                               audioCallback,
                               nullptr);

    if (err != paNoError) {
        std::cerr << "PortAudio open stream error: " << Pa_GetErrorText(err) << std::endl;
        Pa_Terminate();
        return -1;
    }

    err = Pa_StartStream(stream);
    if (err != paNoError) {
        std::cerr << "PortAudio start stream error: " << Pa_GetErrorText(err) << std::endl;
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

    err = Pa_StopStream(stream);
    if (err != paNoError) {
        std::cerr << "PortAudio stop stream error: " << Pa_GetErrorText(err) << std::endl;
    }

    err = Pa_CloseStream(stream);
    if (err != paNoError) {
        std::cerr << "PortAudio close stream error: " << Pa_GetErrorText(err) << std::endl;
    }

    Pa_Terminate();
    delete g_processor;

    return 0;
}
