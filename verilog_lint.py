#!/usr/bin/env python3
"""
Verilog signal warning checker.

Detects the following issues in Verilog modules:
  1. Signal reference without signal definition
  2. Defined but never referred signal
  3. assign statement when l-value is 'reg' signal
  4. assign operator (= or <=) in always/initial block when l-value is 'wire' signal
"""

import re
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class Signal:
	name: str
	kind: str   # 'wire' or 'reg'
	line: int


@dataclass
class Warning:
	line: int
	message: str


# Verilog reserved keywords – never treated as signal names
_KEYWORDS: Set[str] = {
	'module', 'endmodule', 'input', 'output', 'inout', 'wire', 'reg',
	'integer', 'real', 'time', 'realtime', 'parameter', 'localparam',
	'assign', 'always', 'initial', 'begin', 'end', 'if', 'else',
	'case', 'casex', 'casez', 'endcase', 'for', 'while', 'repeat',
	'forever', 'fork', 'join', 'posedge', 'negedge', 'or', 'and',
	'not', 'xor', 'nor', 'nand', 'xnor', 'buf', 'bufif0', 'bufif1',
	'notif0', 'notif1', 'defparam', 'task', 'endtask', 'function',
	'endfunction', 'generate', 'endgenerate', 'genvar', 'signed',
	'unsigned', 'supply0', 'supply1', 'tri', 'tri0', 'tri1', 'wand',
	'wor', 'trireg', 'disable', 'default', 'deassign', 'force',
	'release', 'wait',
}

# Matches a procedural assignment l-value:
#   <name> [optional_bit_select] (<= | =)
# The negative look-behind/ahead on '=' ensures we match only a plain '='
# and not '==', '<=', '>=', or '!=' operators.
_PROC_ASSIGN_RE = re.compile(
	r'\b(\w+)\b(?:\s*\[[^\]]*\])?\s*(?:<=|(?<![=<>!])=(?!=))'
)


def _strip_comments(text: str) -> str:
	"""Remove // and /* */ comments while preserving line numbers."""
	text = re.sub(
		r'/\*.*?\*/',
		lambda m: '\n' * m.group().count('\n'),
		text,
		flags=re.DOTALL,
	)
	text = re.sub(r'//[^\n]*', '', text)
	return text


def _strip_literals(text: str) -> str:
	"""Replace Verilog numeric literals with spaces to prevent false positives.

	Covers: 4'b0101  8'hFF  12'o77  16'd100  'b1  etc.
	The replacement preserves the original length to keep character positions
	(and therefore line numbers) intact.
	"""
	def _blank(m: re.Match) -> str:
		return ' ' * len(m.group())

	return re.sub(r"\d*'[bBoOdDhH][0-9a-fA-FxXzZ_]+", _blank, text)


def _line_of(text: str, pos: int) -> int:
	"""Return 1-based line number for the given character position."""
	return text[:pos].count('\n') + 1


