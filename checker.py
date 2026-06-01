"""C/C++ Code Checker - static analysis with clang-tidy + cppcheck, generates HTML report."""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import webbrowser
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(SCRIPT_DIR, "download")

# Issue category keywords mapping
CATEGORY_PATTERNS = {
    "内存泄漏": [
        r"memory leak", r"leak", r"new\b.*\bnot freed", r"malloc.*not freed",
        r"memory.*not released", r"resource leak", r"owning memory",
        r"owning-memory"
    ],
    "空指针": [
        r"null pointer", r"dereference.*null", r"nullptr", r"NULL",
        r"address of.*null", r"possible null"
    ],
    "缓冲区溢出": [
        r"buffer overflow", r"buffer.*overrun", r"buffer.*overflow",
        r"array index.*overflow", r"out[- ]of[- ]bounds", r"buffer access out of bounds"
    ],
    "未初始化变量": [
        r"uninitializ", r"uninit", r"not initialized", r"may be used uninitialized",
        r"without initialization", r"garbage value"
    ],
    "资源泄漏": [
        r"resource leak", r"file descriptor leak", r"fd leak", r"handle leak",
        r"not closed", r"not freed", r"fopen.*not closed", r"owning memory",
        r"owning-memory"
    ],
    "类型安全": [
        r"type.*mismatch", r"implicit conversion", r"narrowing conversion",
        r"signed.*unsigned", r"integer conversion", r"cast", r"type.*cast",
        r"loss of precision", r"truncat"
    ],
    "代码风格": [
        r"style", r"naming", r"indent", r"whitespace", r"brace",
        r"readability", r"redundant", r"unused", r"modernize",
        r"magic number", r"too many", r"too long"
    ],
    "未定义行为": [
        r"undefined behavior", r"undefined behaviour", r"UB",
        r"invalid.*shift", r"signed.*overflow", r"sequence point",
        r"strict aliasing", r"implementation defined",
        r"garbage value", r"undefined binary operator"
    ],
    "逻辑错误": [
        r"logical", r"logic error", r"dead code", r"unreachable",
        r"always (true|false)", r"never.*executed", r"identical.*condition",
        r"same expression", r"incorrect logic"
    ],
}

def find_tool(name):
    """Find a tool executable - check download dir first, then common install locations, then PATH."""
    # Check download dir
    tool_dir = os.path.join(DOWNLOAD_DIR, name)
    exe = os.path.join(tool_dir, f"{name}.exe")
    if os.path.exists(exe):
        return exe
    
    # Check llvm/bin for clang-tidy
    if name == "clang-tidy":
        alt = os.path.join(DOWNLOAD_DIR, "llvm", "bin", f"{name}.exe")
        if os.path.exists(alt):
            return alt
    
    # Check common Windows install locations
    common_dirs = [
        os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), name),
        os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), name),
        os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "LLVM", "bin"),
        os.path.join(os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"), "LLVM", "bin"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", name),
    ]
    for d in common_dirs:
        candidate = os.path.join(d, f"{name}.exe")
        if os.path.exists(candidate):
            return candidate
    
    # Check PATH
    import shutil
    path_result = shutil.which(name)
    if path_result:
        return path_result
    
    return None

def discover_files(paths):
    """Discover C/C++ files from input paths (files or directories)."""
    c_extensions = {'.c', '.cpp', '.cc', '.cxx', '.h', '.hpp', '.hxx', '.hh'}
    files = []
    
    for p in paths:
        path = Path(p)
        if not path.exists():
            print(f"Warning: {p} does not exist, skipping.")
            continue
        
        if path.is_file():
            if path.suffix.lower() in c_extensions:
                files.append(str(path.resolve()))
            else:
                print(f"Warning: {p} is not a C/C++ file, skipping.")
        elif path.is_dir():
            for root, dirs, filenames in os.walk(path):
                # Skip hidden dirs and common non-source dirs
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', 'build', 'cmake-build-debug', 'cmake-build-release', 'Debug', 'Release', '__pycache__')]
                for f in filenames:
                    if Path(f).suffix.lower() in c_extensions:
                        files.append(os.path.join(root, f))
    
    return sorted(set(files))

def run_cppcheck(file_path):
    """Run cppcheck and return list of issues."""
    cppcheck_exe = find_tool("cppcheck")
    if not cppcheck_exe:
        print("Warning: cppcheck not found, skipping.")
        return []
    
    try:
        result = subprocess.run(
            [cppcheck_exe, "--enable=all", "--inconclusive", "--xml", 
             "--suppress=missingIncludeSystem", "--suppress=unmatchedSuppression",
             "--error-exitcode=0", file_path],
            capture_output=True, text=True, timeout=120
        )
        return parse_cppcheck_xml(result.stderr + result.stdout)
    except subprocess.TimeoutExpired:
        print(f"Warning: cppcheck timed out for {file_path}")
        return []
    except Exception as e:
        print(f"Warning: cppcheck failed for {file_path}: {e}")
        return []

