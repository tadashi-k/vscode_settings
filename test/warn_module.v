// Test: all four warning types
module warn_module (
    input        clk,
    input  [7:0] din,
    output [7:0] dout
);
    wire [7:0] w1;         // used wire
    reg  [7:0] r1;         // used reg
    wire [7:0] unused_w;   // WARNING: declared but never referenced
    reg  [7:0] unused_r;   // WARNING: declared but never referenced

    // OK: continuous assignment to wire
    assign w1 = din;

    // WARNING: continuous assignment l-value is 'reg'
    assign r1 = din;

    // OK: procedural assignment to reg
    always @(posedge clk) begin
        r1 <= din;
    end

    // WARNING: procedural assignment l-value is 'wire' (in always)
    always @(posedge clk) begin
        w1 <= din;
    end

    // WARNING: procedural assignment l-value is 'wire' (in initial)
    initial begin
        w1 = 8'b0;
    end

    // WARNING: undefined signal reference
    assign dout = no_such_signal;

endmodule
