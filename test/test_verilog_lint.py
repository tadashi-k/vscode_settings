#!/usr/bin/env python3
"""
Tests for verilog_lint.py.

Run with: python3 test/test_verilog_lint.py
"""

import sys
import os
import unittest

# Allow importing from the parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from verilog_lint import check_module, Warning


class TestOkModule(unittest.TestCase):
	"""No warnings should be emitted for a correct module."""

	def test_no_warnings(self):
		code = """\
module ok (
    input        clk,
    input  [7:0] din,
    output [7:0] dout
);
    wire [7:0] w1;
    reg  [7:0] r1;

    assign w1 = din;

    always @(posedge clk) begin
        r1 <= din;
    end

    assign dout = w1 | r1;
endmodule
"""
		self.assertEqual(check_module(code), [])


class TestAssignToReg(unittest.TestCase):
	"""assign statement with a 'reg' l-value should produce a warning."""

	def test_assign_to_reg(self):
		code = """\
module m (input [7:0] din, output [7:0] dout);
    reg [7:0] r1;
    assign r1 = din;
    assign dout = r1;
endmodule
"""
		ws = check_module(code)
		msgs = [w.message for w in ws]
		self.assertTrue(
			any("'r1'" in m and "'reg'" in m and "'assign'" in m for m in msgs),
			f"Expected assign-to-reg warning, got: {msgs}",
		)

	def test_assign_to_wire_no_warning(self):
		code = """\
module m (input [7:0] din, output [7:0] dout);
    wire [7:0] w1;
    assign w1 = din;
    assign dout = w1;
endmodule
"""
		ws = check_module(code)
		msgs = [w.message for w in ws]
		self.assertFalse(
			any("'assign'" in m for m in msgs),
			f"Unexpected assign warning: {msgs}",
		)


class TestAlwaysToWire(unittest.TestCase):
	"""Procedural assignment to 'wire' in always/initial should produce a warning."""

	def test_always_nonblocking_to_wire(self):
		code = """\
module m (input clk, input [7:0] din, output [7:0] dout);
    wire [7:0] w1;
    reg  [7:0] r1;
    always @(posedge clk) begin
        w1 <= din;
    end
    assign dout = r1;
endmodule
"""
		ws = check_module(code)
		msgs = [w.message for w in ws]
		self.assertTrue(
			any("'w1'" in m and "'wire'" in m and "'always'" in m for m in msgs),
			f"Expected always-to-wire warning, got: {msgs}",
		)

	def test_always_blocking_to_wire(self):
		code = """\
module m (input clk, input [7:0] din, output [7:0] dout);
    wire [7:0] w1;
    reg  [7:0] r1;
    always @(posedge clk) begin
        w1 = din;
    end
    assign dout = r1;
endmodule
"""
		ws = check_module(code)
		msgs = [w.message for w in ws]
		self.assertTrue(
			any("'w1'" in m and "'wire'" in m and "'always'" in m for m in msgs),
			f"Expected always-to-wire (blocking) warning, got: {msgs}",
		)

	def test_initial_to_wire(self):
		code = """\
module m (output [7:0] dout);
    wire [7:0] w1;
    reg  [7:0] r1;
    initial begin
        w1 = 8'b0;
    end
    assign dout = r1;
endmodule
"""
		ws = check_module(code)
		msgs = [w.message for w in ws]
		self.assertTrue(
			any("'w1'" in m and "'wire'" in m and "'initial'" in m for m in msgs),
			f"Expected initial-to-wire warning, got: {msgs}",
		)

	def test_always_to_reg_no_warning(self):
		code = """\
module m (input clk, input [7:0] din, output [7:0] dout);
    reg [7:0] r1;
    always @(posedge clk) begin
        r1 <= din;
    end
    assign dout = r1;
endmodule
"""
		ws = check_module(code)
		msgs = [w.message for w in ws]
		self.assertFalse(
			any("'always'" in m for m in msgs),
			f"Unexpected always warning: {msgs}",
		)


class TestUndefinedSignal(unittest.TestCase):
	"""Reference to an undeclared signal should produce a warning."""

	def test_undefined_reference(self):
		code = """\
module m (output [7:0] dout);
    assign dout = no_such_signal;
endmodule
"""
		ws = check_module(code)
		msgs = [w.message for w in ws]
		self.assertTrue(
			any("'no_such_signal'" in m and "not declared" in m for m in msgs),
			f"Expected undefined-reference warning, got: {msgs}",
		)

	def test_defined_reference_no_warning(self):
		code = """\
module m (input [7:0] din, output [7:0] dout);
    wire [7:0] w1;
    assign w1  = din;
    assign dout = w1;
endmodule
"""
		ws = check_module(code)
		msgs = [w.message for w in ws]
		self.assertFalse(
			any("not declared" in m for m in msgs),
			f"Unexpected undefined-reference warning: {msgs}",
		)


class TestNeverReferenced(unittest.TestCase):
	"""A declared internal signal that is never used should produce a warning."""

	def test_unused_wire(self):
		code = """\
module m (input [7:0] din, output [7:0] dout);
    wire [7:0] unused_w;
    assign dout = din;
endmodule
"""
		ws = check_module(code)
		msgs = [w.message for w in ws]
		self.assertTrue(
			any("'unused_w'" in m and "never referenced" in m for m in msgs),
			f"Expected never-referenced warning, got: {msgs}",
		)

	def test_unused_reg(self):
		code = """\
module m (input [7:0] din, output [7:0] dout);
    reg [7:0] unused_r;
    assign dout = din;
endmodule
"""
		ws = check_module(code)
		msgs = [w.message for w in ws]
		self.assertTrue(
			any("'unused_r'" in m and "never referenced" in m for m in msgs),
			f"Expected never-referenced warning, got: {msgs}",
		)

	def test_used_signal_no_warning(self):
		code = """\
module m (input [7:0] din, output [7:0] dout);
    wire [7:0] w1;
    assign w1   = din;
    assign dout = w1;
endmodule
"""
		ws = check_module(code)
		msgs = [w.message for w in ws]
		self.assertFalse(
			any("never referenced" in m for m in msgs),
			f"Unexpected never-referenced warning: {msgs}",
		)


class TestNonAnsiPorts(unittest.TestCase):
	"""Port names declared in non-ANSI style should not trigger false positives."""

	def test_non_ansi_no_false_positives(self):
		code = """\
module m (clk, din, dout);
    input        clk;
    input  [7:0] din;
    output [7:0] dout;

    reg [7:0] r1;
    always @(posedge clk) begin
        r1 <= din;
    end
    assign dout = r1;
endmodule
"""
		ws = check_module(code)
		msgs = [w.message for w in ws]
		# clk / din / dout must not appear in any warning
		for port in ('clk', 'din', 'dout'):
			self.assertFalse(
				any(f"'{port}'" in m for m in msgs),
				f"False positive for port '{port}': {msgs}",
			)


if __name__ == '__main__':
	unittest.main()
