// Test: non-ANSI port style with separate declarations
module non_ansi_module (clk, din, dout);
    input        clk;
    input  [7:0] din;
    output [7:0] dout;

    wire [7:0] w1;
    reg  [7:0] r1;
    reg  [7:0] never_used;  // WARNING: declared but never referenced

    assign w1 = din;

    always @(posedge clk) begin
        r1 <= w1;
    end

    assign dout = r1;

endmodule