def parse_cppcheck_xml(text):
    """Parse cppcheck XML output (version 2 format)."""
    issues = []
    # Try XML parsing first
    import xml.etree.ElementTree as ET
    
    # Find XML content (cppcheck output may contain non-XML lines)
    xml_match = re.search(r'<\?xml.*?</results>', text, re.DOTALL)
    if not xml_match:
        # Try to find just <results>...</results>
        xml_match = re.search(r'<results.*?</results>', text, re.DOTALL)
    
    if xml_match:
        xml_text = xml_match.group(0)
        try:
            root = ET.fromstring(xml_text)
            for error in root.iter('error'):
                eid = error.get('id', '')
                # Skip informational meta-entries (not real code issues)
                if eid in ('checkersReport',):
                    continue
                # Extract line/file from first <location> child (cppcheck v2 format)
                loc = error.find('location')
                line = loc.get('line', '0') if loc is not None else '0'
                file_ = loc.get('file', error.get('file0', '')) if loc is not None else error.get('file0', '')
                issue = {
                    'tool': 'cppcheck',
                    'severity': error.get('severity', 'warning'),
                    'message': error.get('msg', error.get('verbose', '')),
                    'file': file_,
                    'line': line,
                    'id': eid,
                }
                # Also get verbose message if available
                verbose = error.get('verbose')
                if verbose and verbose != issue['message']:
                    issue['message'] = f"{issue['message']} ({verbose})"
                issues.append(issue)
        except ET.ParseError as e:
            print(f"Warning: Failed to parse cppcheck XML: {e}")
    
    # Fallback: parse text output
    if not issues and ('error' in text.lower() or 'warning' in text.lower()):
        for line in text.split('\n'):
            line = line.strip()
            if not line:
                continue
            # Pattern: [file:line]: (severity) message
            match = re.match(r'\[([^:]+):(\d+)\]:\s*\((\w+)\)\s*(.+)', line)
            if match:
                issues.append({
                    'tool': 'cppcheck',
                    'severity': match.group(3),
                    'message': match.group(4).strip(),
                    'file': match.group(1),
                    'line': match.group(2),
                    'id': '',
                })
    
    return issues

def run_clang_tidy(file_path):
    """Run clang-tidy and return list of issues."""
    clang_tidy_exe = find_tool("clang-tidy")
    if not clang_tidy_exe:
        print("Warning: clang-tidy not found, skipping.")
        return []
    
    ext = Path(file_path).suffix.lower()
    if ext in ('.c', '.h'):
        # For C files, try to use a compile_commands.json or just basic checks
        checks = ("-checks=-*,bugprone-*,clang-analyzer-*,cert-*,misc-*,"
                  "performance-*,portability-*,readability-*")
    else:
        checks = ("-checks=-*,bugprone-*,clang-analyzer-*,cert-*,cppcoreguidelines-*,"
                  "misc-*,modernize-*,performance-*,portability-*,readability-*")
    
    try:
        cmd = [
            clang_tidy_exe,
            checks,
            '--extra-arg=-Wno-everything',
            file_path,
            '--'
        ]
        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=120
        )
        return parse_clang_tidy_output(result.stdout + result.stderr, file_path)
    except subprocess.TimeoutExpired:
        print(f"Warning: clang-tidy timed out for {file_path}")
        return []
    except Exception as e:
        print(f"Warning: clang-tidy failed for {file_path}: {e}")
        return []

def parse_clang_tidy_output(text, file_path):
    """Parse clang-tidy text output."""
    issues = []
    # Pattern: file:line:col: severity: message [check-name]
    pattern = re.compile(
        r'(.+?):(\d+):(\d+):\s*(warning|error|note):\s*(.+?)\s*\[([^\]]+)\]'
    )
    
    for line in text.split('\n'):
        match = pattern.search(line)
        if match:
            fname = match.group(1)
            # Only include issues for our target file
            if os.path.basename(fname) != os.path.basename(file_path) and fname != file_path:
                # Also accept if it's the full path
                if not os.path.samefile(fname, file_path) if os.path.exists(fname) else True:
                    continue
            
            severity = match.group(4)
            if severity == 'note':
                continue  # Notes are usually supplementary
            
            issues.append({
                'tool': 'clang-tidy',
                'severity': severity,
                'message': match.group(5).strip(),
                'file': fname,
                'line': match.group(2),
                'id': match.group(6).strip(),
            })
    
    return issues

def categorize_issue(issue):
    """Categorize an issue based on its message."""
    message = issue.get('message', '')
    check_id = issue.get('id', '')
    combined = f"{message} {check_id}".lower()
    
    for category, patterns in CATEGORY_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, combined, re.IGNORECASE):
                return category
    
    return "其他"

def escape_html(text):
    """Escape HTML special characters."""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

def get_source_line(file_path, line_no):
    """Read a specific line from a source file."""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            for i, line in enumerate(f, 1):
                if i == line_no:
                    return line.rstrip('\n\r')
    except Exception:
        pass
    return ''

def normalize_severity(severity):
    """Normalize severity to error/warning/style."""
    s = severity.lower().strip()
    if s in ('error', 'fatal', 'critical'):
        return 'error'
    elif s in ('warning', 'warn'):
        return 'warning'
    elif s in ('style', 'note', 'performance', 'portability'):
        return 'style'
    return 'warning'

def calculate_score(issues):
    """Calculate score from issues."""
    deductions = {'error': 3, 'warning': 2, 'style': 1}
    score = 100
    for issue in issues:
        sev = normalize_severity(issue.get('severity', 'warning'))
        score -= deductions.get(sev, 2)
    return max(0, score)

