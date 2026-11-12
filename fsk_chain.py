#!/usr/bin/env python3
"""
Part 1 - FSK modulator / demodulator demo
==========================================

This is a *behavioural* simulation of the FSK link that feeds the CAN-FD
payload.  It is not a model of a real RF channel or of the RM46/S32
peripherals - it only demonstrates that a bit stream can be modulated,
corrupted with noise, and recovered.

    bit '0' -> 1 kHz
    bit '1' -> 2 kHz
    fs      = 48 kHz
    rate    = 100 bit/s  (480 samples per bit)

The recovered bytes are written to recovered.hex for Part 2 to use.
"""

import os
import time

import numpy as np
import matplotlib

matplotlib.use("Agg")              # headless: no GUI window needed for the demo
import matplotlib.pyplot as plt

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------
FS          = 48_000          # sample rate (Hz)
BIT_RATE    = 100             # bits per second
SPB         = FS // BIT_RATE  # 480 samples per bit
F0          = 1_000           # frequency used for a '0' bit (Hz)
F1          = 2_000           # frequency used for a '1' bit (Hz)
N_BYTES     = 8
N_BITS      = N_BYTES * 8
NOISE_SIGMA = 0.45            # AWGN amplitude; still well inside the margin
SEED        = 2026            # fixed seed -> repeatable demo (set None for random)

OUT_DIR = "out"
os.makedirs(OUT_DIR, exist_ok=True)


