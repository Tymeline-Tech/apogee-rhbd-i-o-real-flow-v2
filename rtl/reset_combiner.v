// =============================================================================
// reset_combiner — digital reset glue for Apogee RHBD I/O (sky130 g5v0d10v5)
//
// Interfaces the POR Verilog-A model (active-low POR_N) with the digital domain.
// When a level shift is required, LS_UP brings the POR / soft-reset path into
// the core rail before this block; the combiner then selects the reset source
// for downstream logic.
//
// Analog counterpart intent (RST_COMB): RN = RESET_N & POR_N (active-low).
// This RTL stage exposes a clocked-domain port list (clk) while keeping a
// combinational async assert path matching POR SEU re-assert behavior.
//
// Ports:
//   clk       — digital domain clock (interface; unused in combo path)
//   reset_in  — active-low reset from POR (/ LS_UP), polarity matches POR_N
//   reset_out — active-low combined / selected reset to digital logic
// =============================================================================

`default_nettype none

module reset_combiner (
    // verilator lint_off UNUSED
    // synopsys translate_off
    // iverilog: clk is interface-only (async POR combinational path)
    // synopsys translate_on
    input  wire clk,
    // verilator lint_on UNUSED
    input  wire reset_in,
    output wire reset_out
);

    // -------------------------------------------------------------------------
    // Combinational reset-source selection
    //
    // Primary source: POR-derived active-low reset_in (from por.va POR_N,
    // optionally level-shifted by ls_up.va). Asserted (0) while POR holds or
    // during a POR SEU upset pulse; released (1) when VDD is above the POR
    // release threshold.
    //
    // Additional soft-reset sources can be AND-combined here (active-low) in
    // the same way as analog RST_COMB (NAND+INV). With a single digital input
    // the selected source is reset_in itself.
    // -------------------------------------------------------------------------
    assign reset_out = reset_in;

endmodule

`default_nettype wire
