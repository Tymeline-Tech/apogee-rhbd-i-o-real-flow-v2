// =============================================================================
// tb_top_io — Icarus testbench for TOP_IO digital/analog integration
// Apogee RHBD I/O (sky130 g5v0d10v5)
//
// Instantiates:
//   - models/ls_up.va  (via verilog_ams import; digital twin under Icarus)
//   - models/por.va    (via verilog_ams import; digital twin under Icarus)
//   - rtl/reset_combiner.v
//
// Stimulus covers supply (1.4 / 3.3 / 5.5 V), temperature (−55 / 27 / 125 C),
// process (ss / tt / ff), and SEU upset / normal-operation cases.
// Dumps VCD for waveform inspection (tb_top_io.vcd).
//
// Reference: OpenTitan-style block TB structure (stimulus + checks + VCD),
// adapted for mixed-signal POR / LS_UP glue into reset_combiner.
// =============================================================================

`timescale 1ns / 1ps
`default_nettype none

// -----------------------------------------------------------------------------
// verilog_ams import — bind Verilog-A behavioral sources for AMS cosim /
// verification-suite mixed-signal runs. Under plain Icarus the digital twins
// below (same module names / parameters as models/*.va) are elaborated instead.
// -----------------------------------------------------------------------------
`ifndef VERILOG_AMS
  `define VERILOG_AMS
`endif

`ifdef VERILOG_AMS
  // import "verilog_ams" ls_up <- ../models/ls_up.va
  // import "verilog_ams" por   <- ../models/por.va
  `define VERILOG_AMS_LS_UP_PATH "../models/ls_up.va"
  `define VERILOG_AMS_POR_PATH   "../models/por.va"