def check_tools_available():
    """Check if at least one analysis tool is available. Returns (has_tool, message)."""
    cppcheck = find_tool("cppcheck")
    clang_tidy = find_tool("clang-tidy")
    
    available = []
    missing = []
    if cppcheck:
        available.append(f"cppcheck ({cppcheck})")
    else:
        missing.append("cppcheck")
    if clang_tidy:
        available.append(f"clang-tidy ({clang_tidy})")
    else:
        missing.append("clang-tidy")
    
    if not available:
        msg = "No analysis tools found! Run setup.py first:\n  python setup.py"
        return False, msg
    
    msg = f"Tools: {', '.join(available)}"
    if missing:
        msg += f" | Missing: {', '.join(missing)}"
    return True, msg

# Source-level pattern scan to detect code patterns that static analyzers may miss
SOURCE_PATTERNS = [
    # Null pointer dereference: ptr = nullptr; ... *ptr = ... (clang-analyzer may miss simple paths)
    {
        "name": "null-pointer-dereference",
        "pattern": r'(\w+)\s*=\s*nullptr\s*;.*?\*?\b\1\b\s*=\s*[^=]',
        "message": "Potential null pointer dereference: variable '{var}' assigned nullptr then dereferenced",
        "category": "空指针",
        "severity": "error",
    },
    # Use-after-free: delete ptr; ... *ptr ...
    {
        "name": "use-after-free",
        "pattern": r'delete\s+(\w+)\s*;.*?\*?\1',
        "message": "Potential use-after-free: variable '{var}' used after delete",
        "category": "内存泄漏",
        "severity": "error",
    },
    # Divisor may be zero: x / y where y assigned 0
    {
        "name": "divide-by-zero",
        "pattern": r'(\w+)\s*=\s*0\s*;.*?/\s*\1[^.]',
        "message": "Potential divide-by-zero: variable '{var}' is zero before division",
        "category": "逻辑错误",
        "severity": "error",
    },
]

def scan_source_patterns(file_path):
    """Scan source file for common risky patterns that static analyzers may miss."""
    issues = []
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        lines = content.split('\n')
    except Exception:
        return issues
    
    for rule in SOURCE_PATTERNS:
        for match in re.finditer(rule["pattern"], content, re.DOTALL):
            var_name = match.group(1) if match.lastindex and match.lastindex >= 1 else "?"
            # Find line number
            line_no = content[:match.start()].count('\n') + 1
            msg = rule["message"].replace("{var}", var_name)
            issues.append({
                'tool': 'pattern-scan',
                'severity': rule["severity"],
                'message': msg,
                'file': file_path,
                'line': str(line_no),
                'id': rule["name"],
                'category': rule["category"],
            })
    
    return issues

def check_whitespace(file_path):
    """Check source file for whitespace/indentation issues.

    Catches:
      - Trailing whitespace on non-empty lines
      - Lines starting with whitespace when code is expected (leading space before text)
      - Inconsistent indentation (uses majority-vote to detect dominant indent width)
      - Empty lines that contain only whitespace
      - Missing newline at end of file
    """
    issues = []
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        lines = content.split('\n')
        has_trailing_newline = content.endswith('\n')
    except Exception:
        return issues

    # Detect dominant indentation style from code lines
    indent_counts = {}
    for line in lines:
        stripped = line.rstrip('\r')
        if not stripped.strip():
            continue  # skip blank/whitespace-only lines
        lead = len(stripped) - len(stripped.lstrip(' '))
        if lead > 0:
            indent_counts[lead] = indent_counts.get(lead, 0) + 1

    # Dominant indent = most common non-zero indent width (or 4 as default)
    dominant_indent = 4
    if indent_counts:
        dominant_indent = max(indent_counts, key=indent_counts.get)

    for i, line in enumerate(lines):
        lineno = i + 1
        stripped = line.rstrip('\r')
        content_stripped = stripped.strip()

        # Skip completely empty lines (but flag whitespace-only lines)
        if not content_stripped:
            if stripped and (stripped != stripped.rstrip()):
                issues.append({
                    'tool': 'whitespace',
                    'severity': 'style',
                    'message': 'Line contains only whitespace characters',
                    'file': file_path,
                    'line': str(lineno),
                    'id': 'trailing-whitespace-empty',
                    'category': '代码风格',
                })
            continue

        # Trailing whitespace on non-empty lines
        if stripped != stripped.rstrip():
            issues.append({
                'tool': 'whitespace',
                'severity': 'style',
                'message': 'Trailing whitespace',
                'file': file_path,
                'line': str(lineno),
                'id': 'trailing-whitespace',
                'category': '代码风格',
            })

        # Leading whitespace: check if line starts with space when content has text
        # (catches " // comment" vs "// comment" — extra space before first non-space char)
        if stripped.startswith(' ') and content_stripped:
            lead_spaces = len(stripped) - len(stripped.lstrip(' '))
            # Flag if first non-whitespace char is preceded by a stray space
            # (e.g., " ▸// comment" has 1 space then //, while "    //" has 4 spaces — normal indent)
            first_char = content_stripped[0]
            # Check if there's an extra space between indent and content
            # The content should start at a multiple of the dominant indent
            if lead_spaces > 0:
                # Only flag if it looks like an extra stray leading space:
                # content on this line starts with // or /* (comment) preceded by non-standard indent,
                # or any line where the leading space count doesn't match a multiple of dominant indent
                remainder = lead_spaces % dominant_indent
                if remainder != 0:
                    issues.append({
                        'tool': 'whitespace',
                        'severity': 'style',
                        'message': f'Inconsistent indentation: {lead_spaces} spaces (expected multiple of {dominant_indent})',
                        'file': file_path,
                        'line': str(lineno),
                        'id': 'inconsistent-indent',
                        'category': '代码风格',
                    })

    # Missing newline at end of file
    if lines and lines[-1] != '' and content:
        issues.append({
            'tool': 'whitespace',
            'severity': 'style',
            'message': 'Missing newline at end of file',
            'file': file_path,
            'line': str(len(lines)),
            'id': 'missing-eof-newline',
            'category': '代码风格',
        })

    return issues

