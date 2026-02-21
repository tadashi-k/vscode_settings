// Test: signal with no issues (expect NO warnings)
module ok_module (
    input        clk,
    input        rst,
    input  [7:0] din,
    output [7:0] dout
);
    wire [7:0] w1;
    reg  [7:0] r1;

    assign w1 = din;

    always @(posedge clk or posedge rst) begin
        if (rst)
            r1 <= 8'b0;
        else
            r1 <= din;
    end

    assign dout = w1 | r1;

endmodule
