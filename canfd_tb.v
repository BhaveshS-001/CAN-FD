`timescale 1ns/1ps
// ===========================================================================
//  canfd_tb.v - testbench / top level for the CAN-FD demo
// ===========================================================================
//  Nodes:
//    A : RM46 safety channel  - transmitter + monitor/ACK
//    B : S32 safety channel   - receiver, ACK, 2oo2 compare + monitor/ACK
//    C : S32 logging channel  - listen-only, never drives, writes CSV
//
//  Bus is an open-drain model: 0 = dominant, 1 = recessive (idle).
//  Node C's pin is explicitly high-Z (c_pin) and is never in the bus equation.
//
//  *** BEHAVIOURAL MODEL - NOT CYCLE-ACCURATE ***
//  The bit timing (500 kbit/s nominal, 2 Mbit/s data) is modelled.  Clock
//  recovery, transceiver delays and the RM46/S32 peripherals are not.
// ===========================================================================

module canfd_tb;

    `include "out/frames_def.vh"

    localparam integer GAP_CYCLES = 10000;   // 100 us at 100 MHz

    reg clk = 1'b0;
    reg rst = 1'b1;
    always #5 clk = ~clk;                    // 100 MHz

    // ---- transmitter control ---------------------------------------------
    reg         a_start, b_start;
    reg  [11:0] a_base, a_len, b_base, b_len;
    reg  [1:0]  owner;                       // 1 = A, 2 = B
    reg         frame_start;
    reg         fault_en;

    // ---- node A transmitter ----------------------------------------------
    wire        a_active, a_done, a_bit_start, a_sample, a_dom;
    wire [11:0] a_bit_idx;
    wire [31:0] a_word;
    wire        a_ack_seen, a_ack_error;

    // ---- node B transmitter (heartbeat) ----------------------------------
    wire        b_active, b_done, b_bit_start, b_sample, b_tx_dom;
    wire [11:0] b_bit_idx;
    wire [31:0] b_word;
    wire        b_ack_seen_tx, b_ack_error_tx;

    // ---- ACK drives from the two listeners -------------------------------
    wire        a_ack_dom;                   // A ACKs B's heartbeat
    wire        b_ack_dom;                   // B ACKs A's frames
    wire        c_drive_unused;              // C must never drive

    // ---- fault injection and resolved bus --------------------------------
    wire fault_apply = fault_en && a_active && (a_bit_idx == FAULT_BIT);
    wire a_dom_eff   = fault_apply ? 1'b0 : a_dom;
    wire fault_dom   = fault_apply ? ~a_dom : 1'b0;
    wire bus = ~(a_dom_eff | b_tx_dom | a_ack_dom | b_ack_dom | fault_dom);
    wire c_pin = 1'bz;                       // logger pin: high-Z forever

    // ---- shared PHY bit timing -------------------------------------------
    wire bit_start_stb = (owner == 2'd1) ? a_bit_start :
                         (owner == 2'd2) ? b_bit_start : 1'b0;
    wire sample_stb    = (owner == 2'd1) ? a_sample :
                         (owner == 2'd2) ? b_sample : 1'b0;
    wire [1:0] phase_sel = (owner == 2'd1) ? a_word[3:2] :
                           (owner == 2'd2) ? b_word[3:2] : 2'b00;
    wire stuff_sel = (owner == 2'd1) ? a_word[1] :
                     (owner == 2'd2) ? b_word[1] : 1'b0;

    // ---- listener results -------------------------------------------------
    wire        a_crc_ok, a_ack_seen_l, a_match, a_hb_ok, a_error_flag;
    wire [10:0] a_frame_id;
    wire        a_brs;
    wire [3:0]  a_dlc;
    wire        a_frame_done;
    wire [16:0] a_crc_rx, a_crc_calc;

    wire        b_crc_ok, b_ack_seen, b_match, b_hb_ok, b_error_flag;
    wire [10:0] b_frame_id;
    wire        b_brs;
    wire [3:0]  b_dlc;
    wire        b_frame_done;
    wire [16:0] b_crc_rx, b_crc_calc;

    wire        c_crc_ok, c_ack_seen, c_match, c_hb_ok, c_error_flag;
    wire [10:0] c_frame_id;
    wire        c_brs;
    wire [3:0]  c_dlc;
    wire        c_frame_done;
    wire [16:0] c_crc_rx, c_crc_calc;

    // ---- node A: transmitter + monitor/ACK -------------------------------
    canfd_tx a_tx (
        .clk(clk), .rst(rst), .start(a_start),
        .base(a_base), .len(a_len), .bus(bus),
        .active(a_active), .done(a_done), .bit_idx(a_bit_idx), .word(a_word),
        .dom(a_dom), .bit_start(a_bit_start), .sample(a_sample),
        .ack_seen(a_ack_seen), .ack_error(a_ack_error)
    );

    canfd_listener #(.NODE(1), .DO_ACK(1), .DO_CSV(0)) a_listener (
        .clk(clk), .rst(rst), .frame_start(frame_start), .owner(owner),
        .bit_start(bit_start_stb), .sample(sample_stb), .bus(bus),
        .expected_payload(EXPECTED_PAYLOAD), .hb_expected(HB_B_BYTE),
        .crc_ok(a_crc_ok), .ack_seen(a_ack_seen_l), .match(a_match),
        .hb_ok(a_hb_ok), .error_flag(a_error_flag),
        .frame_id_out(a_frame_id), .brs_out(a_brs), .dlc_out(a_dlc),
        .drive(a_ack_dom), .frame_done(a_frame_done),
        .crc_rx_out(a_crc_rx), .crc_calc_out(a_crc_calc)
    );

    // ---- node B: transmitter (heartbeat) + receiver/ACK/2oo2 ------------
    canfd_tx b_tx (
        .clk(clk), .rst(rst), .start(b_start),
        .base(b_base), .len(b_len), .bus(bus),
        .active(b_active), .done(b_done), .bit_idx(b_bit_idx), .word(b_word),
        .dom(b_tx_dom), .bit_start(b_bit_start), .sample(b_sample),
        .ack_seen(b_ack_seen_tx), .ack_error(b_ack_error_tx)
    );

    canfd_listener #(.NODE(2), .DO_ACK(1), .DO_CSV(0)) b_listener (
        .clk(clk), .rst(rst), .frame_start(frame_start), .owner(owner),
        .bit_start(bit_start_stb), .sample(sample_stb), .bus(bus),
        .expected_payload(EXPECTED_PAYLOAD), .hb_expected(HB_A_BYTE),
        .crc_ok(b_crc_ok), .ack_seen(b_ack_seen), .match(b_match),
        .hb_ok(b_hb_ok), .error_flag(b_error_flag),
        .frame_id_out(b_frame_id), .brs_out(b_brs), .dlc_out(b_dlc),
        .drive(b_ack_dom), .frame_done(b_frame_done),
        .crc_rx_out(b_crc_rx), .crc_calc_out(b_crc_calc)
    );

    // ---- node C: listen-only logger --------------------------------------
    canfd_listener #(.NODE(3), .DO_ACK(0), .DO_CSV(1)) c_listener (
        .clk(clk), .rst(rst), .frame_start(frame_start), .owner(owner),
        .bit_start(bit_start_stb), .sample(sample_stb), .bus(bus),
        .expected_payload(EXPECTED_PAYLOAD), .hb_expected(8'h00),
        .crc_ok(c_crc_ok), .ack_seen(c_ack_seen), .match(c_match),
        .hb_ok(c_hb_ok), .error_flag(c_error_flag),
        .frame_id_out(c_frame_id), .brs_out(c_brs), .dlc_out(c_dlc),
        .drive(c_drive_unused), .frame_done(c_frame_done),
        .crc_rx_out(c_crc_rx), .crc_calc_out(c_crc_calc)
    );

    // ---- waveform dump ----------------------------------------------------
    initial begin
        $dumpfile("out/canfd_verilog.vcd");
        $dumpvars(0, bus, phase_sel, stuff_sel,
                  a_dom, a_dom_eff, b_tx_dom, a_ack_dom, b_ack_dom, fault_dom,
                  c_pin, a_active, b_active, a_bit_idx, b_bit_idx,
                  bit_start_stb, sample_stb, owner, fault_apply,
                  a_ack_seen, a_ack_error,
                  b_crc_ok, b_ack_seen, b_match, b_hb_ok, b_error_flag,
                  c_crc_ok, c_ack_seen, c_error_flag,
                  b_frame_id, c_frame_id, b_dlc, c_dlc,
                  a_crc_ok, a_hb_ok);
    end

    // ---- tasks ------------------------------------------------------------
    task start_a(input [11:0] base, input [11:0] len);
        begin
            owner       = 2'd1;
            a_base      = base;
            a_len       = len;
            a_start     = 1'b1;
            frame_start = 1'b1;
            @(posedge clk);
            #1;                 // let the always block sample start first
            a_start     = 1'b0;
            frame_start = 1'b0;
        end
    endtask

    task start_b(input [11:0] base, input [11:0] len);
        begin
            owner       = 2'd2;
            b_base      = base;
            b_len       = len;
            b_start     = 1'b1;
            frame_start = 1'b1;
            @(posedge clk);
            #1;                 // let the always block sample start first
            b_start     = 1'b0;
            frame_start = 1'b0;
        end
    endtask

    task gap;
        begin
            owner = 2'd0;
            repeat (GAP_CYCLES) @(posedge clk);
        end
    endtask

    // ---- main sequence ----------------------------------------------------
    reg pass;

    initial begin
        pass      = 1'b1;
        rst       = 1'b1;
        a_start   = 1'b0;
        b_start   = 1'b0;
        owner     = 2'd0;
        frame_start = 1'b0;
        fault_en  = 1'b0;
        a_base    = 12'd0;
        a_len     = 12'd0;
        b_base    = 12'd0;
        b_len     = 12'd0;

        #100;
        rst = 1'b0;
        #100;

        $display("");
        $display("==============================================================");
        $display(" VERILOG CAN-FD NODE SIMULATION (behavioural)");
        $display(" 500 kbit/s nominal -> 2 Mbit/s data, BRS=1, 16-byte payload");
        $display("==============================================================");

        // ---- frame 0: A data frame, normal --------------------------------
        start_a(F0_BASE, F0_LEN);
        wait (a_done);
        @(posedge clk); #1;
        $display("[%0.1f us] A data    0x%03X: B crc=%0d ack=%0d match=%0d | C crc=%0d ack=%0d | A ack_seen=%0d ack_err=%0d",
                 $time / 1000.0, b_frame_id, b_crc_ok, b_ack_seen, b_match,
                 c_crc_ok, c_ack_seen, a_ack_seen, a_ack_error);
        if (!(b_crc_ok && b_match && a_ack_seen && c_crc_ok && c_ack_seen))
            pass = 1'b0;
        gap();

        // ---- frame 1: heartbeat from A ------------------------------------
        start_a(F1_BASE, F1_LEN);
        wait (a_done);
        @(posedge clk); #1;
        $display("[%0.1f us] A HB      0x%03X: B crc=%0d hb_ok=%0d | C crc=%0d ack=%0d",
                 $time / 1000.0, b_frame_id, b_crc_ok, b_hb_ok,
                 c_crc_ok, c_ack_seen);
        if (!(b_crc_ok && b_hb_ok && c_crc_ok))
            pass = 1'b0;
        gap();

        // ---- frame 2: heartbeat from B ------------------------------------
        start_b(F2_BASE, F2_LEN);
        wait (b_done);
        @(posedge clk); #1;
        $display("[%0.1f us] B HB      0x%03X: A crc=%0d hb_ok=%0d | C crc=%0d ack=%0d",
                 $time / 1000.0, a_frame_id, a_crc_ok, a_hb_ok,
                 c_crc_ok, c_ack_seen);
        if (!(a_crc_ok && a_hb_ok && c_crc_ok && c_ack_seen))
            pass = 1'b0;
        gap();

        // ---- frame 3: fault injection -------------------------------------
        fault_en = 1'b1;
        start_a(F3_BASE, F3_LEN);
        wait (a_done);
        @(posedge clk); #1;
        $display("[%0.1f us] FAULT     bit %0d: B crc=%0d ack=%0d | C crc=%0d ack=%0d | A ack_seen=%0d ack_err=%0d",
                 $time / 1000.0, FAULT_BIT, b_crc_ok, b_ack_seen,
                 c_crc_ok, c_ack_seen, a_ack_seen, a_ack_error);
        if (!((!b_crc_ok) && (!b_ack_seen) && (!c_crc_ok) && (!c_ack_seen) &&
              (!a_ack_seen) && a_ack_error && b_error_flag && c_error_flag))
            pass = 1'b0;
        fault_en = 1'b0;
        gap();

        // ---- frame 4: recovery --------------------------------------------
        start_a(F4_BASE, F4_LEN);
        wait (a_done);
        @(posedge clk); #1;
        $display("[%0.1f us] RECOVERY 0x%03X: B crc=%0d ack=%0d match=%0d | C crc=%0d ack=%0d",
                 $time / 1000.0, b_frame_id, b_crc_ok, b_ack_seen, b_match,
                 c_crc_ok, c_ack_seen);
        if (!(b_crc_ok && b_match && a_ack_seen && c_crc_ok && c_ack_seen))
            pass = 1'b0;
        gap();

        $display("--------------------------------------------------------------");
        if (pass)
            $display(" RESULT: PASS");
        else
            $display(" RESULT: FAIL");
        $display(" C log : out/canfd_verilog_log.csv");
        $display(" VCD   : out/canfd_verilog.vcd (open with gtkwave)");
        $display("==============================================================");
        $display("");

        $fclose(c_listener.csv_fd);
        $finish;
    end

endmodule
