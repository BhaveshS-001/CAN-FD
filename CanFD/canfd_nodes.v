`timescale 1ns/1ps
// ===========================================================================
//  canfd_nodes.v - behavioural CAN-FD transmitter and listener
// ===========================================================================
//  *** BEHAVIOURAL MODEL - NOT CYCLE-ACCURATE ***
//  This models the protocol logic only.  It does not model the RM46 or S32
//  CAN peripheral registers, the analogue transceiver, or clock tolerance.
//
//  The frame bit stream (including CRC and stuff bits) is produced by
//  canfd_model.py and loaded from out/frames.mem.  The listener receives the
//  bus waveform, removes stuff bits, decodes the fields, checks the CRC and
//  (for node B) drives the ACK slot.  Node C only listens and logs.
//
//  Simplification: all nodes use the testbench bit-timing strobes instead of
//  independent bit-rate recovery / resynchronisation.  This keeps the demo
//  deterministic; the bit timing itself (500 kbit/s -> 2 Mbit/s) is modelled.
//  The CAN-FD stuff-count field and the fixed stuff bits inside the CRC field
//  are not modelled; only the normal "after five equal bits" rule is used.
//  This simplification is explicitly allowed by the assignment.
// ===========================================================================

module canfd_tx (
    input  wire        clk,
    input  wire        rst,
    input  wire        start,
    input  wire [11:0] base,       // first word in out/frames.mem
    input  wire [11:0] len,        // number of wire bits in this frame
    input  wire        bus,        // used to sample the ACK slot
    output reg         active,
    output reg         done,
    output reg  [11:0] bit_idx,
    output reg  [31:0] word,
    output wire        dom,        // 1 = pull the bus dominant
    output reg         bit_start,  // one-clock pulse at the start of each bit
    output reg         sample,     // one-clock pulse at the bit sample point
    output reg         ack_seen,
    output reg         ack_error
);

    // Frame memory word:
    //   [19:16] field code, [15:4] duration in ns,
    //   [3:2] phase (0=nominal, 1=data), [1] stuff bit, [0] bit value
    reg [31:0] mem [0:1023];
    initial $readmemh("out/frames.mem", mem);

    reg [11:0] base_i, len_i;
    reg [15:0] cyc;
    wire [15:0] dur_cyc  = word[15:4] / 10;   // 100 MHz clock -> ns/10 cycles
    wire [15:0] half_cyc = dur_cyc >> 1;

    assign dom = active && (word[0] == 1'b0);

    always @(posedge clk) begin
        if (rst) begin
            active    <= 1'b0;
            done      <= 1'b0;
            bit_idx   <= 12'd0;
            word      <= 32'd0;
            cyc       <= 16'd0;
            bit_start <= 1'b0;
            sample    <= 1'b0;
            ack_seen  <= 1'b0;
            ack_error <= 1'b0;
        end else begin
            done      <= 1'b0;
            bit_start <= 1'b0;
            sample    <= 1'b0;

            if (start) begin
                active    <= 1'b1;
                base_i    <= base;
                len_i     <= len;
                bit_idx   <= 12'd0;
                word      <= mem[base];
                cyc       <= 16'd0;
                bit_start <= 1'b1;
                ack_seen  <= 1'b0;
                ack_error <= 1'b0;
            end else if (active) begin
                if (cyc == dur_cyc - 1) begin
                    cyc <= 16'd0;
                    if (bit_idx == len_i - 1) begin
                        active    <= 1'b0;
                        done      <= 1'b1;
                        ack_error <= ~ack_seen;   // ACK slot was recessive -> error
                    end else begin
                        bit_idx   <= bit_idx + 12'd1;
                        word      <= mem[base_i + bit_idx + 12'd1];
                        bit_start <= 1'b1;
                    end
                end else begin
                    if (cyc == half_cyc - 1) begin
                        sample <= 1'b1;
                        // ACK slot: the transmitter sends recessive (1) and
                        // checks whether another node pulled the bus dominant.
                        if (word[19:16] == 4'd6 && word[0] == 1'b1)
                            ack_seen <= (bus == 1'b0);
                    end
                    cyc <= cyc + 16'd1;
                end
            end
        end
    end
endmodule


module canfd_listener #(
    parameter integer NODE   = 1,   // 1 = A monitor, 2 = B, 3 = C logger
    parameter integer DO_ACK = 0,   // 1 = this node may drive the ACK slot
    parameter integer DO_CSV = 0    // 1 = node C writes the CSV log
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        frame_start,
    input  wire [1:0]  owner,          // 1 = A is transmitting, 2 = B
    input  wire        bit_start,
    input  wire        sample,
    input  wire        bus,
    input  wire [127:0] expected_payload,
    input  wire [7:0]  hb_expected,    // expected heartbeat byte
    output reg         crc_ok,
    output reg         ack_seen,
    output reg         match,
    output reg         hb_ok,
    output reg         error_flag,
    output reg  [10:0] frame_id_out,
    output reg         brs_out,
    output reg  [3:0]  dlc_out,
    output reg         drive,          // 1 = pull ACK dominant
    output reg         frame_done,
    output reg  [16:0] crc_rx_out,
    output reg  [16:0] crc_calc_out
);

    localparam [10:0] DATA_ID = 11'h123;
    localparam [10:0] HB_ID   = 11'h100;

    // ---- CAN-FD DLC -> byte count -----------------------------------------
    function [7:0] dlc_len;
        input [3:0] d;
        begin
            case (d)
                4'd0: dlc_len = 8'd0;   4'd1: dlc_len = 8'd1;
                4'd2: dlc_len = 8'd2;   4'd3: dlc_len = 8'd3;
                4'd4: dlc_len = 8'd4;   4'd5: dlc_len = 8'd5;
                4'd6: dlc_len = 8'd6;   4'd7: dlc_len = 8'd7;
                4'd8: dlc_len = 8'd8;   4'd9: dlc_len = 8'd12;
                4'd10: dlc_len = 8'd16; 4'd11: dlc_len = 8'd20;
                4'd12: dlc_len = 8'd24; 4'd13: dlc_len = 8'd32;
                4'd14: dlc_len = 8'd48; 4'd15: dlc_len = 8'd64;
                default: dlc_len = 8'd0;
            endcase
        end
    endfunction

    // ---- CRC-17, polynomial 0x1685B, MSB first ----------------------------
    function [16:0] crc_step;
        input [16:0] c;
        input        b;
        reg          msb;
        begin
            msb = c[16] ^ b;
            crc_step = {c[15:0], 1'b0};
            if (msb)
                crc_step = crc_step ^ 17'h1685B;
        end
    endfunction

    reg        active, ignore, stuff_en;
    reg [3:0]  run;
    reg        prev;
    reg [9:0]  bit_count;
    reg [16:0] crc, rx_crc;
    reg [10:0] id_reg;
    reg [3:0]  dlc_reg;
    reg        brs_reg, fdf_reg;
    reg [2:0]  state;
    reg [2:0]  eof_cnt;
    reg [1:0]  ifs_cnt;
    reg        crc_ok_reg, ack_seen_reg, error_reg;
    reg        ack_arm, ack_go;
    reg [63:0] ts_ns;

    // payload bytes, assembled as the data field arrives
    reg [7:0] pbyte [0:15];
    reg [7:0] byte_buf;
    reg [2:0] bit_in_byte;
    reg [4:0] byte_idx;
    integer   pi, k, j;
    reg       mm;
    reg [127:0] exp_shift;

    wire [7:0]  data_len_w = dlc_len(dlc_reg);
    wire [9:0]  data_end_w = 10'd22 + (10'd8 * data_len_w);
    wire [3:0]  run_next   = (bus == prev) ? (run + 4'd1) : 4'd1;

    // CSV file (only node C opens it)
    integer csv_fd;
    initial begin
        csv_fd = 0;
        if (DO_CSV != 0) begin
            csv_fd = $fopen("out/canfd_verilog_log.csv", "w");
            $fwrite(csv_fd, "timestamp_us,id,brs,dlc,payload_hex,crc_ok,ack_seen\n");
        end
    end

    always @(posedge clk) begin
        if (rst) begin
            active <= 1'b0; ignore <= 1'b0; stuff_en <= 1'b0;
            run <= 4'd0; prev <= 1'b1; bit_count <= 10'd0;
            crc <= 17'd0; rx_crc <= 17'd0;
            id_reg <= 11'd0; dlc_reg <= 4'd0; brs_reg <= 1'b0; fdf_reg <= 1'b0;
            state <= 3'd0; eof_cnt <= 3'd0; ifs_cnt <= 2'd0;
            crc_ok_reg <= 1'b0; ack_seen_reg <= 1'b0; error_reg <= 1'b0;
            ack_arm <= 1'b0; ack_go <= 1'b0; drive <= 1'b0;
            ts_ns <= 64'd0;
            byte_buf <= 8'd0; bit_in_byte <= 3'd0; byte_idx <= 5'd0;
            for (pi = 0; pi < 16; pi = pi + 1) pbyte[pi] <= 8'd0;
            crc_ok <= 1'b0; ack_seen <= 1'b0; match <= 1'b0; hb_ok <= 1'b0;
            error_flag <= 1'b0; frame_id_out <= 11'd0; brs_out <= 1'b0;
            dlc_out <= 4'd0; frame_done <= 1'b0;
            crc_rx_out <= 17'd0; crc_calc_out <= 17'd0;
        end else begin
            frame_done <= 1'b0;

            if (frame_start) begin
                active <= 1'b1;
                ignore <= (owner == NODE);
                stuff_en <= 1'b1;
                run <= 4'd0; prev <= 1'b1; bit_count <= 10'd0;
                crc <= 17'd0; rx_crc <= 17'd0;
                id_reg <= 11'd0; dlc_reg <= 4'd0; brs_reg <= 1'b0; fdf_reg <= 1'b0;
                state <= 3'd0; eof_cnt <= 3'd0; ifs_cnt <= 2'd0;
                crc_ok_reg <= 1'b0; ack_seen_reg <= 1'b0; error_reg <= 1'b0;
                ack_arm <= 1'b0; ack_go <= 1'b0; drive <= 1'b0;
                ts_ns <= $time;
                byte_buf <= 8'd0; bit_in_byte <= 3'd0; byte_idx <= 5'd0;
                for (pi = 0; pi < 16; pi = pi + 1) pbyte[pi] <= 8'd0;
                crc_ok <= 1'b0; ack_seen <= 1'b0; match <= 1'b0; hb_ok <= 1'b0;
                error_flag <= 1'b0; frame_id_out <= 11'd0; brs_out <= 1'b0;
                dlc_out <= 4'd0;
                crc_rx_out <= 17'd0; crc_calc_out <= 17'd0;
            end else if (active) begin

                // ---- ACK drive timing -----------------------------------
                // ack_go is set when the CRC delimiter is sampled; the next
                // bit_start is the ACK slot.  The drive is removed at the ACK
                // sample point (state 2) so it cannot leak into the delimiter.
                if (bit_start) begin
                    if (ack_go) begin
                        drive  <= 1'b1;
                        ack_go <= 1'b0;
                    end else if (drive) begin
                        drive <= 1'b0;
                    end
                end

                if (sample && !ignore) begin
                    case (state)
                    // ------------------------------------------------------
                    // state 0: SOF .. end of CRC sequence (stuffing active)
                    // ------------------------------------------------------
                    3'd0: begin
                        if (stuff_en && bit_count > 0 && run == 4'd5) begin
                            // this wire bit is a stuff bit - skip it
                            if (bus == prev) error_reg <= 1'b1; // stuff error
                            prev <= bus;
                            run  <= 4'd1;
                        end else begin
                            // CRC: message bits for SOF..data, then 17 zero
                            // bits while the CRC sequence is being received.
                            if (bit_count < data_end_w)
                                crc <= crc_step(crc, bus);
                            else
                                crc <= crc_step(crc, 1'b0);

                            if (bit_count >= 10'd1 && bit_count <= 10'd11)
                                id_reg <= {id_reg[9:0], bus};
                            if (bit_count == 10'd14) fdf_reg <= bus;
                            if (bit_count == 10'd16) brs_reg <= bus;
                            if (bit_count >= 10'd18 && bit_count <= 10'd21)
                                dlc_reg <= {dlc_reg[2:0], bus};

                            // data field -> bytes
                            if (bit_count >= 10'd22 && bit_count < data_end_w) begin
                                byte_buf <= {byte_buf[6:0], bus};
                                if (bit_in_byte == 3'd7) begin
                                    pbyte[byte_idx] <= {byte_buf[6:0], bus};
                                    byte_idx  <= byte_idx + 5'd1;
                                    bit_in_byte <= 3'd0;
                                end else begin
                                    bit_in_byte <= bit_in_byte + 3'd1;
                                end
                            end

                            // received CRC sequence
                            if (bit_count >= data_end_w &&
                                bit_count < data_end_w + 10'd17)
                                rx_crc <= {rx_crc[15:0], bus};

                            if (bit_count == data_end_w + 10'd16) begin
                                // 17th CRC bit: both crc and rx_crc are now final
                                crc_ok_reg  <= ({rx_crc[15:0], bus} ==
                                                crc_step(crc, 1'b0));
                                crc_rx_out  <= {rx_crc[15:0], bus};
                                crc_calc_out <= crc_step(crc, 1'b0);
                                stuff_en    <= 1'b0;
                                if (DO_ACK != 0)
                                    ack_arm <= ({rx_crc[15:0], bus} ==
                                                crc_step(crc, 1'b0));
                                // a final stuff bit may follow the last CRC bit
                                if (run_next == 4'd5)
                                    state <= 3'd6;
                                else
                                    state <= 3'd1;
                            end

                            if (bus == prev) run <= run + 4'd1;
                            else             run <= 4'd1;
                            prev <= bus;
                            bit_count <= bit_count + 10'd1;
                        end
                    end

                    // ------------------------------------------------------
                    // state 6: optional stuff bit after the last CRC bit
                    // ------------------------------------------------------
                    3'd6: begin
                        if (bus == prev) error_reg <= 1'b1;
                        prev  <= bus;
                        run   <= 4'd1;
                        state <= 3'd1;
                    end

                    // ------------------------------------------------------
                    // CRC delimiter
                    // ------------------------------------------------------
                    3'd1: begin
                        if (bus != 1'b1) error_reg <= 1'b1;
                        state <= 3'd2;
                        if (DO_ACK != 0 && ack_arm && bus == 1'b1)
                            ack_go <= 1'b1;
                    end

                    // ------------------------------------------------------
                    // ACK slot: sample it; B removes its dominant drive here
                    // ------------------------------------------------------
                    3'd2: begin
                        ack_seen_reg <= (bus == 1'b0);
                        drive <= 1'b0;
                        state <= 3'd3;
                    end

                    // ------------------------------------------------------
                    // ACK delimiter + EOF + IFS
                    // ------------------------------------------------------
                    3'd3: begin
                        if (bus != 1'b1) error_reg <= 1'b1;
                        state   <= 3'd4;
                        eof_cnt <= 3'd0;
                    end

                    3'd4: begin
                        if (bus != 1'b1) error_reg <= 1'b1;
                        eof_cnt <= eof_cnt + 3'd1;
                        if (eof_cnt == 3'd6)
                            state <= 3'd5;
                    end

                    3'd5: begin
                        if (bus != 1'b1) error_reg <= 1'b1;
                        ifs_cnt <= ifs_cnt + 2'd1;
                        if (ifs_cnt == 2'd2) begin
                            active <= 1'b0;
                            frame_done <= 1'b1;
                            crc_ok   <= crc_ok_reg;
                            ack_seen <= ack_seen_reg;
                            frame_id_out <= id_reg;
                            brs_out  <= brs_reg;
                            dlc_out  <= dlc_reg;
                            error_flag <= error_reg | ~crc_ok_reg;

                            // 2oo2 compare against B's own copy (16-byte data)
                            exp_shift = expected_payload;
                            mm = 1'b1;
                            for (k = 0; k < 16; k = k + 1) begin
                                if (pbyte[k] != exp_shift[127:120])
                                    mm = 1'b0;
                                exp_shift = exp_shift << 8;
                            end
                            match <= (id_reg == DATA_ID) && crc_ok_reg && mm;
                            hb_ok <= (id_reg == HB_ID) && crc_ok_reg &&
                                     (pbyte[0] == hb_expected);
                        end
                    end

                    default: state <= 3'd0;
                    endcase
                end
            end
        end
    end

    // ---- node C logger ----------------------------------------------------
    always @(posedge clk) begin
        if (frame_done && DO_CSV != 0) begin
            $fwrite(csv_fd, "%0.3f,%03X,%0d,%0d,",
                    ts_ns / 1000.0, frame_id_out, brs_out, dlc_out);
            for (j = 0; j < 16; j = j + 1) begin
                if (j < dlc_len(dlc_out))
                    $fwrite(csv_fd, "%02X", pbyte[j]);
            end
            $fwrite(csv_fd, ",%0d,%0d\n", crc_ok, ack_seen);
        end
    end

endmodule
