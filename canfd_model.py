#!/usr/bin/env python3
"""
Part 2 - CAN-FD behavioural model (Python reference + Verilog frame generator)
==============================================================================

*** THIS IS A BEHAVIOURAL PROTOCOL MODEL, NOT A CYCLE-ACCURATE MODEL ***
It models the *logic* of a CAN-FD frame, not the RM46 / S32 CAN peripherals,
not the analogue transceiver, and not oscillator tolerances.  It is intended
for a demo/report, not for compliance testing.

What is modelled
----------------
* 11-bit identifier, FDF=1, BRS=1, ESI, DLC (including the CAN-FD DLC
  encoding: DLC=10 means 16 bytes, not 10 bytes)
* nominal phase 500 kbit/s (2.0 us/bit) and data phase 2 Mbit/s (0.5 us/bit)
* bit stuffing after 5 equal bits, from SOF through the CRC sequence
* CRC-17 with polynomial 0x1685B (MSB-first, 17 appended zero bits)
* CRC delimiter, ACK slot, ACK delimiter, EOF (7 bits), IFS (3 bits)
* Node A transmitter, Node B receiver + ACK + 2oo2 compare, Node C
  listen-only logger (never drives, never ACKs, never flags errors)
* heartbeat frames from A and B (ID 0x100)
* optional in-flight bit flip -> CRC error, no ACK, error flagged

Simplifications (documented for the report)
-------------------------------------------
* One in-flight bit flip is injected at the bus, not physically in a driver.
* A bit may not be stuffed immediately after the last CRC bit in some
  simplified models; we DO insert and remove that stuff bit consistently.
* Nodes share the testbench bit timing in the Verilog version; the Python
  version simply uses the known bit boundaries (no clock recovery).
* The CAN-FD "stuff count" field and the fixed stuff bits in the CRC field
  are not modelled beyond the normal 5-equal-bits rule.  The task explicitly
  allows this simplification.
"""

import csv
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch, Rectangle

# ----------------------------------------------------------------------------
# Bit timing and CAN-FD constants
# ----------------------------------------------------------------------------
NOMINAL_NS = 2_000            # 500 kbit/s
DATA_NS = 500                 # 2 Mbit/s

# CAN-FD DLC -> number of data bytes
DLC_TO_LEN = {
    0: 0, 1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 7, 8: 8,
    9: 12, 10: 16, 11: 20, 12: 24, 13: 32, 14: 48, 15: 64,
}
LEN_TO_DLC = {v: k for k, v in DLC_TO_LEN.items()}

# field codes stored in the Verilog frame memory (bits [19:16])
FIELD_CODE = {
    "SOF": 0, "ID": 1, "CTRL": 2, "DATA": 3, "CRC": 4,
    "CRC_DELIM": 5, "ACK_SLOT": 6, "ACK_DELIM": 7,
    "EOF": 8, "IFS": 9, "STUFF": 10,
}
# individual control sub-fields all map to the CTRL code
for _f in ("RRS", "IDE", "FDF", "res", "BRS", "ESI", "DLC"):
    FIELD_CODE[_f] = 2
CTRL_FIELDS = {"RRS", "IDE", "FDF", "res", "BRS", "ESI", "DLC"}

OUT_DIR = "out"
os.makedirs(OUT_DIR, exist_ok=True)


# ----------------------------------------------------------------------------
# Bit / frame data structures
# ----------------------------------------------------------------------------
@dataclass
class Bit:
    value: int
    field: str
    phase: str                    # "nominal" or "data"
    stuff: bool = False
    duration_ns: int = 0
    t0_ns: int = 0
    wire_idx: int = 0

    @property
    def t1_ns(self) -> int:
        return self.t0_ns + self.duration_ns


@dataclass
class Frame:
    name: str
    frame_id: int
    payload: bytes
    dlc: int
    bits: List[Bit]
    crc_calc: int
    brs: bool = True
    wire: List[int] = field(default_factory=list)
    t0_ns: int = 0
    t1_ns: int = 0
    crc_ok: bool = True
    ack_seen: bool = False
    fault_bit: Optional[int] = None
    decoded: dict = field(default_factory=dict)

    @property
    def duration_ns(self) -> int:
        return self.t1_ns - self.t0_ns


# ----------------------------------------------------------------------------
# CRC-17 (poly 0x1685B), MSB-first
# ----------------------------------------------------------------------------
def crc17_update(crc: int, bit: int) -> int:
    """One CRC step: XOR the bit into bit 16, shift, conditionally XOR poly."""
    crc ^= (bit & 1) << 16
    if crc & 0x10000:
        crc = ((crc << 1) ^ 0x1685B) & 0x1FFFF
    else:
        crc = (crc << 1) & 0x1FFFF
    return crc


