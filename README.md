# Three-Channel Safety Demo — FSK + CAN-FD + Listen-Only Logger

A small, runnable, **behavioural** simulation for the Phase-2 review.

| Channel | Role | Model node |
|---|---|---|
| **A** | TI Hercules RM46 (lockstep Cortex-R4F), safety processing | CAN-FD transmitter + monitor |
| **B** | NXP S32 Safety MCU, safety processing | CAN-FD receiver, ACK, 2oo2 compare + monitor |
| **C** | Independent NXP S32 logging MCU | listen-only CAN-FD logger (never drives / ACKs / flags) |

The input data comes from Part 1: an FSK modem produces 8 bytes, which are
padded to the 16-byte CAN-FD payload sent from A to B. C logs every frame with
a timestamp. A and B exchange `0x100` heartbeat frames and cross-monitor each
other. A fault-injection run flips one bit in flight and shows a CRC error,
no ACK, and recovery on the next frame.

> **Important:** this is a behavioural protocol model, **not** a cycle-accurate
> model of the RM46 or S32 peripherals, the CAN transceiver, or IEEE 1588.
> The goal is to demonstrate the architecture and the protocol logic, not to
> validate hardware timing. See [Simplifications](#simplifications).

---

## 1. Install (Windows)

### Python + packages

```bat
winget install --id Python.Python.3.12 -e
python --version
python -m pip install --upgrade pip
python -m pip install numpy matplotlib
```

If `winget` is unavailable, install Python 3.10+ from
<https://www.python.org/downloads/windows/> and **tick “Add python.exe to
PATH”** during setup.

### Icarus Verilog + GTKWave (optional, but recommended)

The Windows installer from **bleyer.org** bundles both Icarus Verilog and
GTKWave:

1. Download the 64-bit installer from <https://bleyer.org/icarus/>
   (for example `iverilog-v12-20220611-x64_setup.exe`).
2. During setup tick **“Add executable folder(s) to PATH”** and install
   GTKWave.
3. Verify in a **new** terminal:

```bat
iverilog -V
gtkwave --version
```

Alternative if you already use Chocolatey:

```bat
choco install iverilog -y
```

GTKWave is normally installed at `C:\iverilog\gtkwave\bin\gtkwave.exe` and is
already on PATH if the installer option was ticked.

> If `iverilog` is **not** installed, `run_all.bat` still runs the Python
> reference model and produces the PNG timing diagrams and CSV log. Only the
> VCD / Verilog CSV are skipped.

---

## 2. Run

From this folder (the path may contain spaces — that is fine):

```bat
run_all.bat
```

For automation / no pause:

```bat
run_all.bat --no-pause
```

Git Bash / Linux / macOS:

```bash
bash run_all.sh
```

### Run the pieces individually

```bat
REM Part 1 - FSK modem
python fsk_chain.py

REM Part 2 - Python CAN-FD reference + frame data for Verilog
python canfd_model.py

REM Part 2 - Verilog simulation (preferred timing path)
iverilog -g2012 -o out\sim.vvp canfd_nodes.v canfd_tb.v
vvp out\sim.vvp

REM Open the waveform
gtkwave out\canfd_verilog.vcd
```

> Run the Verilog commands **from this folder**: the testbench reads
> `out/frames.mem` and writes `out/canfd_verilog.vcd` using relative paths.

---

## 3. Outputs

| File | What it is |
|---|---|
| `recovered.hex` | 8 bytes recovered by the FSK demodulator |
| `out/fsk_demo.png` | input bits, FSK waveform, detector margin, recovered bits |
| `out/timing_diagram.png` | normal frame: bus, phase, stuff bits, A/B/C drives, scenario timeline |
| `out/fault_timing.png` | fault frame: flipped bit, CRC error, no ACK |
| `out/canfd_log.csv` | Node C log from the **Python** model |
| `out/canfd_verilog_log.csv` | Node C log from the **Verilog** model (if iverilog ran) |
| `out/canfd_verilog.vcd` | GTKWave-ready waveform (if iverilog ran) |
| `out/frames.mem`, `out/frames_def.vh` | generated frame bits/constants used by the Verilog testbench |

CSV columns:

```text
timestamp_us,id,brs,dlc,payload_hex,crc_ok,ack_seen
```

---

## 4. What you should see

Typical console result:

```text
PART 1 - FSK MODEM
 bit errors          : 0
 bytes recovered     : 90 BE C7 77 80 C6 21 2B

PART 2 - CAN-FD BEHAVIOURAL MODEL
 0  DATA 0x123     ID=0x123  DLC=10 (16B)  CRC=OK     ACK=yes  2oo2: MATCH
 1  HB-A 0x100     ID=0x100  DLC= 1 ( 1B)  CRC=OK     ACK=yes  heartbeat from A
 2  HB-B 0x100     ID=0x100  DLC= 1 ( 1B)  CRC=OK     ACK=yes  heartbeat from B
 3  FAULT 0x123    ID=0x123  DLC=10 (16B)  CRC=ERROR  ACK=NO   2oo2: rejected
 4  RECOVERY 0x123 ID=0x123  DLC=10 (16B)  CRC=OK     ACK=yes  2oo2: MATCH

VERILOG CAN-FD NODE SIMULATION
[144.2 us] A data    0x123: B crc=1 ack=1 match=1 | C crc=1 ack=1 | A ack_seen=1 ...
[762.3 us] FAULT     bit 91: B crc=0 ack=0 | C crc=0 ack=0 | A ack_seen=0 ack_err=1
 RESULT: PASS
```

The fault frame payload in the CSV differs from the expected payload by one
bit, and both B and C mark `crc_ok=0`, `ack_seen=0`.

---

## 5. Five lines to say during the demo

1. “The FSK modem converts an 8-byte random pattern into 1 kHz / 2 kHz tones;
   the receiver recovers all 64 bits with zero errors.”
2. “Those bytes are padded to a 16-byte CAN-FD payload and Node A sends it with
   an 11-bit ID, BRS=1, 500 kbit/s arbitration and 2 Mbit/s data, CRC-17 and
   bit stuffing.”
3. “Node B removes the stuff bits, checks the CRC, pulls the ACK slot dominant
   and compares the payload with its own copy — the 2oo2 result is MATCH.”
4. “Node C is completely passive: its pin stays high-Z, it never drives or ACKs,
   and it writes a timestamped CSV row for every frame it hears.”
5. “In the fault test we flip one bit in flight: B and C both detect the CRC
   error, B does not ACK, A flags the missing ACK, and the next frame recovers.”

---

## 6. Files

```text
fsk_chain.py        Part 1: FSK modulator/demodulator + plots
canfd_model.py      Part 2: frame encoder, CRC, stuffing, receiver, 2oo2,
                    logger, fault injection, PNG figures, CSV, Verilog data
canfd_nodes.v       Verilog transmitter + listener (CRC, de-stuffing, ACK)
canfd_tb.v          Verilog top: bus, scheduler, heartbeats, fault injection,
                    VCD dump, pass/fail summary
run_all.bat         one-command Windows runner
run_all.sh          one-command bash runner
recovered.hex       generated by fsk_chain.py
out/                generated outputs (safe to delete and regenerate)
```

---

## 7. Protocol details modelled

* 11-bit identifier, `FDF=1`, `BRS=1`, `ESI`, 4-bit DLC.
* CAN-FD DLC encoding is correct: **DLC=10 means 16 bytes** (DLC 9..15 map to
  12, 16, 20, 24, 32, 48, 64 bytes).
* Nominal phase 500 kbit/s (2.0 µs/bit); data phase 2 Mbit/s (0.5 µs/bit).
  The rate switches at BRS and returns at the CRC delimiter.
* Bit stuffing after five equal bits, from SOF through the CRC sequence. A
  possible final stuff bit after the last CRC bit is inserted and removed
  consistently.
* CRC-17, polynomial `0x1685B`, MSB-first, 17 appended zero bits.
* CRC delimiter, ACK slot, ACK delimiter, EOF (7 recessive bits), IFS (3).
* Node B drives ACK dominant only when the CRC is good. Node A checks the ACK
  slot and raises an ACK error if it stays recessive.
* 2oo2 compare: B compares the received 16-byte payload with its own copy and
  raises MATCH / MISMATCH.
* Heartbeats: ID `0x100` from A and B; each node checks the other’s heartbeat
  ID, CRC and source byte. A and B also ACK each other.
* Node C is not in the bus-drive equation at all; its pin is tied to `1'bz`
  and its listener has `DO_ACK=0`.

### Simplifications

These are deliberate and called out in the source comments:

* Behavioural, not cycle-accurate. No RM46/S32 peripheral registers, no
  transceiver analogue behaviour, no oscillator tolerance or bit
  resynchronisation. All nodes share the testbench bit-timing strobes.
* The heartbeat interval is compressed to 100 µs (Verilog) / 120 µs (Python)
  so the whole scenario fits on one readable plot. A real system would use
  milliseconds.
* One bit is flipped at the bus in the fault frame; this is a demonstration
  hook, not a physical fault injector.
* The CAN-FD stuff-count field and the fixed stuff bits in the CRC field are
  not modelled beyond the normal five-equal-bits rule (explicitly allowed by
  the assignment).
* The logger timestamp is the simulation time; an actual PTP/IEEE 1588 stack
  and eMMC/FRAM storage are outside the scope of this model.

---

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `python` is not recognised | Reinstall Python and tick “Add python.exe to PATH”, or use `py` instead of `python`. |
| `ModuleNotFoundError: numpy` | `python -m pip install numpy matplotlib` |
| `iverilog` is not recognised | Install from <https://bleyer.org/icarus/> and tick the PATH option, then open a new terminal. The Python outputs still work without it. |
| GTKWave shows `z` on `c_pin` | This is correct: Node C is high-Z by design. |
| `out/canfd_verilog_log.csv` is empty | Run `vvp out\sim.vvp` from this folder, not from `out`. |
| Matplotlib window does not open | The scripts use the `Agg` backend and only write PNG files; no window is needed. |
| Path contains spaces | The runners use `cd /d "%~dp0"` and quoted paths, so `MAIN EL 1` is fine. |

---

## 9. One-line architecture reminder

A and B are the two safety channels running the 2oo2 comparison and
cross-monitoring over CAN-FD; C is the independent, passive logger that can
observe the bus without affecting the safety loop.