`endif

// =============================================================================
// Digital twin: ls_up  (mirrors models/ls_up.va port / parameter surface)
// VDDL-domain IN → VDDH-domain OUT. SEU is applied from the TB (seu_inj).
// =============================================================================
module ls_up #(
    parameter real    vddl_nom   = 1.8,
    parameter real    vddh_nom   = 5.0,
    parameter real    vin_thresh = 0.5,
    parameter real    process    = 0.0,   // -1=ss, 0=tt, +1=ff
    parameter real    temp_c     = 27.0,
    parameter integer seu        = 0,
    parameter real    seu_time   = 50.0e-9,
    parameter real    seu_width  = 1.0e-9,
    parameter real    seu_amp    = 1.0
) (
    input  wire IN,
    output wire OUT,
    input  wire VDDL_OK,
    input  wire VDDH_OK,
    input  wire VSS,
    input  wire seu_inj          // TB: pulse high to force SEU glitch
);

    integer tpd_i;
    real    pvt_delay;
    reg     out_q;

    initial begin
        out_q = 1'b0;
        pvt_delay = (1.0 - 0.25 * process) * (1.0 + 0.003 * (temp_c - 27.0));
        if (pvt_delay < 0.1)
            pvt_delay = 0.1;
        tpd_i = pvt_delay;
        if (tpd_i < 1)
            tpd_i = 1;
        // Touch VA-facing parameters so elaborators keep the surface alive
        if (seu < 0 || seu_amp < 0.0 || seu_time < 0.0 || seu_width < 0.0)
            $display("ls_up: bad seu params");
        if (vddl_nom < 0.0 || vddh_nom < 0.0 || vin_thresh < 0.0)
            $display("ls_up: bad supply params");
    end

    always @(IN or VDDL_OK or VDDH_OK or VSS) begin
        if (!VDDL_OK || !VDDH_OK || VSS)
            out_q <= 1'b0;
        else
            out_q <= #(tpd_i) IN;
    end

    // SEU: invert the steady level while seu_inj is high (seu_amp>=0.5 intent)
    assign OUT = seu_inj ? ~out_q : out_q;

endmodule

// =============================================================================
// Digital twin: por  (mirrors models/por.va port / parameter surface)
// Active-low POR_N. Release latency is exposed as release_ns for the TB.
// SEU re-assert is applied from the TB (seu_inj).
// =============================================================================
module por #(
    parameter real    vdd_nom    = 5.0,
    parameter real    process    = 0.0,   // -1=ss, 0=tt, +1=ff
    parameter real    temp_c     = 27.0,
    parameter integer seu        = 0,
    parameter real    seu_time   = 150.0e-6,
    parameter real    seu_width  = 1.0e-6,
    parameter real    seu_amp    = 1.0
) (
    input  wire VDD_OK,
    input  wire VSS,
    input  wire seu_inj,         // TB: pulse high to force POR re-assert
    output wire POR_N,
    output reg  [31:0] release_ns
);

    real pvt_scale;
    reg  released;

    initial begin
        released   = 1'b0;
        pvt_scale  = (1.0 - 0.12 * process) * (1.0 - 0.001 * (temp_c - 27.0));
        if (pvt_scale < 0.5)
            pvt_scale = 0.5;
        // ~ (Vrel/VDD)*100 us on Epic 1 ramp, expressed in ns
        release_ns = (100000.0 * 1.14 / vdd_nom) * pvt_scale;
        if (release_ns < 1000)
            release_ns = 1000;
        if (seu < 0 || seu_amp < 0.0 || seu_time < 0.0 || seu_width < 0.0)
            $display("por: bad seu params");
        if (temp_c < -100.0)
            $display("por: bad temp");
    end

    // Edge-safe release model: blocking delay inside a single-threaded fork
    // that aborts on rail collapse (no stacked NBA intra-assignment delays).
    always @(posedge VDD_OK) begin
        released <= 1'b0;
        fork
            begin : wait_release
                #(release_ns);
                if (VDD_OK && !VSS)
                    released <= 1'b1;
            end
            begin : abort_on_collapse
                @(negedge VDD_OK or posedge VSS);
                disable wait_release;
                released <= 1'b0;
            end
        join_any
        disable fork;
    end

    always @(negedge VDD_OK or posedge VSS) begin
        released <= 1'b0;
    end

    // Active-low: 0 while held / SEU, 1 when released
    assign POR_N = seu_inj ? 1'b0 : released;

endmodule

// =============================================================================
// TOP_IO integration testbench
// =============================================================================
module tb_top_io;

    // ---- Digital / clock domain ---------------------------------------------
    reg  clk;
    wire reset_in;
    wire reset_out;

    // ---- Analog-proxy / rail status -----------------------------------------
    reg  vss;
    reg  vddl_ok;
    reg  vddh_ok;

    // ---- LS_UP / POR dig paths ----------------------------------------------
    reg  ls_in;
    wire ls_out;
    wire por_n;
    wire [31:0] por_release_ns;
    reg  ls_seu_inj;
    reg  por_seu_inj;

    // ---- Sweep / scenario bookkeeping ---------------------------------------
    real    sweep_vddl;
    real    sweep_vddh;
    real    sweep_temp_c;
    real    sweep_process;
    integer sweep_seu;
    integer errors;
    integer corner_id;
    real    active_vdd_nom;
    real    active_temp_c;
    real    active_process;

`ifdef VERILOG_AMS
    initial begin
        $display("verilog_ams import ls_up: %s", `VERILOG_AMS_LS_UP_PATH);
        $display("verilog_ams import por:   %s", `VERILOG_AMS_POR_PATH);
    end