def escape_html(text):
    """Escape HTML special characters."""
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

def get_source_line(file_path, line_no):
    """Read a specific line from a source file."""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            for i, line in enumerate(f, 1):
                if i == line_no:
                    return line.rstrip('\n\r')
    except Exception:
        pass
    return ''

def collect_issues(file_paths):
    """Run tools on all files and collect issues."""
    all_issues = []
    
    for fp in file_paths:
        print(f"  Checking: {fp}")
        issues = run_cppcheck(fp) + run_clang_tidy(fp) + scan_source_patterns(fp) + check_whitespace(fp)
        
        # Deduplicate (same line + similar message)
        seen = set()
        unique = []
        for issue in issues:
            key = (issue['file'], issue['line'], issue['message'][:80], issue['tool'])
            if key not in seen:
                seen.add(key)
                unique.append(issue)
        
        # Categorize and normalize severity
        for issue in unique:
            issue['category'] = categorize_issue(issue)
            issue['severity'] = normalize_severity(issue.get('severity', 'warning'))
            # Boost severity for critical categories to error level
            if issue['category'] in ('内存泄漏', '空指针', '缓冲区溢出', '未初始化变量'):
                issue['severity'] = 'error'
            # Reclassify cppcheck "style" issues that are actually correctness problems
            if issue['tool'] == 'cppcheck' and issue['severity'] == 'style':
                dead_code_ids = ('unreadVariable', 'unusedVariable', 'unusedAllocatedMemory',
                                 'unusedFunction', 'unusedStructMember', 'unusedLabel')
                if issue.get('id', '') in dead_code_ids:
                    issue['severity'] = 'warning'
        
        all_issues.extend(unique)
        print(f"    Found {len(unique)} issues")
    
    return all_issues

def generate_json_result(file_paths, issues, score):
    """Generate JSON result for a set of files."""
    # Group by category
    by_category = defaultdict(list)
    by_severity = defaultdict(list)
    
    for issue in issues:
        by_category[issue['category']].append(issue)
        by_severity[issue['severity']].append(issue)
    
    result = {
        'files': file_paths,
        'timestamp': datetime.now(timezone(timedelta(hours=8))).isoformat(),
        'summary': {
            'total_files': len(file_paths),
            'total_issues': len(issues),
            'score': score,
            'by_severity': {
                'error': len(by_severity.get('error', [])),
                'warning': len(by_severity.get('warning', [])),
                'style': len(by_severity.get('style', [])),
            },
        },
        'issues': issues,
    }
    return result

def generate_html(results, output_path, mode='single'):
    """Generate HTML report from results."""
    timestamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S CST")
    
    if mode == 'single':
        return generate_single_html(results, output_path, timestamp)
    elif mode == 'compare':
        return generate_compare_html(results, output_path, timestamp)