def make_bits(seed=SEED):
    """Generate N_BITS random bits."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 2, N_BITS).astype(int)


def fsk_modulate(bits):
    """Continuous-phase FSK.  A cumulative phase avoids clicks at bit edges."""
    freq = np.repeat(np.where(bits == 0, F0, F1), SPB)
    phase = 2.0 * np.pi * np.cumsum(freq) / FS
    return np.sin(phase)


def fsk_demodulate(rx, n_bits):
    """
    Non-coherent energy detector.

    For every bit window we correlate the received samples against a complex
    exponential at 1 kHz and at 2 kHz.  Whichever tone has more energy wins.
    This is the same idea as two band-pass filters + envelope detectors, but
    it needs no external DSP library.

    Returns (bits, metric) where metric = (E1 - E0)/(E1 + E0).  A positive
    metric means "1", negative means "0"; the distance from zero is the margin.
    """
    t_bit = np.arange(SPB) / FS
    ref0 = np.exp(-2j * np.pi * F0 * t_bit)
    ref1 = np.exp(-2j * np.pi * F1 * t_bit)

    recovered = np.zeros(n_bits, dtype=int)
    metric = np.zeros(n_bits)
    for k in range(n_bits):
        seg = rx[k * SPB:(k + 1) * SPB]
        e0 = abs(np.dot(seg, ref0)) ** 2
        e1 = abs(np.dot(seg, ref1)) ** 2
        recovered[k] = 1 if e1 > e0 else 0
        metric[k] = (e1 - e0) / (e1 + e0 + 1e-12)
    return recovered, metric


def bits_to_bytes(bits):
    """MSB-first packing: first 8 bits -> first byte."""
    out = bytearray()
    for i in range(0, len(bits), 8):
        byte = 0
        for b in bits[i:i + 8]:
            byte = (byte << 1) | int(b)
        out.append(byte)
    return bytes(out)


def plot_result(tx_bits, tx_wave, rx_wave, metric, rx_bits, errors, path):
    """Four panels: input bits, FSK waveform zoom, detector margin, recovered bits."""
    zoom_bits = min(8, len(tx_bits))
    n_zoom = zoom_bits * SPB
    t_ms = np.arange(n_zoom) / FS * 1000.0

    fig = plt.figure(figsize=(14, 11))
    gs = fig.add_gridspec(4, 1, height_ratios=[1.0, 1.5, 1.0, 1.0], hspace=0.55)

    # --- input bits ---------------------------------------------------------
    ax = fig.add_subplot(gs[0])
    ax.step(np.arange(len(tx_bits)), tx_bits, where="post", color="#1f4e79", lw=1.6)
    ax.set_xlim(-0.5, len(tx_bits) - 0.5)
    ax.set_ylim(-0.3, 1.3)
    ax.set_yticks([0, 1])
    ax.set_ylabel("bit")
    ax.set_title("1) Transmitted bit stream (8 random bytes)", loc="left", fontsize=11)
    ax.grid(alpha=0.25)

    # --- waveform zoom ------------------------------------------------------
    ax = fig.add_subplot(gs[1])
    for k in range(zoom_bits):
        x0 = k * SPB / FS * 1000.0
        x1 = (k + 1) * SPB / FS * 1000.0
        ax.axvspan(x0, x1, color="#fff2cc" if tx_bits[k] == 0 else "#dbe5f1",
                   alpha=0.7, lw=0)
        ax.axvline(x0, color="gray", lw=0.5, alpha=0.6)
        ax.text((x0 + x1) / 2, 1.75, str(tx_bits[k]), ha="center", va="top",
                fontsize=10, fontweight="bold",
                color="#1f4e79" if tx_bits[k] == 0 else "#b22222")
    ax.plot(t_ms, rx_wave[:n_zoom], color="#2e8b57", lw=0.8,
            label="RX = FSK + noise")
    ax.set_xlim(0, n_zoom / FS * 1000.0)
    ax.set_ylim(-1.8, 2.1)
    ax.set_xlabel("time (ms)")
    ax.set_ylabel("amplitude")
    ax.set_title("2) FSK waveform, first %d bits (yellow = 1 kHz '0', blue = 2 kHz '1')"
                 % zoom_bits, loc="left", fontsize=11)
    ax.legend(loc="lower right", fontsize=8, framealpha=0.9)
    ax.grid(alpha=0.25)

    # --- detector margin ----------------------------------------------------
    ax = fig.add_subplot(gs[2])
    ax.bar(np.arange(len(metric)), metric, color="#6a3d9a", width=0.9)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xlim(-0.5, len(metric) - 0.5)
    ax.set_ylim(-1.05, 1.05)
    ax.set_xlabel("bit index")
    ax.set_ylabel("(E1-E0)/(E1+E0)")
    ax.set_title("3) Demodulator decision metric (sign gives the bit, distance from 0 is margin)",
                 loc="left", fontsize=11)
    ax.grid(alpha=0.25, axis="y")

    # --- recovered bits -----------------------------------------------------
    ax = fig.add_subplot(gs[3])
    ax.step(np.arange(len(rx_bits)), rx_bits, where="post", color="#7b3f00", lw=1.6)
    if errors.size:
        ax.scatter(errors, rx_bits[errors], s=90, color="red", zorder=5,
                   label="bit errors")
    ax.set_xlim(-0.5, len(rx_bits) - 0.5)
    ax.set_ylim(-0.3, 1.3)
    ax.set_yticks([0, 1])
    ax.set_xlabel("bit index")
    ax.set_ylabel("bit")
    title = "4) Recovered bit stream - %d errors" % len(errors)
    if errors.size:
        ax.legend(loc="upper right")
    ax.set_title(title, loc="left", fontsize=11)
    ax.grid(alpha=0.25)

    fig.suptitle("Part 1 - FSK chain (behavioural model, not a hardware model)",
                 fontsize=14, fontweight="bold")
    # Retry: OneDrive / the image viewer can briefly lock the PNG on Windows.
    for _ in range(10):
        try:
            fig.savefig(path, dpi=160, bbox_inches="tight")
            break
        except OSError:
            time.sleep(0.4)
    plt.close(fig)


def main():
    bits = make_bits()
    tx = fsk_modulate(bits)

    # Add a small amount of white noise.  Change NOISE_SIGMA above to make the
    # demo easier/harder; 0.45 still gives zero errors with this detector.
    rng = np.random.default_rng(SEED + 1)
    rx = tx + rng.normal(0.0, NOISE_SIGMA, size=tx.shape)

    recovered, metric = fsk_demodulate(rx, N_BITS)
    errors = np.flatnonzero(recovered != bits)
    bytes_tx = bits_to_bytes(bits)
    bytes_rx = bits_to_bytes(recovered)

    hex_payload = bytes_rx.hex().upper()
    with open("recovered.hex", "w", encoding="ascii") as f:
        f.write(hex_payload + "\n")

    plot_result(bits, tx, rx, metric, recovered, errors,
                os.path.join(OUT_DIR, "fsk_demo.png"))

    print("=" * 66)
    print(" PART 1 - FSK MODEM")
    print("=" * 66)
    print(f" carrier frequencies : {F0} Hz = '0', {F1} Hz = '1'")
    print(f" sample rate         : {FS} Hz   ({SPB} samples/bit, {BIT_RATE} bit/s)")
    print(f" payload             : {N_BYTES} bytes / {N_BITS} bits")
    print(f" noise sigma         : {NOISE_SIGMA}")
    print(f" bit errors          : {len(errors)}")
    print(f" BER                 : {len(errors) / N_BITS:.3e}")
    print(f" bytes transmitted   : {bytes_tx.hex(' ').upper()}")
    print(f" bytes recovered     : {bytes_rx.hex(' ').upper()}")
    print(f" recovered.hex       : {hex_payload}")
    print(f" plot                : {os.path.join(OUT_DIR, 'fsk_demo.png')}")
    print()


if __name__ == "__main__":
    main()
