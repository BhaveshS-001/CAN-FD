@echo off
REM ===========================================================================
REM  run_all.bat - one command for the whole demo (Windows)
REM  Usage:  run_all.bat            (pauses at the end)
REM          run_all.bat --no-pause (for automation)
REM ===========================================================================
setlocal
cd /d "%~dp0"

echo ============================================================
echo  Three-channel safety demo - FSK + CAN-FD + listen-only logger
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found on PATH.
    echo         Install Python 3.10+ and tick "Add python.exe to PATH".
    goto :fail
)

python -c "import numpy, matplotlib" >nul 2>nul
if errorlevel 1 (
    echo [ERROR] numpy / matplotlib are missing.
    echo         Run:  python -m pip install numpy matplotlib
    goto :fail
)

echo [1/3] FSK modulator / demodulator ...
python fsk_chain.py
if errorlevel 1 goto :fail
echo.

echo [2/3] CAN-FD Python reference model + Verilog frame data ...
python canfd_model.py
if errorlevel 1 goto :fail
echo.

echo [3/3] Verilog / GTKWave model ...
where iverilog >nul 2>nul
if errorlevel 1 (
    echo [INFO] iverilog not found - skipping the RTL-style simulation.
    echo        The Python timing diagram and CSV are still complete.
    echo        Optional install: https://bleyer.org/icarus/
    goto :done
)

iverilog -g2012 -o out\sim.vvp canfd_nodes.v canfd_tb.v
if errorlevel 1 (
    echo [WARN] Verilog compile failed - Python outputs are still valid.
    goto :done
)
vvp out\sim.vvp
if errorlevel 1 (
    echo [WARN] Verilog simulation returned an error.
    goto :done
)

where gtkwave >nul 2>nul
if not errorlevel 1 (
    echo [INFO] View the waveform with:
    echo        gtkwave out\canfd_verilog.vcd
)

:done
echo.
echo ============================================================
echo  Done. Generated files in the "out" folder:
echo    out\fsk_demo.png            FSK plots
echo    out\timing_diagram.png      normal CAN-FD frame + timeline
echo    out\fault_timing.png        fault-injection frame
echo    out\canfd_log.csv           Python model C log
echo    out\canfd_verilog_log.csv   Verilog C log (if iverilog ran)
echo    out\canfd_verilog.vcd       GTKWave waveform (if iverilog ran)
echo ============================================================
echo.

if /I "%~1"=="--no-pause" exit /b 0
pause
exit /b 0

:fail
echo.
echo [ERROR] The run stopped. Fix the message above and try again.
if /I "%~1"=="--no-pause" exit /b 1
pause
exit /b 1
