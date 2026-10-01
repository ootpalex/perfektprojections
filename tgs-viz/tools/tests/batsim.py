"""Interpreter for the subset of cmd.exe batch syntax the legacy bats use.

Test tool only. It runs a legacy bat with no side effects: external commands
are recorded, not run, and their exit codes come from the scenario. The result
is a transcript of echo lines, commands (argv plus the STATSPLUS_COOKIE value),
prompts and pauses, and the bat's exit code.

Supported (DESIGN.md 14.1): @echo off, title, setlocal/endlocal, cd /d, echo,
echo., rem, ::, labels, goto, set "X=...", set X=..., set /a X+=1,
set /p X=prompt, %VAR% %~1 %% expansion, if [not] errorlevel N, if [not]
defined X, if [/i] [not] "a"=="b", if [not] exist "p" (...) else (...),
multi-line ( ... ) blocks, & chains inside blocks, pause, exit /b N, and the
external commands python and py -3.14.
"""
import re

# exit codes of 2**31 or more are negative numbers to cmd
def signed(code):
    code = int(code)
    if code >= 2 ** 31:
        return code - 2 ** 32
    return code


class BatExit(Exception):
    def __init__(self, code):
        self.code = code


class Truncated(Exception):
    pass


class Unclosed(Exception):
    pass


class Goto(Exception):
    def __init__(self, label):
        self.label = label


def read_lines(data):
    """Lines of a bat file; CRLF and LF both accepted."""
    if isinstance(data, bytes):
        data = data.decode("ascii")
    text = data.replace("\r\n", "\n")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def caret(text):
    """cmd's caret rule: outside double quotes, ^x prints x."""
    out = []
    inq = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '"':
            inq = not inq
            out.append(ch)
        elif ch == "^" and not inq and i + 1 < len(text):
            out.append(text[i + 1])
            i += 1
        elif ch == "^" and not inq:
            pass
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def split_args(s):
    """Split a command tail the way the C runtime builds argv (simple subset)."""
    args = []
    cur = []
    have = False
    inq = False
    for ch in s:
        if ch == '"':
            inq = not inq
            have = True
        elif ch in " \t" and not inq:
            if have:
                args.append("".join(cur))
                cur = []
                have = False
        else:
            cur.append(ch)
            have = True
    if have:
        args.append("".join(cur))
    return args


def _scan(text, i, stops):
    """Index of the first char in stops at or after i, outside quotes and not
    escaped by a caret; len(text) when none."""
    inq = False
    while i < len(text):
        ch = text[i]
        if ch == '"':
            inq = not inq
        elif not inq and ch == "^":
            i += 2
            continue
        elif not inq and ch in stops:
            return i
        i += 1
    return len(text)


def _match_paren(text, i):
    """text[i] == '('. Index of the matching ')'; -1 when the block is open."""
    depth = 0
    inq = False
    while i < len(text):
        ch = text[i]
        if ch == '"':
            inq = not inq
        elif not inq and ch == "^":
            i += 2
            continue
        elif not inq and ch == "(":
            depth += 1
        elif not inq and ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