def crc17(bits: List[int]) -> int:
    """
    Message CRC: process all message bits, then append 17 zero bits.
    The final 17-bit register is the CRC sequence sent on the wire.
    """
    crc = 0
    for b in bits:
        crc = crc17_update(crc, b)
    for _ in range(17):
        crc = crc17_update(crc, 0)
    return crc


# ----------------------------------------------------------------------------
# Frame construction (the encoder)
# ----------------------------------------------------------------------------
def build_frame(name: str, frame_id: int, payload: bytes, brs: bool = True) -> Frame:
    """
    Build the complete wire bit list for one standard 11-bit CAN-FD frame.
    """
    dlc = LEN_TO_DLC[len(payload)]
    core: List[Bit] = []

    def add(value: int, fld: str, phase: str):
        core.append(Bit(value, fld, phase))

    # --- SOF + arbitration + control --------------------------------------
    add(0, "SOF", "nominal")
    for i in range(10, -1, -1):
        add((frame_id >> i) & 1, "ID", "nominal")
    add(0, "RRS", "nominal")          # RRS (replaces RTR in CAN-FD)
    add(0, "IDE", "nominal")          # 11-bit identifier
    add(1, "FDF", "nominal")          # CAN-FD frame
    add(0, "res", "nominal")
    add(1 if brs else 0, "BRS", "nominal")
    add(0, "ESI", "nominal")          # error state indicator (recessive = ok)
    for i in range(3, -1, -1):
        add((dlc >> i) & 1, "DLC", "nominal")

    # --- data field (switches to the data rate after BRS) ------------------
    data_phase = "data" if brs else "nominal"
    for byte in payload:
        for i in range(7, -1, -1):
            add((byte >> i) & 1, "DATA", data_phase)

    # --- CRC-17 over SOF..data (no stuff bits) -----------------------------
    crc_val = crc17([b.value for b in core])
    for i in range(16, -1, -1):
        add((crc_val >> i) & 1, "CRC", data_phase)

    # --- insert stuff bits over SOF..CRC -----------------------------------
    stuffed: List[Bit] = [core[0]]
    run = 1
    prev = core[0].value
    for b in core[1:]:
        stuffed.append(b)
        if b.value == prev:
            run += 1
        else:
            run = 1
        prev = b.value
        if run == 5:
            # After 5 equal bits insert one opposite bit.  It inherits the
            # phase (nominal/data) of the bit that triggered it.
            stuff = Bit(1 - b.value, "STUFF", b.phase, stuff=True)
            stuffed.append(stuff)
            prev = stuff.value
            run = 1

    # --- fixed (un-stuffed) trailer ---------------------------------------
    def append_fixed(value: int, fld: str):
        stuffed.append(Bit(value, fld, "nominal"))

    append_fixed(1, "CRC_DELIM")
    append_fixed(1, "ACK_SLOT")       # A transmits recessive; B may pull low
    append_fixed(1, "ACK_DELIM")
    for _ in range(7):
        append_fixed(1, "EOF")
    for _ in range(3):
        append_fixed(1, "IFS")

    for i, b in enumerate(stuffed):
        b.duration_ns = DATA_NS if b.phase == "data" else NOMINAL_NS
        b.wire_idx = i

    return Frame(name=name, frame_id=frame_id, payload=payload, dlc=dlc,
                 bits=stuffed, crc_calc=crc_val, brs=brs,
                 wire=[b.value for b in stuffed])


# ----------------------------------------------------------------------------
# Receiver: de-stuffing + field parsing + CRC check
# ----------------------------------------------------------------------------
class Destuffer:
    """
    Recover the original bit stream from the wire, removing stuff bits using
    the same "after 5 equal bits" rule.  Raises ValueError on a stuff error.
    """

    def __init__(self, values: List[int]):
        self.v = values
        self.i = 0
        self.prev = None
        self.run = 0
        self.started = False

    def next_bit(self) -> int:
        if not self.started:
            self.started = True
            v = self.v[self.i]
            self.i += 1
            self.prev = v
            self.run = 1
            return v

        # If we have just seen 5 equal bits, the next wire bit is a stuff bit.
        if self.run == 5:
            stuff = self.v[self.i]
            self.i += 1
            if stuff == self.prev:
                raise ValueError("stuff-bit violation (6 equal bits)")
            self.prev = stuff
            self.run = 1

        v = self.v[self.i]
        self.i += 1
        if v == self.prev:
            self.run += 1
        else:
            self.run = 1
        self.prev = v
        return v

    def finish_stuff(self):
        """Consume a possible stuff bit after the final CRC bit."""
        if self.run == 5:
            stuff = self.v[self.i]
            self.i += 1
            if stuff == self.prev:
                raise ValueError("stuff-bit violation after CRC")
            self.prev = stuff
            self.run = 1
        return self.i


