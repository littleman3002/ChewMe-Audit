# Rust core (private)

The deterministic Rust core from the chewme tokenizer lab is kept as a
private library and is not part of this repo. It provides the fidelity
gate, collision handling, and lexical rules behind the byte-exact minify
used for the `pretty_printing` detector's "here's what minify would save
you" line.

The Python CLI in this repo does not need it: the audit runs entirely
in Python with no API keys. Nothing in the audit's findings depends on
the Rust core; the Python lexical minify in
`chewme_audit/detectors/pretty_print.py` is self-contained and
regression-tested (including the `[File: ...]` header case the old
shape check used to mangle).
