#!/usr/bin/env bash
# ===========================================================================
#  run_all.sh - one command for the whole demo (Linux / macOS / Git Bash)
# ===========================================================================
set -u
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
command -v "$PY" >/dev/null 2>&1 || PY=python

echo "============================================================"
echo " Three-channel safety demo - FSK + CAN-FD + pass logger"
echo "============================================================"
echo

if ! "$PY" -c "import numpy, matplotlib" >/dev/null 2>&1; then
    echo "[ERROR] numpy / matplotlib missing."
    echo "        Run: $PY -m pip install numpy matplotlib"
    exit 1
fi

echo "[1/3] FSK modulator / demodulator ..."
"$PY" fsk_chain.py || exit 1
echo

echo "[2/3] CAN-FD Python reference model + Verilog frame data ..."
"$PY" canfd_model.py || exit 1
echo

echo "[3/3] Verilog / GTKWave model ..."
if ! command -v iverilog >/dev/null 2>&1; then
    echo "[INFO] iverilog not found - skipping the RTL-style simulation."
    echo "       The Python timing diagram and CSV are still complete."
else
    if iverilog -g2012 -o out/sim.vvp canfd_nodes.v canfd_tb.v; then
        vvp out/sim.vvp
    else
        echo "[WARN] Verilog compile failed - Python outputs are still valid."
    fi
fi

echo
echo "============================================================"
echo " Done. See the out/ folder:"
echo "   out/fsk_demo.png"
echo "   out/timing_diagram.png"
echo "   out/fault_timing.png"
echo "   out/canfd_log.csv"
echo "   out/canfd_verilog_log.csv   (if iverilog ran)"
echo "   out/canfd_verilog.vcd       (if iverilog ran)"
echo "============================================================"