class BatSim:
    """Runs one bat. Scenario inputs:
      args       positional arguments (%1 ...)
      env        starting environment (USERPROFILE ...)
      answers    {VAR: str or [str, ...]} for set /p, in order
      exit_for   function(argv, occurrence) -> exit code (unsigned int)
      exists     {path as written in the bat: bool}
      loop_label, max_cycles: stop with Truncated when the label is reached
                 for the (max_cycles + 1)th time
    """

    def __init__(self, data, args=(), env=None, answers=None, exit_for=None,
                 exists=None, loop_label=None, max_cycles=None, dp0="C:\\repo\\"):
        self.lines = read_lines(data)
        self.args = list(args)
        self.env = {k.upper(): v for k, v in (env or {}).items()}
        self.answers = {k.upper(): (list(v) if isinstance(v, (list, tuple)) else [v])
                        for k, v in (answers or {}).items()}
        self.exit_for = exit_for or (lambda argv, n: 0)
        self.exists = {k.lower(): bool(v) for k, v in (exists or {}).items()}
        self.loop_label = loop_label.lower() if loop_label else None
        self.max_cycles = max_cycles
        self.loop_hits = 0
        self.dp0 = dp0
        self.errorlevel = 0
        self.transcript = []
        self.counts = {}
        self.labels = {}
        for n, line in enumerate(self.lines):
            s = line.strip()
            if s.startswith(":") and not s.startswith("::"):
                self.labels[s[1:].split()[0].lower()] = n

    # ---- expansion
    def expand(self, text):
        out = []
        i = 0
        while i < len(text):
            ch = text[i]
            if ch != "%":
                out.append(ch)
                i += 1
                continue
            if text.startswith("%%", i):
                out.append("%")
                i += 2
                continue
            m = re.match(r"%~(dp)?([0-9])", text[i:])
            if m:
                if m.group(1):
                    out.append(self.dp0)
                else:
                    k = int(m.group(2))
                    v = self.args[k - 1] if 1 <= k <= len(self.args) else ""
                    out.append(v.strip('"'))
                i += m.end()
                continue
            m = re.match(r"%([0-9])", text[i:])
            if m:
                k = int(m.group(1))
                out.append(self.args[k - 1] if 1 <= k <= len(self.args) else "")
                i += m.end()
                continue
            j = text.find("%", i + 1)
            if j < 0:
                out.append(text[i:])
                break
            name = text[i + 1:j]
            if name.lower() == "errorlevel":
                out.append(str(signed(self.errorlevel)))
            else:
                out.append(self.env.get(name.upper(), ""))
            i = j + 1
        return "".join(out)

    # ---- program flow
    def run(self):
        """Returns {"transcript", "exit", "env"}. exit is None when truncated."""
        pc = 0
        code = None
        try:
            while pc < len(self.lines):
                text, pc = self._logical_line(pc)
                if text is None:
                    continue
                try:
                    self.exec_text(self.expand(text))
                except Goto as g:
                    pc = self._goto(g.label)
            code = self.errorlevel
        except BatExit as e:
            code = e.code
        except Truncated:
            code = None
        return {"transcript": self.transcript, "exit": code, "env": dict(self.env)}

    def _goto(self, label):
        label = label.lstrip(":").strip().lower()
        if label == "eof":
            raise BatExit(self.errorlevel)
        if label not in self.labels:
            raise RuntimeError(f"goto: no label {label}")
        n = self.labels[label]
        if label == self.loop_label:
            self._hit_loop()
        return n + 1

    def _hit_loop(self):
        self.loop_hits += 1
        if self.max_cycles is not None and self.loop_hits > self.max_cycles:
            raise Truncated()

    def _logical_line(self, pc):
        """(text or None, next pc). Joins lines while a ( block is open."""
        line = self.lines[pc]
        s = line.strip()
        if not s or s.startswith("::") or s.lower().startswith("rem ") or s.lower() == "rem":
            return None, pc + 1
        if s.startswith(":"):
            if self.loop_label and s[1:].split()[0].lower() == self.loop_label:
                self._hit_loop()
            return None, pc + 1
        text = line.lstrip()   # cmd keeps trailing spaces (set /p prompts, echo)
        pc += 1
        while True:
            try:
                self.parse_seq(text)
                break
            except Unclosed:
                if pc >= len(self.lines):
                    raise RuntimeError("unclosed ( block")
                text += "\n" + self.lines[pc].lstrip()
                pc += 1
        return text, pc

    # ---- command execution (text is already %-expanded)
    def exec_text(self, text):
        for cmd in self.parse_seq(text):
            self.exec_cmd(cmd)

    def parse_seq(self, text):
        """Split a block body into commands: newlines and & outside quotes."""
        cmds = []
        i = 0
        while i < len(text):
            while i < len(text) and text[i] in " \t\n&":
                i += 1
            if i >= len(text):
                break
            node, i = self.parse_cmd(text, i)
            if node is not None:
                cmds.append(node)
        return cmds

    def parse_cmd(self, text, i):
        """One command at text[i]. Returns (node, next index)."""
        while i < len(text) and text[i] in " \t":
            i += 1
        if text[i] == "(":
            j = _match_paren(text, i)
            if j < 0:
                raise Unclosed()
            return ("block", self.parse_seq(text[i + 1:j])), j + 1
        low = text[i:].lower()
        if low.startswith("if ") or low.startswith("if\t"):
            return self.parse_if(text, i + 3)
        j = _scan(text, i, "&\n")
        return ("simple", text[i:j]), j

    def parse_if(self, text, i):
        def skip_ws(k):
            while k < len(text) and text[k] in " \t":
                k += 1
            return k

        i = skip_ws(i)
        icase = False
        neg = False
        if text[i:i + 2].lower() == "/i" and text[i + 2:i + 3] in (" ", "\t"):
            icase = True
            i = skip_ws(i + 2)
        if text[i:i + 4].lower() == "not " or text[i:i + 4].lower() == "not\t":
            neg = True
            i = skip_ws(i + 4)
        low = text[i:].lower()
        if low.startswith("errorlevel "):
            i = skip_ws(i + len("errorlevel "))
            m = re.match(r"-?\d+", text[i:])
            cond = ("errorlevel", int(m.group(0)))
            i += m.end()
        elif low.startswith("defined "):
            i = skip_ws(i + len("defined "))
            m = re.match(r"[^\s]+", text[i:])
            cond = ("defined", m.group(0))
            i += m.end()
        elif low.startswith("exist "):
            i = skip_ws(i + len("exist "))
            tok, i = self._token(text, i)
            cond = ("exist", tok)
        else:
            left, i = self._token(text, i, stop_eq=True)
            if text[i:i + 2] != "==":
                raise RuntimeError("if: expected == in: " + text)
            i += 2
            right, i = self._token(text, i)
            cond = ("eq", left, right, icase)
        i = skip_ws(i)
        then, i = self.parse_cmd(text, i)
        k = skip_ws(i)
        els = None
        if text[k:k + 5].lower() == "else " or text[k:k + 5].lower() == "else(" or text[k:k + 4].lower() == "else" and k + 4 == len(text):
            k = skip_ws(k + 4)
            els, i = self.parse_cmd(text, k)
        return ("if", cond, neg, then, els), i

    @staticmethod
    def _token(text, i, stop_eq=False):
        """A possibly quoted token; quotes kept (cmd compares them as written)."""
        start = i
        inq = False
        while i < len(text):
            ch = text[i]
            if ch == '"':
                inq = not inq
            elif not inq and ch in " \t\n":
                break
            elif not inq and stop_eq and text.startswith("==", i):
                break
            i += 1
        return text[start:i], i

    def eval_cond(self, cond):
        kind = cond[0]
        if kind == "errorlevel":
            return signed(self.errorlevel) >= cond[1]
        if kind == "defined":
            return cond[1].upper() in self.env
        if kind == "exist":
            p = cond[1].strip('"')
            if p.lower() not in self.exists:
                raise RuntimeError(f"if exist: scenario has no answer for {p}")
            return self.exists[p.lower()]
        if kind == "eq":
            a, b, icase = cond[1], cond[2], cond[3]
            return a.lower() == b.lower() if icase else a == b
        raise RuntimeError(kind)

    def exec_cmd(self, node):
        kind = node[0]
        if kind == "block":
            for n in node[1]:
                self.exec_cmd(n)
            return
        if kind == "if":
            _, cond, neg, then, els = node
            ok = self.eval_cond(cond)
            if neg:
                ok = not ok
            if ok:
                self.exec_cmd(then)
            elif els is not None:
                self.exec_cmd(els)
            return
        self.exec_simple(node[1])

    def exec_simple(self, s):
        if not s:
            return
        if s.startswith("@"):
            s = s[1:]
        low = s.lower()
        word = low.split(None, 1)[0] if low.split() else ""
        if low.startswith("echo.") and len(s) == 5:
            self.transcript.append(("echo", ""))
            return
        if word == "echo":
            rest = s[5:] if len(s) > 4 else ""
            if rest.strip().lower() in ("off", "on") and s[4:5] == " ":
                return
            self.transcript.append(("echo", caret(rest)))
            return
        if word in ("title", "setlocal", "endlocal", "rem", "cls"):
            return
        if word == "cd":
            return
        if word == "goto":
            raise Goto(s.split(None, 1)[1].strip())
        if word == "pause":
            self.transcript.append(("pause",))
            return
        if word == "exit":
            m = re.match(r"exit\s+/b\s*(-?\d+)?", s, re.I)
            raise BatExit(int(m.group(1)) if m and m.group(1) else self.errorlevel)
        if word == "set":
            self.exec_set(s[3:].lstrip())
            return
        if word in ("python", "py"):
            self.exec_external(s)
            return
        raise RuntimeError("batsim: unsupported command: " + s)

    def exec_set(self, s):
        if s[:2].lower() == "/a":
            m = re.match(r"/a\s+(\w+)\s*\+=\s*(\d+)", s, re.I)
            name = m.group(1).upper()
            self.env[name] = str(int(self.env.get(name, "0") or "0") + int(m.group(2)))
            return
        if s[:2].lower() == "/p":
            body = s[2:].lstrip()
            name, _, prompt = body.partition("=")
            self.transcript.append(("prompt", prompt))
            queue = self.answers.get(name.upper())
            if not queue:
                raise RuntimeError(f"set /p: scenario has no answer for {name}")
            value = queue.pop(0)
            if value != "":
                self.env[name.upper()] = value
            return
        if s.startswith('"'):
            end = s.rfind('"')
            body = s[1:end]
        else:
            body = s
        name, _, value = body.partition("=")
        if value == "":
            self.env.pop(name.upper(), None)
        else:
            self.env[name.upper()] = value

    def exec_external(self, s):
        if s.lower().startswith("py "):
            parts = split_args(s)
            argv = parts
        else:
            argv = split_args(s)
        key = tuple(argv)
        n = self.counts.get(key, 0)
        self.counts[key] = n + 1
        code = int(self.exit_for(argv, n))
        self.transcript.append(("cmd", tuple(argv), self.env.get("STATSPLUS_COOKIE")))
        self.errorlevel = code


def run_bat(data, **kw):
    return BatSim(data, **kw).run()


def echo_lines(data, start, end):
    """Echo text of lines start..end (1-based, inclusive) after the caret rule,
    with %VAR% left as written. Used to port bat text."""
    out = []
    for line in read_lines(data)[start - 1:end]:
        s = line.strip()
        low = s.lower()
        if low == "echo.":
            out.append("")
        elif low.startswith("echo "):
            out.append(caret(s[5:]))
    return out