def check_module(text: str) -> List[Warning]:
	"""
	Parse one Verilog module (or a file containing one module) and return
	a sorted list of warnings.
	"""
	warnings: List[Warning] = []
	text = _strip_comments(text)
	text = _strip_literals(text)

	# ------------------------------------------------------------------
	# 1. Collect port names
	#    Support both ANSI-style (comma-terminated in port list) and
	#    non-ANSI style (semicolon-terminated in the module body).
	# ------------------------------------------------------------------
	port_names: Set[str] = set()

	# ANSI style: "input/output/inout [wire|reg] [range] name" followed by , or )
	ansi_port_re = re.compile(
		r'\b(?:input|output|inout)\b'
		r'(?:\s+(?:wire|reg))?'
		r'(?:\s+(?:signed|unsigned))?'
		r'(?:\s*\[[^\]]*\])?'
		r'\s+(\w+)'
		r'\s*[,)]',
	)
	for m in ansi_port_re.finditer(text):
		name = m.group(1)
		if name not in _KEYWORDS:
			port_names.add(name)

	# Non-ANSI style: "input/output/inout [wire|reg] [range] name, ...;"
	non_ansi_port_re = re.compile(
		r'\b(?:input|output|inout)\b'
		r'(?:\s+(?:wire|reg))?'
		r'(?:\s+(?:signed|unsigned))?'
		r'(?:\s*\[[^\]]*\])?'
		r'([^;]*)'             # capture everything up to the semicolon
		r';',
		re.MULTILINE,
	)
	for m in non_ansi_port_re.finditer(text):
		for name in re.findall(r'\b([A-Za-z_]\w*)\b', m.group(1)):
			if name not in _KEYWORDS:
				port_names.add(name)

	# ------------------------------------------------------------------
	# 2. Collect internal signal declarations (wire / reg)
	#    Only signals NOT already identified as ports are tracked here.
	# ------------------------------------------------------------------
	internal_signals: Dict[str, Signal] = {}

	sig_decl_re = re.compile(
		r'\b(wire|reg)\b'
		r'(?:\s+(?:signed|unsigned))?'
		r'(?:\s*\[[^\]]*\])?'
		r'([^;]*)'             # capture everything up to the semicolon
		r';',
		re.MULTILINE,
	)
	for m in sig_decl_re.finditer(text):
		kind = m.group(1)
		line_no = _line_of(text, m.start())
		for name in re.findall(r'\b([A-Za-z_]\w*)\b', m.group(2)):
			if name not in _KEYWORDS and name not in port_names and name not in internal_signals:
				internal_signals[name] = Signal(name=name, kind=kind, line=line_no)

	# Track declaration line spans so we can skip them during reference counting
	decl_lines: Set[int] = set()
	for m in sig_decl_re.finditer(text):
		for ln in range(_line_of(text, m.start()), _line_of(text, m.end()) + 1):
			decl_lines.add(ln)
	for m in non_ansi_port_re.finditer(text):
		for ln in range(_line_of(text, m.start()), _line_of(text, m.end()) + 1):
			decl_lines.add(ln)

	# ------------------------------------------------------------------
	# 3. Collect parameter / localparam names (not signals, but legal refs)
	# ------------------------------------------------------------------
	param_names: Set[str] = set()
	for m in re.finditer(r'\b(?:parameter|localparam)\b\s+(?:\[[^\]]*\]\s+)?(\w+)', text):
		param_names.add(m.group(1))

	# All names that are legitimately defined
	all_known: Set[str] = set(port_names) | set(internal_signals) | param_names

	# Resolve the effective signal kind for any name (wire or reg)
	# For ports declared as "output reg" or in "output reg q;" — they are reg
	# We handle this by also looking for port-typed regs
	port_reg_names: Set[str] = set()
	for m in re.finditer(
		r'\b(?:output|input|inout)\s+reg\b'
		r'(?:\s+(?:signed|unsigned))?'
		r'(?:\s*\[[^\]]*\])?'
		r'\s*(\w+)',
		text,
	):
		port_reg_names.add(m.group(1))

	def _effective_kind(name: str) -> Optional[str]:
		"""Return 'wire' or 'reg' for a known signal name, or None."""
		if name in internal_signals:
			return internal_signals[name].kind
		if name in port_reg_names:
			return 'reg'
		# pure input/output/inout without explicit type is wire by default
		if name in port_names:
			return 'wire'
		return None

	# ------------------------------------------------------------------
	# 4. Warn: assign statement when l-value is a 'reg' signal
	# ------------------------------------------------------------------
	for m in re.finditer(r'\bassign\b\s+(\w+)', text, re.MULTILINE):
		name = m.group(1)
		line_no = _line_of(text, m.start())
		if _effective_kind(name) == 'reg':
			warnings.append(Warning(
				line=line_no,
				message=f"Signal '{name}' is declared as 'reg' but driven by 'assign' statement",
			))

	# ------------------------------------------------------------------
	# 5. Warn: procedural assignment to 'wire' inside always/initial blocks
	# ------------------------------------------------------------------
	block_keyword_re = re.compile(r'\b(always|initial)\b')
	# Positions of tokens that delimit end-of-block
	end_marker_positions = sorted(
		m.start() for m in re.finditer(
			r'\b(?:always|initial|assign|endmodule)\b', text
		)
	)

	for bm in block_keyword_re.finditer(text):
		bstart = bm.start()
		bkind = bm.group(1)
		nexts = [p for p in end_marker_positions if p > bstart]
		bend = nexts[0] if nexts else len(text)
		block_body = text[bstart:bend]

		# Match procedural assignment l-values: "name [optional_index] <= | ="
		for pm in _PROC_ASSIGN_RE.finditer(block_body):
			name = pm.group(1)
			if name in _KEYWORDS:
				continue
			abs_pos = bstart + pm.start()
			line_no = _line_of(text, abs_pos)
			if _effective_kind(name) == 'wire':
				warnings.append(Warning(
					line=line_no,
					message=(
						f"Signal '{name}' is declared as 'wire' but assigned "
						f"in '{bkind}' block"
					),
				))

	# ------------------------------------------------------------------
	# 6. Warn: signal reference without definition
	#    Scan the module body for identifiers not in any known set.
	# ------------------------------------------------------------------
	# Find body start (after module header's first ';')
	hm = re.search(r'\bmodule\b[^;]*;', text, re.DOTALL)
	body_start = hm.end() if hm else 0
	body_text = text[body_start:]
	body_offset = body_start

	undefined_seen: Set[str] = set()
	for m in re.finditer(r'\b([A-Za-z_]\w*)\b', body_text):
		name = m.group(1)
		if name in _KEYWORDS or name in all_known or name in undefined_seen:
			continue
		abs_pos = body_offset + m.start()
		line_no = _line_of(text, abs_pos)
		if line_no in decl_lines:
			continue
		undefined_seen.add(name)
		warnings.append(Warning(
			line=line_no,
			message=f"Signal '{name}' is referenced but not declared",
		))

	# ------------------------------------------------------------------
	# 7. Warn: internal signal declared but never referenced
	# ------------------------------------------------------------------
	ref_count: Dict[str, int] = {name: 0 for name in internal_signals}
	for m in re.finditer(r'\b([A-Za-z_]\w*)\b', body_text):
		name = m.group(1)
		if name not in ref_count:
			continue
		line_no = _line_of(text, body_offset + m.start())
		if line_no in decl_lines:
			continue
		ref_count[name] += 1

	for name, count in ref_count.items():
		if count == 0:
			sig = internal_signals[name]
			warnings.append(Warning(
				line=sig.line,
				message=f"Signal '{name}' is declared but never referenced",
			))

	warnings.sort(key=lambda w: w.line)
	return warnings


def check_file(path: str) -> List[Warning]:
	"""Read a Verilog file and return all warnings."""
	try:
		with open(path, encoding='utf-8') as fh:
			text = fh.read()
	except OSError as exc:
		print(f"Error reading {path}: {exc}", file=sys.stderr)
		return []
	return check_module(text)


def main() -> int:
	if len(sys.argv) < 2:
		print(f"Usage: {sys.argv[0]} <file.v> [file.v ...]", file=sys.stderr)
		return 1

	rc = 0
	for path in sys.argv[1:]:
		for w in check_file(path):
			print(f"{path}:{w.line}: warning: {w.message}")
			rc = 1
	return rc


if __name__ == '__main__':
	sys.exit(main())