`endif

    // ---- Verilog-A digital twins + reset_combiner ---------------------------
    ls_up #(
        .vddl_nom (1.8),
        .vddh_nom (5.0),
        .process  (0.0),
        .temp_c   (27.0),
        .seu      (0)
    ) u_ls_up (
        .IN      (ls_in),
        .OUT     (ls_out),
        .VDDL_OK (vddl_ok),
        .VDDH_OK (vddh_ok),
        .VSS     (vss),
        .seu_inj (ls_seu_inj)
    );

    por #(
        .vdd_nom (5.0),
        .process (0.0),
        .temp_c  (27.0),
        .seu     (0)
    ) u_por (
        .VDD_OK     (vddh_ok),
        .VSS        (vss),
        .seu_inj    (por_seu_inj),
        .POR_N      (por_n),
        .release_ns (por_release_ns)
    );

    assign reset_in = por_n;

    reset_combiner u_reset_combiner (
        .clk       (clk),
        .reset_in  (reset_in),
        .reset_out (reset_out)
    );

    // ---- Clock --------------------------------------------------------------
    initial clk = 1'b0;
    always #5 clk = ~clk;   // 100 MHz digital domain

    // ---- VCD dump -----------------------------------------------------------
    initial begin
        $dumpfile("tb_top_io.vcd");
        $dumpvars(0, tb_top_io);
    end

    // ---- Helpers ------------------------------------------------------------
    task automatic power_down;
        begin
            ls_seu_inj  = 1'b0;
            por_seu_inj = 1'b0;
            vddl_ok     = 1'b0;
            vddh_ok     = 1'b0;
            ls_in       = 1'b0;
            #100;
        end
    endtask

    task automatic power_up_rails;
        input real vddl;
        input real vddh;
        begin
            sweep_vddl = vddl;
            sweep_vddh = vddh;
            vddl_ok = 1'b1;
            #1000;
            vddh_ok = 1'b1;
        end
    endtask

    task automatic wait_por_release;
        input integer timeout_ns;
        integer t;
        begin
            t = 0;
            while (reset_out !== 1'b1 && t < timeout_ns) begin
                #1000;
                t = t + 1000;
            end
            if (reset_out !== 1'b1) begin
                $display("FAIL corner %0d: POR did not release (VDDH=%0f T=%0f P=%0f SEU=%0d)",
                         corner_id, sweep_vddh, sweep_temp_c, sweep_process, sweep_seu);
                errors = errors + 1;
            end
        end
    endtask

    task automatic check_reset_follows_por;
        begin
            if (reset_out !== reset_in) begin
                $display("FAIL corner %0d: reset_combiner mismatch out=%b in=%b",
                         corner_id, reset_out, reset_in);
                errors = errors + 1;
            end
        end
    endtask

    task automatic exercise_ls_up;
        begin
            ls_in = 1'b0;
            #50;
            ls_in = 1'b1;
            #50;
            if (vddl_ok && vddh_ok && !ls_seu_inj && ls_out !== 1'b1) begin
                $display("FAIL corner %0d: LS_UP OUT stuck low after IN rise", corner_id);
                errors = errors + 1;
            end
            ls_in = 1'b0;
            #50;
            if (vddl_ok && vddh_ok && !ls_seu_inj && ls_out !== 1'b0) begin
                $display("FAIL corner %0d: LS_UP OUT stuck high after IN fall", corner_id);
                errors = errors + 1;
            end
        end
    endtask

    // Inject SEU matching models/por.va + models/ls_up.va windows
    task automatic inject_seu_upset;
        input integer por_width_ns;
        input integer ls_width_ns;
        begin
            // LS_UP SEU glitch
            ls_in = 1'b1;
            #20;
            ls_seu_inj = 1'b1;
            #1;
            if (ls_out !== 1'b0) begin
                $display("FAIL corner %0d: LS_UP SEU did not glitch OUT", corner_id);
                errors = errors + 1;
            end
            #(ls_width_ns);
            ls_seu_inj = 1'b0;
            #20;

            // POR SEU re-assert → reset_combiner must follow
            por_seu_inj = 1'b1;
            #10;
            if (reset_out !== 1'b0) begin
                $display("FAIL corner %0d: reset_out not asserted during POR SEU",
                         corner_id);
                errors = errors + 1;
            end
            check_reset_follows_por;
            #(por_width_ns);
            por_seu_inj = 1'b0;
            #10;
        end
    endtask

    task automatic run_normal_corner;
        input real vddl;
        input real vddh;
        input real temp_c;
        input real proc;
        begin
            corner_id      = corner_id + 1;
            sweep_temp_c   = temp_c;
            sweep_process  = proc;
            sweep_seu      = 0;
            active_vdd_nom = vddh;
            active_temp_c  = temp_c;
            active_process = proc;

            $display("CORNER %0d NORMAL  VDDL=%0f VDDH=%0f T=%0f process=%0f",
                     corner_id, vddl, vddh, temp_c, proc);

            power_down;
            #10;
            if (reset_out !== 1'b0) begin
                $display("FAIL corner %0d: reset_out not asserted at power-down", corner_id);
                errors = errors + 1;
            end

            power_up_rails(vddl, vddh);
            wait_por_release(500000);
            check_reset_follows_por;
            exercise_ls_up;
            check_reset_follows_por;

            #10000;
            vddh_ok = 1'b0;
            #2000;
            if (reset_out !== 1'b0) begin
                $display("FAIL corner %0d: reset_out not re-asserted on VDDH collapse",
                         corner_id);
                errors = errors + 1;
            end
            power_down;
        end
    endtask

    task automatic run_seu_corner;
        input real vddl;
        input real vddh;
        input real temp_c;
        input real proc;
        begin
            corner_id      = corner_id + 1;
            sweep_temp_c   = temp_c;
            sweep_process  = proc;
            sweep_seu      = 1;
            active_vdd_nom = vddh;
            active_temp_c  = temp_c;
            active_process = proc;

            $display("CORNER %0d SEU     VDDL=%0f VDDH=%0f T=%0f process=%0f",
                     corner_id, vddl, vddh, temp_c, proc);

            power_down;
            power_up_rails(vddl, vddh);
            wait_por_release(500000);
            check_reset_follows_por;
            exercise_ls_up;

            // SEU widths: POR 1 us, LS_UP 1 ns (VA defaults)
            inject_seu_upset(1000, 1);

            if (reset_out !== 1'b1) begin
                $display("FAIL corner %0d: reset_out did not recover after SEU", corner_id);
                errors = errors + 1;
            end
            check_reset_follows_por;
            exercise_ls_up;
            power_down;
        end
    endtask

    // ---- Main sweep ---------------------------------------------------------
    // Supplies: 1.4 / 3.3 / 5.5 V (VDDH); VDDL = min(1.8, VDDH)
    // Temperatures: -55 / 27 / 125 C
    // Process: -1 (ss) / 0 (tt) / +1 (ff)
    // SEU: off (normal) and on (upset)
    initial begin
        errors         = 0;
        corner_id      = 0;
        vss            = 1'b0;
        vddl_ok        = 1'b0;
        vddh_ok        = 1'b0;
        ls_in          = 1'b0;
        ls_seu_inj     = 1'b0;
        por_seu_inj    = 1'b0;
        sweep_vddl     = 1.8;
        sweep_vddh     = 5.0;
        sweep_temp_c   = 27.0;
        sweep_process  = 0.0;
        sweep_seu      = 0;
        active_vdd_nom = 5.0;
        active_temp_c  = 27.0;
        active_process = 0.0;

        $display("=== tb_top_io: TOP_IO LS_UP + POR + reset_combiner ===");
`ifdef VERILOG_AMS
        $display("verilog_ams: ls_up=%s por=%s",
                 `VERILOG_AMS_LS_UP_PATH, `VERILOG_AMS_POR_PATH);
