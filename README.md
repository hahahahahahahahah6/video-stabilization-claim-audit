# Documentation claim auditor

An offline auditor comparing documentation about the checked capability with
static evidence in Python source. It never executes the inspected code, accesses
the network, or writes files. Requires Python 3.9 or later; no runtime dependencies.

## Install and run

```sh
python3 -m pip install .
video-stabilization-claim-audit --version
video-stabilization-claim-audit audit /path/to/repo
python3 -m video_stabilization_claim_audit audit . --json --verbose
video-stabilization-claim-audit audit . --fail-on medium --ignore vendor --ignore build
```

The audit subcommand defaults to the current directory. Each ignore option takes
one relative path prefix, matching a path or its descendants. The default failure
threshold is high; medium also fails on evidence found only in tests. Exit 0 means
no findings meet the threshold, exit 2 means findings meet it, and exit 1 means
usage or I/O failure. JSON contains verdict, findings, and evidence fields;
findings include id, severity, message, and matched claims. A FAIL verdict may
still exit 0 when all findings fall below the threshold. Verbose text output
includes evidence paths. Version output is 0.1.0.

## Scope and rules

Only root README.md and Markdown files with a docs path component are checked.
Backtick and tilde fences with up to three leading spaces are excluded; inline
code counts. Paragraph text is lowercased, contractions expanded, hyphens replaced
with spaces, and whitespace collapsed. Exact word-boundary matches are processed
longest first, alphabetically on ties. Denial spans are removed first.

Source files are parsed with the AST module. Symlinks are excluded. Files in
fixtures, docs, or examples supply no evidence. Test directories and test filenames
supply separate evidence. Invalid syntax supplies none. Recognized paired calls
and the four-part manual pipeline must occur within one module. Imports, aliases,
local definitions, assignments, annotated assignments, and context bindings are
considered. Bare imports, strings, comments, references without calls, and
unrelated operations supply none.

```text
Evidence routes:
cv2.videostab.OnePassStabilizer / TwoPassStabilizer + nextFrame
vidstab.VidStab + stabilize / stabilize_frame
stabilo.Stabilizer + stabilize
cv2 feature detector + calcOpticalFlowPyrLK + affine estimation + warpAffine
24 generic operation names, including stabilize_video and remove_jitter

Findings:
documented-video-stabilization-claim-false HIGH (or MEDIUM for test-only evidence)
documented-no-video-stabilization-claim-false HIGH
```

An affirmative claim without production evidence produces a finding, including
when no source exists. A denial only produces a finding when production evidence
exists. Each family produces at most one finding.

## Differentiation

Image stitching joins photos into a panorama. Optical flow estimates motion
vectors. Image denoising removes noise. Video generation creates new content.
Super resolution increases spatial resolution. These adjacent operations alone
do not establish the checked capability.

## Honest limitations

Exact phrases can refer to OIS hardware, frame-rate interpolation, or tripod
footage rather than the checked operation. A short term may also name an ffmpeg
filter. These ambiguities can produce false positives. Generic calls can be
wrappers around external binaries, audio timing correction, or timestamp smoothing;
their names do not prove semantics. Local wrappers shadowing route names are
excluded, but an imported wrapper can still count.

A manual implementation using only affine estimation and warping is missed:
all four parts, including feature detection and optical flow, are required in one
module. External ffmpeg filters (vidstabdetect / vidstabtransform), Gyroflow, and
other subprocess tools are excluded. Boolean configuration flags alone are
excluded, including this example:

```python
VideoGear(source, stabilize=True)
```

Static pattern matching cannot judge semantics. Dead code counts. Unsupported
alias chains may be missed. Only listed phrases count; denial handling depends
on the fixed denial list. Each pair or pipeline must sit in one module.

## Development

```sh
python3 -m unittest discover
python3 -m build
```

The source distribution includes the test suite. MIT licensed.