def decode_frame(wire_values: List[int]) -> dict:
    """
    Decode a complete frame from the wire values only.  This is the receiver
    logic used by B and C.  Returns a dictionary; on a structural error it
    returns ok=False instead of throwing.
    """
    try:
        r = Destuffer(wire_values)
        head = [r.next_bit() for _ in range(22)]
        sof = head[0]
        frame_id = 0
        for b in head[1:12]:
            frame_id = (frame_id << 1) | b
        rrs, ide, fdf, res, brs, esi = head[12:18]
        dlc = 0
        for b in head[18:22]:
            dlc = (dlc << 1) | b
        n = DLC_TO_LEN.get(dlc, 0)
        data_bits = [r.next_bit() for _ in range(8 * n)]

        crc_rx = 0
        for _ in range(17):
            crc_rx = (crc_rx << 1) | r.next_bit()

        calc = crc17(head + data_bits)
        r.finish_stuff()
        idx = r.i

        crc_delim = wire_values[idx]
        ack_slot = wire_values[idx + 1]
        ack_delim = wire_values[idx + 2]
        eof = wire_values[idx + 3:idx + 10]
        ifs = wire_values[idx + 10:idx + 13]

        payload = bytearray()
        for i in range(0, len(data_bits), 8):
            byte = 0
            for b in data_bits[i:i + 8]:
                byte = (byte << 1) | b
            payload.append(byte)

        errors = []
        if sof != 0:
            errors.append("SOF")
        if fdf != 1:
            errors.append("FDF")
        if crc_delim != 1:
            errors.append("CRC delimiter")
        if ack_delim != 1:
            errors.append("ACK delimiter")
        if len(eof) != 7 or any(b != 1 for b in eof):
            errors.append("EOF")
        if len(ifs) != 3 or any(b != 1 for b in ifs):
            errors.append("IFS")

        return {
            "ok": True,
            "id": frame_id,
            "dlc": dlc,
            "brs": brs,
            "fdf": fdf,
            "payload": bytes(payload),
            "crc_rx": crc_rx,
            "crc_calc": calc,
            "crc_ok": crc_rx == calc and not any(
                e in ("CRC delimiter", "EOF") for e in errors),
            "ack_seen": ack_slot == 0,
            "errors": errors,
        }
    except (IndexError, ValueError) as exc:
        return {
            "ok": False,
            "id": 0, "dlc": 0, "brs": 0, "fdf": 0,
            "payload": b"", "crc_ok": False, "ack_seen": False,
            "errors": [str(exc)],
        }


