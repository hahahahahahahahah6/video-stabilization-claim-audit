"""Offline documentation and AST evidence audit. Never imports audited code."""
import argparse
import ast
import json
import os
from pathlib import Path
import re
import sys

from . import __version__
from .phrases import VIDEOSTABILIZATION, NOVIDEOSTABILIZATION, GENERIC_NAMES


def normalize(text):
    return re.sub(r'\s+', ' ', text.lower().replace("n't", ' not').replace('-', ' ')).strip()


def matches(text, phrases):
    found = []
    for phrase in sorted(phrases, key=lambda p: (-len(p), p)):
        pattern = r'\b' + re.escape(phrase) + r'\b'
        if re.search(pattern, text):
            found.append(phrase)
            text = re.sub(pattern, lambda m: ' ' * len(m.group()), text)
    return found, text


def doc_claims(text):
    lines = []
    fence = None
    for line in text.splitlines():
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            continue
        if marker:
            fence = marker[1]
            continue
        lines.append(line)
    positive, negative = [], []
    for paragraph in re.split(r'\n\s*\n', '\n'.join(lines)):
        denials, rest = matches(normalize(paragraph), NOVIDEOSTABILIZATION)
        claims, _ = matches(rest, VIDEOSTABILIZATION)
        positive.extend(claims)
        negative.extend(denials)
    return positive, negative


def source_evidence(text):
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return False
    nodes = list(ast.walk(tree))
    shadow = {n.name for n in nodes if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    imports = {}
    gates = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports[alias.asname or alias.name.split('.')[0]] = alias.name if alias.asname else alias.name.split('.')[0]
                gates.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            gates.add(node.module.split('.')[0])
            for alias in node.names:
                imports[alias.asname or alias.name] = node.module + '.' + alias.name

    def resolve(node):
        if isinstance(node, ast.Name):
            if node.id in shadow:
                return ''
            return imports.get(node.id, node.id)
        if isinstance(node, ast.Attribute):
            if node.attr in shadow:
                return ''
            base = resolve(node.value)
            return base + '.' + node.attr if base else ''
        return ''

    def constructor(node):
        if not isinstance(node, ast.Call):
            return None
        name = resolve(node.func)
        last = name.split('.')[-1]
        if 'cv2' in gates and name in ('cv2.videostab.OnePassStabilizer', 'cv2.videostab.TwoPassStabilizer'):
            return 'cv2'
        for gate, target in (('vidstab', 'VidStab'), ('stabilo', 'Stabilizer')):
            if gate in gates and last == target:
                return gate
        return None

    bindings = {}
    for node in nodes:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for part in ast.walk(target):
                    if isinstance(part, ast.Name):
                        bindings.setdefault(part.id, []).append(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            bindings.setdefault(node.target.id, []).append(node.value)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars:
                    for part in ast.walk(item.optional_vars):
                        if isinstance(part, ast.Name):
                            bindings.setdefault(part.id, []).append(item.context_expr)
    calls = [n for n in nodes if isinstance(n, ast.Call)]
    parts = set()
    manual = ({'goodFeaturesToTrack', 'SIFT_create', 'ORB_create', 'AKAZE_create', 'BRISK_create'},
              {'calcOpticalFlowPyrLK'}, {'estimateAffinePartial2D', 'estimateAffine2D'}, {'warpAffine'})
    for call in calls:
        name = resolve(call.func)
        last = name.split('.')[-1]
        if last in GENERIC_NAMES and last not in shadow:
            if isinstance(call.func, ast.Attribute) or (isinstance(call.func, ast.Name) and call.func.id in imports):
                return True
        if 'cv2' in gates and name.startswith('cv2.') and name.count('.') == 1:
            for i, names in enumerate(manual):
                if last in names:
                    parts.add(i)
        if isinstance(call.func, ast.Attribute) and call.func.attr not in shadow:
            base = call.func.value
            routes = [constructor(base)]
            if isinstance(base, ast.Name) and base.id not in shadow:
                values = bindings.get(base.id, [])
                # Ambiguous/rebound receivers do not establish a route.
                routes = [constructor(v) for v in values]
                if not routes or None in routes or len(set(routes)) != 1:
                    routes = []
            for route in routes:
                if (route == 'cv2' and call.func.attr == 'nextFrame' or
                    route == 'vidstab' and call.func.attr in ('stabilize', 'stabilize_frame') or
                    route == 'stabilo' and call.func.attr == 'stabilize'):
                    return True
    return len(parts) == 4


def audit(root, ignore=()):
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise OSError('Repository must be an existing, readable directory')
    prefixes = [p.replace('\\', '/').removeprefix('./').rstrip('/') for p in ignore]

    def ignored(rel):
        return any(rel == p or rel.startswith(p + '/') for p in prefixes)

    claims, denials, production, tests = [], [], [], []
    def walk_error(error):
        raise error
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        dirs[:] = sorted(d for d in dirs if not (Path(directory)/d).is_symlink() and not ignored((Path(directory)/d).relative_to(root).as_posix()))
        for filename in sorted(files):
            path = Path(directory)/filename
            rel = path.relative_to(root)
            if path.is_symlink() or ignored(rel.as_posix()):
                continue
            if (rel.as_posix() == 'README.md' or 'docs' in rel.parts) and path.suffix == '.md':
                pos, neg = doc_claims(path.read_text(encoding='utf-8'))
                claims.extend({'path': rel.as_posix(), 'phrase': p} for p in pos)
                denials.extend({'path': rel.as_posix(), 'phrase': p} for p in neg)
            if path.suffix == '.py' and not {'fixtures', 'docs', 'examples'}.intersection(rel.parts):
                if source_evidence(path.read_text(encoding='utf-8')):
                    target = tests if 'tests' in rel.parts or filename.startswith('test_') or filename.endswith('_test.py') else production
                    target.append(rel.as_posix())
    findings = []
    if claims and not production:
        severity = 'MEDIUM' if tests else 'HIGH'
        findings.append({'id': 'documented-video-stabilization-claim-false', 'severity': severity,
                         'message': 'Evidence exists only in tests.' if tests else 'No production evidence supports the documented claim.', 'claims': claims})
    if denials and production:
        findings.append({'id': 'documented-no-video-stabilization-claim-false', 'severity': 'HIGH',
                         'message': 'Production evidence contradicts the documented denial.', 'claims': denials})
    return {'verdict': 'FAIL' if findings else 'PASS', 'findings': findings,
            'evidence': {'production': production, 'tests': tests}}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def main(argv=None):
    parser = Parser(description='Audit documentation claims against local source evidence.')
    parser.add_argument('--version', action='version', version=__version__)
    sub = parser.add_subparsers(dest='command', required=True, parser_class=Parser)
    command = sub.add_parser('audit')
    command.add_argument('repo', nargs='?', default='.')
    command.add_argument('--json', action='store_true')
    command.add_argument('--verbose', action='store_true')
    command.add_argument('--ignore', action='append', default=[], metavar='PREFIX')
    command.add_argument('--fail-on', choices=('high', 'medium'), default='high')
    try:
        args = parser.parse_args(argv)
        result = audit(args.repo, args.ignore)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(result['verdict'])
            for finding in result['findings']:
                print('{severity} {id}: {message}'.format(**finding))
            if args.verbose:
                print(json.dumps(result['evidence'], indent=2))
        return 2 if any(f['severity'] == 'HIGH' or args.fail_on == 'medium' for f in result['findings']) else 0
    except SystemExit as error:
        return error.code
    except (OSError, UnicodeError, ValueError) as error:
        print('error: ' + str(error), file=sys.stderr)
        return 1