def generate_single_html(result, output_path, timestamp):
    """Generate single-file HTML report."""
    issues = result['issues']
    score = result['summary']['score']
    by_category = defaultdict(list)
    by_severity = defaultdict(list)
    for issue in issues:
        by_category[issue['category']].append(issue)
        by_severity[issue['severity']].append(issue)
    
    sev_counts = result['summary']['by_severity']
    
    # Score color
    if score >= 90:
        score_color = "#27ae60"
        score_badge = "优秀"
    elif score >= 70:
        score_color = "#f39c12"
        score_badge = "一般"
    else:
        score_color = "#e74c3c"
        score_badge = "较差"
    
    # Build category detail sections
    category_sections = ""
    for cat in ["内存泄漏", "空指针", "缓冲区溢出", "未初始化变量", "资源泄漏", 
                "类型安全", "代码风格", "未定义行为", "逻辑错误", "其他"]:
        cat_issues = by_category.get(cat, [])
        if cat_issues:
            category_sections += f"""
            <div class="category-section">
                <h3>{cat} <span class="count">{len(cat_issues)}</span></h3>
                <table>
                    <thead><tr><th>严重度</th><th>文件</th><th>行</th><th>源代码</th><th>工具</th><th>问题描述</th></tr></thead>
                    <tbody>
            """
            for issue in sorted(cat_issues, key=lambda x: {'error':0,'warning':1,'style':2}.get(x.get('severity','warning'), 1)):
                sev_class = issue.get('severity', 'warning')
                src_line = get_source_line(issue.get('file', ''), int(issue.get('line', 0)))
                src_html = escape_html(src_line) if src_line else ''
                category_sections += f"""
                        <tr class="sev-{sev_class}">
                            <td><span class="badge badge-{sev_class}">{sev_class.upper()}</span></td>
                            <td class="file-cell">{os.path.basename(issue.get('file', ''))}</td>
                            <td>{issue.get('line', '')}</td>
                            <td class="source-cell"><code>{src_html}</code></td>
                            <td>{issue.get('tool', '')}</td>
                            <td>{issue.get('message', '')} <code class="check-id">{issue.get('id', '')}</code></td>
                        </tr>"""
            category_sections += """
                    </tbody>
                </table>
            </div>"""
    
    # Build issues table
    issues_table = ""
    for issue in issues:
        sev_class = issue.get('severity', 'warning')
        src_line = get_source_line(issue.get('file', ''), int(issue.get('line', 0)))
        src_html = escape_html(src_line) if src_line else ''
        issues_table += f"""
            <tr class="sev-{sev_class}">
                <td><span class="badge badge-{sev_class}">{issue['severity'].upper()}</span></td>
                <td>{issue['category']}</td>
                <td class="file-cell">{os.path.basename(issue.get('file', ''))}</td>
                <td>{issue.get('line', '')}</td>
                <td class="source-cell"><code>{src_html}</code></td>
                <td>{issue.get('tool', '')}</td>
                <td>{issue.get('message', '')} <code class="check-id">{issue.get('id', '')}</code></td>
            </tr>"""
    
    files_list = ", ".join(os.path.basename(f) for f in result.get('files', []))
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>C/C++ Code Checker Report - {files_list}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #f5f6fa; color: #2c3e50; line-height: 1.6; }}
.container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
.header {{ background: linear-gradient(135deg, #2c3e50, #3498db); color: white; padding: 40px; border-radius: 12px; margin-bottom: 24px; text-align: center; }}
.header h1 {{ font-size: 28px; margin-bottom: 8px; }}
.header .subtitle {{ opacity: 0.85; font-size: 14px; }}
.summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
.card {{ background: white; border-radius: 10px; padding: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); text-align: center; }}
.card .value {{ font-size: 36px; font-weight: 700; }}
.card .label {{ color: #7f8c8d; font-size: 13px; margin-top: 4px; text-transform: uppercase; letter-spacing: 1px; }}
.card.error .value {{ color: #e74c3c; }}
.card.warning .value {{ color: #f39c12; }}
.card.style .value {{ color: #3498db; }}
.card.score .value {{ color: {score_color}; font-size: 48px; }}
.score-badge {{ display: inline-block; background: {score_color}; color: white; padding: 4px 16px; border-radius: 20px; font-size: 14px; margin-top: 8px; }}
.section {{ background: white; border-radius: 10px; padding: 24px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
.section h2 {{ font-size: 20px; margin-bottom: 16px; color: #2c3e50; border-bottom: 2px solid #ecf0f1; padding-bottom: 8px; }}
table {{ width: 100%; border-collapse: collapse; }}
th {{ background: #f8f9fa; padding: 12px; text-align: left; font-size: 13px; text-transform: uppercase; letter-spacing: 0.5px; color: #7f8c8d; border-bottom: 2px solid #dee2e6; }}
td {{ padding: 10px 12px; border-bottom: 1px solid #ecf0f1; font-size: 14px; }}
tr:hover {{ background: #f8f9fa; }}
.badge {{ display: inline-block; padding: 2px 10px; border-radius: 4px; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; }}
.badge-error {{ background: #fde8e8; color: #c0392b; }}
.badge-warning {{ background: #fef3e2; color: #e67e22; }}
.badge-style {{ background: #e8f4fd; color: #2980b9; }}
.sev-error {{ border-left: 3px solid #e74c3c; }}
.sev-warning {{ border-left: 3px solid #f39c12; }}
.sev-style {{ border-left: 3px solid #3498db; }}
.check-id {{ font-size: 11px; color: #95a5a6; margin-left: 8px; }}
.file-cell {{ font-family: 'Consolas', 'Courier New', monospace; font-size: 13px; }}
.category-section {{ margin-bottom: 24px; }}
.category-section h3 {{ font-size: 16px; margin-bottom: 8px; color: #34495e; }}
.count {{ background: #ecf0f1; padding: 2px 10px; border-radius: 12px; font-size: 13px; margin-left: 8px; }}
.footer {{ text-align: center; color: #95a5a6; font-size: 12px; margin-top: 24px; padding: 16px; }}
</style>
</head>
<body>
<div class="container">
<div class="header">
    <h1>C/C++ Code Checker Report</h1>
    <div class="subtitle">Generated: {timestamp} | Files: {files_list}</div>
</div>

<div class="summary">
    <div class="card score">
        <div class="value">{score}</div>
        <div class="label">得分 / 100</div>
        <div class="score-badge">{score_badge}</div>
    </div>
    <div class="card error">
        <div class="value">{sev_counts.get('error', 0)}</div>
        <div class="label">Error</div>
    </div>
    <div class="card warning">
        <div class="value">{sev_counts.get('warning', 0)}</div>
        <div class="label">Warning</div>
    </div>
    <div class="card style">
        <div class="value">{sev_counts.get('style', 0)}</div>
        <div class="label">Style</div>
    </div>
</div>

<div class="section">
    <h2>按分类查看</h2>
    {category_sections}
</div>

<div class="section">
    <h2>全部问题列表 ({len(issues)})</h2>
    <table>
        <thead>
            <tr><th>严重度</th><th>分类</th><th>文件</th><th>行</th><th>源代码</th><th>工具</th><th>问题描述</th></tr>
        </thead>
        <tbody>
            {issues_table}
        </tbody>
    </table>
</div>

<div class="footer">
    C/C++ Code Checker | Powered by cppcheck + clang-tidy
</div>
</div>
</body>
</html>"""
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    return output_path

def generate_compare_html(results, output_path, name1="File 1", name2="File 2", timestamp=""):
    """Generate comparison HTML report for two groups."""
    # results is a dict with 'file1', 'file2' keys, each containing result dict
    r1 = results['file1']
    r2 = results['file2']
    
    s1 = r1['summary']['score']
    s2 = r2['summary']['score']
    
    # Use provided names, fallback to first file basename
    if name1 == "File 1" and r1['files']:
        name1 = os.path.basename(r1['files'][0])
    if name2 == "File 2" and r2['files']:
        name2 = os.path.basename(r2['files'][0])
    
    def score_color(s):
        if s >= 90: return "#27ae60", "优秀"
        elif s >= 70: return "#f39c12", "一般"
        else: return "#e74c3c", "较差"
    
    c1, b1 = score_color(s1)
    c2, b2 = score_color(s2)
    
    # Better file
    if s1 > s2:
        winner = f"<strong>{name1}</strong> 得分更高 (+{s1 - s2}分)"
    elif s2 > s1:
        winner = f"<strong>{name2}</strong> 得分更高 (+{s2 - s1}分)"
    else:
        winner = "两者得分相同"
    
    # Build per-category stats for unified comparison table
    all_categories = [
        "内存泄漏", "空指针", "缓冲区溢出", "未初始化变量", "资源泄漏",
        "类型安全", "代码风格", "未定义行为", "逻辑错误", "其他"
    ]
    
    def calc_category_stats(issues):
        """Calculate per-category error/warning/style counts."""
        stats = {}
        for cat in all_categories:
            stats[cat] = {"error": 0, "warning": 0, "style": 0}
        for issue in issues:
            cat = issue.get("category", "其他")
            sev = issue.get("severity", "warning")
            if cat in stats:
                stats[cat][sev] = stats[cat].get(sev, 0) + 1
            else:
                stats["其他"][sev] += 1
        return stats
    
    stats1 = calc_category_stats(r1['issues'])
    stats2 = calc_category_stats(r2['issues'])
    
    # Total
    totals1 = {"error": 0, "warning": 0, "style": 0}
    totals2 = {"error": 0, "warning": 0, "style": 0}
    for cat_stats in stats1.values():
        for k in totals1:
            totals1[k] += cat_stats[k]
    for cat_stats in stats2.values():
        for k in totals2:
            totals2[k] += cat_stats[k]
    
    def max_if_greater(a, b):
        """Return (a, 'higher') if a > b, else (b, 'higher') if b > a, else (a, '')."""
        if a > b:
            return a, True
        elif b > a:
            return b, False
        return a, None
    
    def build_comparison_row(cat, s1, s2):
        """Build one row of the comparison table.
        Column order: cat, file1.error, file1.warning, file1.style, file2.error, file2.warning, file2.style
        """
        cells = ""
        # Output file1's three columns, then file2's three columns
        for sev in ("error", "warning", "style"):
            v1 = s1[sev]
            v2 = s2[sev]
            _, higher = max_if_greater(v1, v2)
            if higher is True:
                cells += f'<td class="compare-higher">{v1}</td>'
            else:
                cells += f'<td>{v1}</td>'
        for sev in ("error", "warning", "style"):
            v1 = s1[sev]
            v2 = s2[sev]
            _, higher = max_if_greater(v1, v2)
            if higher is False:
                cells += f'<td class="compare-higher">{v2}</td>'
            else:
                cells += f'<td>{v2}</td>'
        return f"<tr><td class='cat-name'>{cat}</td>{cells}</tr>"
    
    comparison_rows = ""
    for cat in all_categories:
        comparison_rows += build_comparison_row(cat, stats1[cat], stats2[cat])
    
    totals_row = build_comparison_row("<strong>合计</strong>", totals1, totals2)
    
    # Build issue tables for each file
    def build_issue_table(issues):
        rows = ""
        for issue in issues:
            sev = issue.get('severity', 'warning')
            src_line = get_source_line(issue.get('file', ''), int(issue.get('line', 0)))
            src_html = escape_html(src_line) if src_line else ''
            rows += f"""
            <tr class="sev-{sev}">
                <td><span class="badge badge-{sev}">{sev.upper()}</span></td>
                <td>{issue['category']}</td>
                <td>{issue.get('line', '')}</td>
                <td class="source-cell"><code>{src_html}</code></td>
                <td>{issue.get('tool', '')}</td>
                <td>{issue.get('message', '')} <code class="check-id">{issue.get('id', '')}</code></td>
            </tr>"""
        return rows
    
    # AI analysis placeholder
    ai_analysis = results.get('ai_analysis', '')
    ai_section = ""
    if ai_analysis:
        ai_section = f"""
        <div class="section ai-analysis">
            <h2>AI 对比分析</h2>
            <div class="ai-content">{ai_analysis.replace(chr(10), '<br>')}</div>
        </div>"""
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>C/C++ Code Checker - Compare: {name1} vs {name2}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #f5f6fa; color: #2c3e50; line-height: 1.6; }}
.container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
.header {{ background: linear-gradient(135deg, #8e44ad, #3498db); color: white; padding: 40px; border-radius: 12px; margin-bottom: 24px; text-align: center; }}
.header h1 {{ font-size: 28px; margin-bottom: 8px; }}
.header .subtitle {{ opacity: 0.85; font-size: 14px; }}
.compare-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }}
.compare-card {{ background: white; border-radius: 10px; padding: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
.compare-card h2 {{ font-size: 18px; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 2px solid #ecf0f1; }}
.big-score {{ font-size: 64px; font-weight: 700; text-align: center; margin: 16px 0; }}
.mini-stats {{ display: flex; justify-content: center; gap: 20px; margin-top: 8px; }}
.mini-stat {{ text-align: center; }}
.mini-stat .num {{ font-size: 20px; font-weight: 600; }}
.mini-stat .lbl {{ font-size: 11px; color: #7f8c8d; text-transform: uppercase; }}
.winner-banner {{ background: #2ecc71; color: white; text-align: center; padding: 16px; border-radius: 10px; margin-bottom: 20px; font-size: 16px; }}
.section {{ background: white; border-radius: 10px; padding: 24px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
.section h2 {{ font-size: 20px; margin-bottom: 16px; color: #2c3e50; border-bottom: 2px solid #ecf0f1; padding-bottom: 8px; }}
table {{ width: 100%; border-collapse: collapse; }}
th {{ background: #f8f9fa; padding: 10px; text-align: left; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; color: #7f8c8d; border-bottom: 2px solid #dee2e6; }}
td {{ padding: 8px 10px; border-bottom: 1px solid #ecf0f1; font-size: 13px; }}
tr:hover {{ background: #f8f9fa; }}
.badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: 600; }}
.badge-error {{ background: #fde8e8; color: #c0392b; }}
.badge-warning {{ background: #fef3e2; color: #e67e22; }}
.badge-style {{ background: #e8f4fd; color: #2980b9; }}
.sev-error {{ border-left: 3px solid #e74c3c; }}
.sev-warning {{ border-left: 3px solid #f39c12; }}
.sev-style {{ border-left: 3px solid #3498db; }}
.check-id {{ font-size: 10px; color: #95a5a6; margin-left: 6px; }}
.ai-analysis {{ background: linear-gradient(135deg, #f8f9fa, #e8f4fd); }}
.ai-content {{ white-space: pre-wrap; font-size: 14px; line-height: 1.8; }}
.badge-better {{ background: #2ecc71; color: white; padding: 2px 10px; border-radius: 4px; font-size: 10px; margin-left: 8px; }}
.compare-table th.header-1 {{ background: #e8f0fe; color: #2980b9; font-weight: 700; }}
.compare-table th.header-2 {{ background: #f0e6f6; color: #8e44ad; font-weight: 700; }}
.compare-table th.col-error {{ color: #e74c3c; }}
.compare-table th.col-warning {{ color: #f39c12; }}
.compare-table th.col-style {{ color: #3498db; }}
.compare-table .compare-higher {{ background: #ffe0e0; font-weight: 700; }}
.compare-table .cat-name {{ font-weight: 600; text-align: left; }}
.compare-table .totals-row td {{ border-top: 2px solid #2c3e50; font-weight: 700; background: #f8f9fa; }}
.compare-table .totals-row .compare-higher {{ background: #ffcccc; }}
.footer {{ text-align: center; color: #95a5a6; font-size: 12px; margin-top: 24px; padding: 16px; }}
</style>
</head>
<body>
<div class="container">
<div class="header">
    <h1>Code Checker - Comparison Report</h1>
    <div class="subtitle">Generated: {timestamp}</div>
</div>

<div class="winner-banner">
    🏆 {winner}
</div>

<div class="compare-grid">
    <div class="compare-card">
        <h2>{name1}</h2>
        <div class="big-score" style="color: {c1}">{s1}</div>
        <div class="mini-stats">
            <div class="mini-stat"><div class="num" style="color:#e74c3c">{r1['summary']['by_severity'].get('error',0)}</div><div class="lbl">Error</div></div>
            <div class="mini-stat"><div class="num" style="color:#f39c12">{r1['summary']['by_severity'].get('warning',0)}</div><div class="lbl">Warning</div></div>
            <div class="mini-stat"><div class="num" style="color:#3498db">{r1['summary']['by_severity'].get('style',0)}</div><div class="lbl">Style</div></div>
        </div>
    </div>
    <div class="compare-card">
        <h2>{name2}</h2>
        <div class="big-score" style="color: {c2}">{s2}</div>
        <div class="mini-stats">
            <div class="mini-stat"><div class="num" style="color:#e74c3c">{r2['summary']['by_severity'].get('error',0)}</div><div class="lbl">Error</div></div>
            <div class="mini-stat"><div class="num" style="color:#f39c12">{r2['summary']['by_severity'].get('warning',0)}</div><div class="lbl">Warning</div></div>
            <div class="mini-stat"><div class="num" style="color:#3498db">{r2['summary']['by_severity'].get('style',0)}</div><div class="lbl">Style</div></div>
        </div>
    </div>
</div>

{ai_section}

<div class="section">
    <h2>维度对比表</h2>
    <table class="compare-table">
        <thead>
            <tr>
                <th rowspan="2" style="vertical-align:middle;">维度</th>
                <th colspan="3" class="header-1">{name1}</th>
                <th colspan="3" class="header-2">{name2}</th>
            </tr>
            <tr>
                <th class="col-error">Error</th><th class="col-warning">Warning</th><th class="col-style">Style</th>
                <th class="col-error">Error</th><th class="col-warning">Warning</th><th class="col-style">Style</th>
            </tr>
        </thead>
        <tbody>
            {comparison_rows}
            <tr class="totals-row">{totals_row.replace('<tr>','').replace('</tr>','')}</tr>
        </tbody>
    </table>
</div>

<div class="compare-grid">
    <div class="compare-card">
        <h2>{name1} - 问题列表 ({r1['summary']['total_issues']})</h2>
        <table>
            <thead><tr><th>严重度</th><th>分类</th><th>行</th><th>源代码</th><th>工具</th><th>问题描述</th></tr></thead>
            <tbody>{build_issue_table(r1['issues'])}</tbody>
        </table>
    </div>
    <div class="compare-card">
        <h2>{name2} - 问题列表 ({r2['summary']['total_issues']})</h2>
        <table>
            <thead><tr><th>严重度</th><th>分类</th><th>行</th><th>源代码</th><th>工具</th><th>问题描述</th></tr></thead>
            <tbody>{build_issue_table(r2['issues'])}</tbody>
        </table>
    </div>
</div>

<div class="footer">
    C/C++ Code Checker | Powered by cppcheck + clang-tidy
</div>
</div>
</body>
</html>"""
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    return output_path

def main():
    parser = argparse.ArgumentParser(
        description="C/C++ Code Checker - Static analysis with clang-tidy + cppcheck",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python checker.py file.cpp              # Single file check
  python checker.py a.cpp b.cpp           # Compare two files
  python checker.py src/                  # Directory batch check
  python checker.py --output report.html file.cpp  # Custom output path
        """
    )
    parser.add_argument('paths', nargs='+', help='C/C++ files or directories to check')
    parser.add_argument('--output', '-o', help='Output HTML file path')
    parser.add_argument('--json', help='Output JSON result file path')
    parser.add_argument('--no-browser', action='store_true', help='Do not open browser')
    
    args = parser.parse_args()
    
    # Discover files - support comparing two directories
    if len(args.paths) == 2:
        files1 = discover_files([args.paths[0]])
        files2 = discover_files([args.paths[1]])
        
        if not files1 and not files2:
            print("No C/C++ files found!")
            return 1
        
        mode = 'compare'
        print(f"\nComparing:")
        print(f"  Path 1 ({args.paths[0]}): {len(files1)} file(s)")
        print(f"  Path 2 ({args.paths[1]}): {len(files2)} file(s)")
        print()
    else:
        file_paths = discover_files(args.paths)
        
        if not file_paths:
            print("No C/C++ files found!")
            return 1
        
        print(f"\nFound {len(file_paths)} file(s) to check:")
        for f in file_paths:
            print(f"  - {f}")
        print()
        
        mode = 'single'
    
    has_tools, tool_msg = check_tools_available()
    print(f"\n{tool_msg}\n")
    
    if mode == 'compare':
        # Check each group separately
        issues1 = collect_issues(files1)
        issues2 = collect_issues(files2)
        
        score1 = calculate_score(issues1)
        score2 = calculate_score(issues2)
        
        result1 = generate_json_result(files1, issues1, score1)
        result2 = generate_json_result(files2, issues2, score2)
        
        results = {
            'file1': result1,
            'file2': result2,
            'ai_analysis': '',
        }
        
        # Save JSON for AI analysis
        json_path = args.json or 'code_check_results.json'
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\nJSON results saved to: {json_path}")
        print("AI analysis step: Read this JSON and provide comparison analysis.")
        
        # Generate HTML
        output_path = args.output or 'code_check_report_compare.html'
        cmp_name1 = os.path.basename(args.paths[0].rstrip('/\\'))
        cmp_name2 = os.path.basename(args.paths[1].rstrip('/\\'))
        generate_compare_html(results, output_path,
                              name1=cmp_name1,
                              name2=cmp_name2,
            timestamp=datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S CST"))
        
    else:
        # Single or batch mode
        issues = collect_issues(file_paths)
        score = calculate_score(issues)
        result = generate_json_result(file_paths, issues, score)
        
        # Save JSON
        json_path = args.json
        if json_path:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"\nJSON results saved to: {json_path}")
        
        # Generate HTML
        output_path = args.output or 'code_check_report.html'
        generate_single_html(result, output_path, timestamp=datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S CST"))
    
    print(f"\nHTML report saved to: {output_path}")
    
    # Open in browser
    if not args.no_browser:
        abs_path = os.path.abspath(output_path)
        webbrowser.open(f'file:///{abs_path}')
        print(f"Report opened in browser.")
    
    # Print summary
    if mode == 'compare':
        print(f"\n{'='*60}")
        print(f"Comparison Summary:")
        print(f"  {cmp_name1}: Score {score1}/100 ({len(issues1)} issues)")
        print(f"  {cmp_name2}: Score {score2}/100 ({len(issues2)} issues)")
        print(f"{'='*60}")
    else:
        print(f"\n{'='*60}")
        print(f"Total: {len(issues)} issues | Score: {score}/100")
        sev_counts = result['summary']['by_severity']
        print(f"  Error: {sev_counts.get('error', 0)} | Warning: {sev_counts.get('warning', 0)} | Style: {sev_counts.get('style', 0)}")
        print(f"{'='*60}")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())