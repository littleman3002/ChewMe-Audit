# Rust core (optional)

The deterministic Rust core from the chewme tokenizer lab lives outside
this repo. It provides the fidelity gate, collision handling, and
lexical rules behind the byte-exact minify used for the
`pretty_printing` detector's "here's what minify would save you" line.

The Python CLI in this repo does not need it: the audit runs entirely
in Python with no API keys. If you want the Rust core's byte-exact
guarantees in your own pipeline, it is a separate open-source
component — see the lab repo.

Nothing in the audit's findings depends on the Rust core; the Python
lexical minify in `chewme_audit/detectors/pretty_print.py` is
self-contained and regression-tested (including the `[File: ...]`
header case the old shape check used to mangle).