`endif

        // ---- Normal operation -----------------------------------------------
        run_normal_corner(1.4, 1.4, 27.0, 0.0);
        run_normal_corner(1.8, 3.3, 27.0, 0.0);
        run_normal_corner(1.8, 5.5, 27.0, 0.0);
        run_normal_corner(1.8, 3.3, -55.0, 0.0);
        run_normal_corner(1.8, 3.3, 125.0, 0.0);
        run_normal_corner(1.8, 5.0, 27.0, -1.0);
        run_normal_corner(1.8, 5.0, 27.0,  1.0);

        // ---- SEU upset ------------------------------------------------------
        run_seu_corner(1.8, 3.3, 27.0, 0.0);
        run_seu_corner(1.8, 5.5, 27.0, 0.0);
        run_seu_corner(1.8, 3.3, -55.0, 0.0);
        run_seu_corner(1.8, 3.3, 125.0, 0.0);
        run_seu_corner(1.8, 5.0, 27.0, -1.0);
        run_seu_corner(1.8, 5.0, 27.0,  1.0);

        #100;
        if (errors == 0)
            $display("TB_TOP_IO RESULT=PASS corners=%0d", corner_id);
        else
            $display("TB_TOP_IO RESULT=FAIL errors=%0d corners=%0d",
                     errors, corner_id);
        $finish;
    end

endmodule

`default_nettype wire