# ----------------------------------------------------------------------------
# Simulation: schedule, ACK, 2oo2, logger
# ----------------------------------------------------------------------------
def find_fault_bit(frame: Frame) -> int:
    """
    Choose an in-flight bit flip that keeps the receiver byte-aligned but
    breaks the CRC.  Flipping some bits would also break the stuffing rule;
    those are rejected here so the demo shows a clean CRC error.
    """
    candidates = []
    for i, b in enumerate(frame.bits):
        if b.field in ("DATA", "CRC") and not b.stuff:
            candidates.append(i)

    # Prefer the middle of the data field so the fault is easy to see.
    candidates.sort(key=lambda i: abs(i - len(frame.bits) // 2))
    for i in candidates:
        w = list(frame.wire)
        w[i] ^= 1
        dec = decode_frame(w)
        if dec["ok"] and not dec["crc_ok"] and not dec["errors"]:
            return i
    raise RuntimeError("could not find a safe fault bit")


def simulate() -> List[Frame]:
    # Payload comes from Part 1.  Pad 8 bytes to the 16-byte CAN-FD payload.
    with open("recovered.hex", "r", encoding="ascii") as fh:
        raw = bytes.fromhex(fh.read().strip())
    if len(raw) != 8:
        raise ValueError("recovered.hex must contain exactly 8 bytes")
    payload = raw + bytes([0xA5]) * 8          # 16 bytes -> DLC 10

    frames = [
        build_frame("DATA 0x123", 0x123, payload),
        build_frame("HB-A 0x100", 0x100, bytes([0xA1])),
        build_frame("HB-B 0x100", 0x100, bytes([0xB2])),
        build_frame("FAULT 0x123", 0x123, payload),
        build_frame("RECOVERY 0x123", 0x123, payload),
    ]

    # ---- fault injection --------------------------------------------------
    frames[3].fault_bit = find_fault_bit(frames[3])
    w = list(frames[3].wire)
    w[frames[3].fault_bit] ^= 1
    frames[3].wire = w

    # ---- receiver/ACK/2oo2 for every frame --------------------------------
    for f in frames:
        dec = decode_frame(f.wire)
        f.decoded = dec
        f.crc_ok = dec["crc_ok"]

        # B drives the ACK slot dominant only when the CRC is good.
        ack_idx = next(i for i, b in enumerate(f.bits) if b.field == "ACK_SLOT")
        f.wire[ack_idx] = 0 if f.crc_ok else 1
        dec2 = decode_frame(f.wire)
        f.ack_seen = dec2["ack_seen"]
        f.decoded = dec2

    # ---- timing schedule --------------------------------------------------
    # Heartbeats in a real system would be every N ms.  We compress the gap
    # to 120 us so the whole demo fits on one readable timing diagram.
    t = 0
    gap = 120_000
    for f in frames:
        f.t0_ns = t
        tt = t
        for b in f.bits:
            b.t0_ns = tt
            tt += b.duration_ns
        f.t1_ns = tt
        t = tt + gap

    return frames


def write_csv(frames: List[Frame], path: str):
    with open(path, "w", newline="", encoding="ascii") as fh:
        w = csv.writer(fh)
        w.writerow(["timestamp_us", "id", "brs", "dlc",
                    "payload_hex", "crc_ok", "ack_seen"])
        for f in frames:
            d = f.decoded
            w.writerow([
                f"{f.t0_ns / 1000.0:.3f}",
                f"{d['id']:03X}",
                int(d["brs"]),
                d["dlc"],
                d["payload"].hex().upper(),
                int(bool(d["crc_ok"])),
                int(bool(d["ack_seen"])),
            ])


def write_verilog_frames(frames: List[Frame], fault_bit: int):
    """Write the frame bit memories and constants consumed by canfd_tb.v."""
    words = []
    bases = []
    lens = []
    for f in frames:
        bases.append(len(words))
        lens.append(len(f.bits))
        for b in f.bits:                       # A's transmitted bits, not the bus
            phase_code = 1 if b.phase == "data" else 0
            fld = FIELD_CODE[b.field]
            word = ((fld & 0xF) << 16) | ((b.duration_ns & 0xFFF) << 4) \
                   | ((phase_code & 0x3) << 2) | ((1 if b.stuff else 0) << 1) \
                   | (b.value & 1)
            words.append(word)

    with open(os.path.join(OUT_DIR, "frames.mem"), "w", encoding="ascii") as fh:
        for w in words:
            fh.write(f"{w:08X}\n")
        # Pad to 1024 words so iverilog's $readmemh does not warn.  The extra
        # words are never addressed.
        for _ in range(len(words), 1024):
            fh.write("00000000\n")

    expected = frames[0].payload
    expected_int = int.from_bytes(expected, "big")
    hb_a = frames[1].payload[0]
    hb_b = frames[2].payload[0]

    with open(os.path.join(OUT_DIR, "frames_def.vh"), "w", encoding="ascii") as fh:
        fh.write("// AUTO-GENERATED by canfd_model.py - do not edit\n")
        fh.write("// Frame memory word: [19:16] field, [15:4] duration_ns,\n")
        fh.write("//                    [3:2] phase (0=nominal,1=data), [1] stuff, [0] bit\n")
        for i, (base, ln) in enumerate(zip(bases, lens)):
            fh.write(f"localparam integer F{i}_BASE = {base};\n")
            fh.write(f"localparam integer F{i}_LEN  = {ln};\n")
        fh.write(f"localparam integer FAULT_FRAME = 3;\n")
        fh.write(f"localparam integer FAULT_BIT = {fault_bit};\n")
        fh.write(f"localparam [10:0] DATA_ID = 11'h123;\n")
        fh.write(f"localparam [10:0] HB_ID   = 11'h100;\n")
        fh.write(f"localparam [127:0] EXPECTED_PAYLOAD = 128'h{expected_int:032X};\n")
        fh.write(f"localparam [7:0] HB_A_BYTE = 8'h{hb_a:02X};\n")
        fh.write(f"localparam [7:0] HB_B_BYTE = 8'h{hb_b:02X};\n")


# ----------------------------------------------------------------------------
# Plotting
# ----------------------------------------------------------------------------
PHASE_COLORS = {"nominal": "#dbe5f1", "data": "#fce5cd"}


def save_figure(fig, path: str, dpi: int = 160):
    """
    Save a figure with a few retries.

    The project may live in a OneDrive folder; OneDrive / an image viewer can
    briefly hold a PNG open.  A short retry turns that transient Windows
    "invalid argument" error into a non-issue for the demo.
    """
    last_error = None
    for _ in range(10):
        try:
            fig.savefig(path, dpi=dpi, bbox_inches="tight")
            plt.close(fig)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.4)
    plt.close(fig)
    raise last_error


def _rel_us(frame: Frame, t_ns: int) -> float:
    return (t_ns - frame.t0_ns) / 1000.0


def _field_spans(frame: Frame):
    """Group consecutive non-stuff bits into field spans for annotation."""
    spans = []
    cur = None
    for b in frame.bits:
        if b.field == "STUFF":
            continue
        key = "CTRL" if b.field in CTRL_FIELDS else b.field
        if cur and cur["key"] == key:
            cur["t1"] = b.t1_ns
        else:
            if cur:
                spans.append(cur)
            cur = {"key": key, "t0": b.t0_ns, "t1": b.t1_ns}
    if cur:
        spans.append(cur)
    return spans


FIELD_LABEL = {
    "SOF": "SOF", "ID": "ID", "CTRL": "CTRL\nFDF BRS DLC",
    "DATA": "DATA", "CRC": "CRC-17", "CRC_DELIM": "CRC d",
    "ACK_SLOT": "ACK", "ACK_DELIM": "",
    "EOF": "EOF", "IFS": "IFS",
}


def draw_detail(fig, gs_rows, frame: Frame, fault_mode: bool):
    """Draw bus / phase / stuff / drive rows for one frame."""
    ax_bus = fig.add_subplot(gs_rows[0])
    ax_phase = fig.add_subplot(gs_rows[1], sharex=ax_bus)
    ax_stuff = fig.add_subplot(gs_rows[2], sharex=ax_bus)
    ax_drive = fig.add_subplot(gs_rows[3], sharex=ax_bus)

    xmax = frame.duration_ns / 1000.0

    # background: nominal vs data phase
    runs = []
    for b in frame.bits:
        if runs and runs[-1][2] == b.phase:
            runs[-1][1] = b.t1_ns
        else:
            runs.append([b.t0_ns, b.t1_ns, b.phase])
    for t0, t1, ph in runs:
        ax_bus.axvspan(_rel_us(frame, t0), _rel_us(frame, t1),
                       color=PHASE_COLORS[ph], alpha=0.55, lw=0, zorder=0)

    # bus waveform
    xs, ys = [], []
    for b, v in zip(frame.bits, frame.wire):
        xs += [_rel_us(frame, b.t0_ns), _rel_us(frame, b.t1_ns)]
        ys += [v, v]
    ax_bus.plot(xs, ys, color="black", lw=1.8, zorder=3)
    ax_bus.set_xlim(0, xmax)
    ax_bus.set_ylim(-0.7, 2.8)
    ax_bus.set_yticks([0, 1])
    ax_bus.set_yticklabels(["0\ndominant", "1\nrecessive"])
    ax_bus.grid(alpha=0.2, axis="x")

    # field boundaries and labels
    for sp in _field_spans(frame):
        x0 = _rel_us(frame, sp["t0"])
        x1 = _rel_us(frame, sp["t1"])
        ax_bus.axvline(x0, color="#777777", lw=0.7, ls=":", zorder=2)
        label = FIELD_LABEL.get(sp["key"], sp["key"])
        if sp["key"] == "ID":
            label = f"ID 0x{frame.frame_id:03X}"
        if sp["key"] == "DATA":
            label = f"DATA ({len(frame.payload)} bytes)"
        if not label:
            continue
        xc = (x0 + x1) / 2
        if sp["key"] == "ACK_SLOT":
            # The ACK slot is only 2 us wide - use an arrow so the label does
            # not collide with the CRC/ACK delimiter labels.
            ax_bus.annotate("ACK", xy=(xc, 1.08), xytext=(xc, 2.55),
                            ha="center", va="center", fontsize=7.5,
                            color="#1a6b1a", fontweight="bold",
                            arrowprops=dict(arrowstyle="->", color="#1a6b1a",
                                            lw=0.9))
        elif sp["key"] in ("SOF", "CRC_DELIM", "ACK_DELIM", "IFS"):
            ax_bus.text(xc, 1.55, label, ha="center", va="bottom",
                        fontsize=7.5, rotation=90, zorder=5)
        else:
            ax_bus.text(xc, 2.35, label, ha="center", va="center",
                        fontsize=7.5, zorder=5)

    # data byte grid
    data_bits = [b for b in frame.bits if b.field == "DATA"]
    for i in range(0, len(data_bits), 8):
        x = _rel_us(frame, data_bits[i].t0_ns)
        ax_bus.axvline(x, color="#999999", lw=0.4, alpha=0.6, zorder=1)
        if i % 32 == 0:
            ax_bus.text(x + 0.4, -0.45, f"B{i // 8}", fontsize=6,
                        color="#666666", ha="left")

    # ACK slot highlight
    ack_b = next(b for b in frame.bits if b.field == "ACK_SLOT")
    ax_bus.axvspan(_rel_us(frame, ack_b.t0_ns), _rel_us(frame, ack_b.t1_ns),
                   color="#2ca02c", alpha=0.30, zorder=2)

    # fault marker
    if frame.fault_bit is not None:
        fb = frame.bits[frame.fault_bit]
        xf = _rel_us(frame, (fb.t0_ns + fb.t1_ns) // 2)
        yf = frame.wire[frame.fault_bit]
        ax_bus.scatter([xf], [yf], s=110, facecolors="none",
                       edgecolors="red", linewidths=2, zorder=6)
        ax_bus.annotate("bit flipped in flight\n(CRC will fail)",
                        xy=(xf, yf), xytext=(xf - 18, 2.35),
                        fontsize=7, color="red", ha="center",
                        arrowprops=dict(arrowstyle="->", color="red", lw=1.0))

    ax_bus.set_title(
        f"{frame.name}: bus, 11-bit ID, BRS={'1' if frame.brs else '0'}, "
        f"{len(frame.payload)}-byte payload - "
        f"{'FAULT INJECTED' if fault_mode else 'nominal frame'}",
        loc="left", fontsize=11)

    # --- phase row ---------------------------------------------------------
    pxs, pys = [], []
    for b in frame.bits:
        pxs += [_rel_us(frame, b.t0_ns), _rel_us(frame, b.t1_ns)]
        pys += [1 if b.phase == "data" else 0] * 2
    ax_phase.plot(pxs, pys, color="#8c564b", lw=1.4)
    ax_phase.set_ylim(-0.35, 1.35)
    ax_phase.set_yticks([0, 1])
    ax_phase.set_yticklabels(["nominal\n500 kbit/s", "data\n2 Mbit/s"])
    ax_phase.grid(alpha=0.2, axis="x")
    for t0, t1, ph in runs:
        if (t1 - t0) > 20_000:
            ax_phase.text(_rel_us(frame, (t0 + t1) // 2), 0.5,
                          "500 kbit/s" if ph == "nominal" else "2 Mbit/s",
                          ha="center", va="center", fontsize=7,
                          color="#555555")
    ax_phase.set_title("Bit-rate phase (switches at BRS and back at the CRC delimiter)",
                       loc="left", fontsize=9)

    # --- stuff row ---------------------------------------------------------
    stuff_bits = [b for b in frame.bits if b.stuff]
    for b in stuff_bits:
        x = _rel_us(frame, (b.t0_ns + b.t1_ns) // 2)
        ax_stuff.vlines(x, 0.0, 1.0, color="red", lw=1.2)
        ax_stuff.scatter([x], [1.0], marker="v", color="red", s=35, zorder=4)
        ax_bus.scatter([x], [frame.wire[b.wire_idx] + 0.16], marker="v",
                       color="red", s=28, zorder=5)
    ax_stuff.set_ylim(-0.2, 1.3)
    ax_stuff.set_yticks([])
    ax_stuff.grid(alpha=0.2, axis="x")
    ax_stuff.set_ylabel("stuff", rotation=0, labelpad=16, fontsize=8)
    ax_stuff.set_title(
        f"Stuff bits: {len(stuff_bits)} (one opposite bit after each run of five)",
        loc="left", fontsize=9)

    # --- drive row ---------------------------------------------------------
    def drive_trace(offset, active_fn, color, lw=1.4):
        dxs, dys = [], []
        for i, b in enumerate(frame.bits):
            active = active_fn(i, b)
            dxs += [_rel_us(frame, b.t0_ns), _rel_us(frame, b.t1_ns)]
            dys += [offset + (0.6 if active else 0.0)] * 2
        ax_drive.plot(dxs, dys, color=color, lw=lw)

    # A drives dominant whenever its transmitted bit is 0.
    drive_trace(2.2, lambda i, b: b.value == 0, "#1f4e79")
    # B drives dominant only in the ACK slot, and only if the CRC is good.
    drive_trace(1.2, lambda i, b: (b.field == "ACK_SLOT" and frame.ack_seen),
                "#2ca02c", lw=2.0)

    ax_drive.axhspan(0.02, 0.58, facecolor="#dddddd", edgecolor="#777777",
                     hatch="///", alpha=0.55, lw=0.6)
    ax_drive.text(xmax / 2, 0.30,
                  "Node C (logging MCU): high-Z / listen-only - never drives, "
                  "never ACKs, never error-flags",
                  ha="center", va="center", fontsize=8, color="#333333")
    ax_drive.set_ylim(-0.15, 2.95)
    ax_drive.set_yticks([0.3, 1.5, 2.5])
    ax_drive.set_yticklabels(["C pin\nhigh-Z", "B drive", "A drive"])
    ax_drive.grid(alpha=0.2, axis="x")
    ax_drive.set_xlabel("time within frame (us)")

    # ACK annotation on the drive row
    ack_x = _rel_us(frame, (ack_b.t0_ns + ack_b.t1_ns) // 2)
    if frame.ack_seen:
        ax_drive.annotate("B pulls ACK dominant", xy=(ack_x, 1.65),
                          xytext=(ack_x - 14, 1.95), fontsize=7, color="#1a6b1a",
                          ha="center",
                          arrowprops=dict(arrowstyle="->", color="#1a6b1a", lw=0.8))
    else:
        ax_drive.annotate("no ACK (CRC error)", xy=(ack_x, 1.2),
                          xytext=(ack_x - 14, 1.85), fontsize=7, color="red",
                          ha="center",
                          arrowprops=dict(arrowstyle="->", color="red", lw=0.8))

    return ax_bus, ax_phase, ax_stuff, ax_drive


def draw_timeline(ax, frames: List[Frame]):
    """Compact overview of the whole scenario."""
    colors = {
        "DATA": ("#2ca02c", "normal data"),
        "HB": ("#1f77b4", "heartbeat"),
        "FAULT": ("#d62728", "fault injected"),
        "RECOVERY": ("#2ca02c", "recovery"),
    }
    ax.set_xlim(0, frames[-1].t1_ns / 1000.0 + 80)
    ax.set_ylim(-0.9, 2.0)
    ax.axhline(1.0, color="#888888", lw=0.8, ls="--")

    for f in frames:
        if f.name.startswith("HB"):
            c, _ = colors["HB"]
        elif f.name.startswith("FAULT"):
            c, _ = colors["FAULT"]
        elif f.name.startswith("RECOVERY"):
            c, _ = colors["RECOVERY"]
        else:
            c, _ = colors["DATA"]
        x0 = f.t0_ns / 1000.0
        w = f.duration_ns / 1000.0
        ax.add_patch(Rectangle((x0, 0.25), w, 0.7, facecolor=c,
                               edgecolor="black", alpha=0.75, lw=0.7))
        label = f.name.replace(" ", "\n")
        ax.text(x0 + w / 2, 1.22, label, ha="center", va="bottom",
                fontsize=7.2, color=c, fontweight="bold")
        if f.fault_bit is not None:
            fb = f.bits[f.fault_bit]
            xf = fb.t0_ns / 1000.0
            ax.scatter([xf], [0.6], marker="x", color="white", s=40, zorder=5)
            ax.annotate("fault", xy=(xf, 0.6), xytext=(xf, -0.55),
                        ha="center", fontsize=7, color="red",
                        arrowprops=dict(arrowstyle="->", color="red", lw=0.8))
        # mark the ACK slot with a small tick
        ack_b = next(b for b in f.bits if b.field == "ACK_SLOT")
        xa = ack_b.t0_ns / 1000.0
        ax.plot([xa], [0.15], marker="|", color="green", ms=8, mew=2)

    ax.set_yticks([])
    ax.set_xlabel("absolute time (us)")
    ax.set_title("Scenario timeline - heartbeat spacing is compressed for the demo "
                 "(green tick = ACK slot)", loc="left", fontsize=10)
    ax.grid(alpha=0.2, axis="x")
    legend = [
        Patch(facecolor=colors["DATA"][0], alpha=0.75, label="data frame"),
        Patch(facecolor=colors["HB"][0], alpha=0.75, label="heartbeat"),
        Patch(facecolor=colors["FAULT"][0], alpha=0.75, label="fault injected"),
    ]
    ax.legend(handles=legend, loc="lower right", fontsize=7, ncol=3,
              framealpha=0.9)


def plot_timing(frames: List[Frame], path: str):
    fig = plt.figure(figsize=(16, 11))
    gs = fig.add_gridspec(5, 1, height_ratios=[3.0, 0.9, 0.9, 1.7, 1.4],
                          hspace=0.5)
    draw_detail(fig, [gs[0], gs[1], gs[2], gs[3]], frames[0], fault_mode=False)
    ax_time = fig.add_subplot(gs[4])
    draw_timeline(ax_time, frames)

    fig.suptitle("Part 2 - CAN-FD frame timing (behavioural model, 500 kbit/s "
                 "nominal -> 2 Mbit/s data)", fontsize=14, fontweight="bold")
    save_figure(fig, path, dpi=170)


def plot_fault(frames: List[Frame], path: str):
    fig = plt.figure(figsize=(16, 9))
    gs = fig.add_gridspec(4, 1, height_ratios=[3.0, 0.9, 0.9, 1.7],
                          hspace=0.45)
    draw_detail(fig, [gs[0], gs[1], gs[2], gs[3]], frames[3], fault_mode=True)
    fig.suptitle("Fault-injection case - one bit flipped in flight: CRC error, "
                 "no ACK, no 2oo2 comparison", fontsize=14, fontweight="bold")
    save_figure(fig, path, dpi=170)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    frames = simulate()
    expected = frames[0].payload

    log_path = os.path.join(OUT_DIR, "canfd_log.csv")
    write_csv(frames, log_path)
    write_verilog_frames(frames, frames[3].fault_bit)

    timing_path = os.path.join(OUT_DIR, "timing_diagram.png")
    fault_path = os.path.join(OUT_DIR, "fault_timing.png")
    plot_timing(frames, timing_path)
    plot_fault(frames, fault_path)

    print("=" * 74)
    print(" PART 2 - CAN-FD BEHAVIOURAL MODEL (not cycle-accurate)")
    print("=" * 74)
    print(f" nominal rate : 500 kbit/s ({NOMINAL_NS} ns/bit)")
    print(f" data rate    : 2 Mbit/s   ({DATA_NS} ns/bit)")
    print(f" payload      : {expected.hex(' ').upper()}   (from recovered.hex + pad)")
    print(f" frames       : {len(frames)} (data, heartbeats, fault, recovery)")
    print("-" * 74)

    for i, f in enumerate(frames):
        d = f.decoded
        crc = "OK   " if d["crc_ok"] else "ERROR"
        ack = "yes" if d["ack_seen"] else "NO "
        if f.name.startswith("HB"):
            role = f"heartbeat from {'A' if f.payload[0] == 0xA1 else 'B'}"
            extra = "cross-monitor OK"
        elif f.name.startswith("FAULT"):
            role = "data frame"
            extra = "2oo2: rejected (CRC error)"
        else:
            match = d["payload"] == expected
            role = "data frame"
            extra = "2oo2: MATCH" if match else "2oo2: MISMATCH"
        print(f" {i}  {f.name:<14} ID=0x{d['id']:03X}  DLC={d['dlc']:>2} "
              f"({len(d['payload']):>2}B)  CRC={crc}  ACK={ack}  {role:<18} {extra}")
        if d["errors"]:
            print(f"      receiver errors: {', '.join(d['errors'])}")

    fault = frames[3]
    print("-" * 74)
    print(f" fault injection : bit {fault.fault_bit} flipped in flight -> "
          f"B and C both see CRC ERROR")
    print(f"                  B does not ACK; A sees no ACK (ACK error flag)")
    print(f"                  C logged the corrupted frame with crc_ok=0, ack_seen=0")
    print(f" 2oo2 compare   : A data vs B's own copy -> "
          f"{'MATCH' if frames[0].decoded['payload'] == expected else 'MISMATCH'} "
          f"(good frames), fault frame rejected before compare")
    print(f" heartbeat      : A<->B cross-monitor OK (CRC + ID 0x100 checked)")
    print("-" * 74)
    print(f" C log          : {log_path}")
    print(f" timing diagram : {timing_path}")
    print(f" fault diagram  : {fault_path}")
    print(f" Verilog inputs : {os.path.join(OUT_DIR, 'frames.mem')}, "
          f"{os.path.join(OUT_DIR, 'frames_def.vh')}")
    print()


if __name__ == "__main__":
    main()
