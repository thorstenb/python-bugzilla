
import commands
import difflib
import os
import shlex
import sys
import StringIO

from tests.scriptimports import bugzillascript

def diff(orig, new):
    """
    Return a unified diff string between the passed strings
    """
    return "".join(difflib.unified_diff(orig.splitlines(1),
                                        new.splitlines(1),
                                        fromfile="Orig",
                                        tofile="New"))
def difffile(expect, filename):
    expect += '\n'
    if not os.path.exists(filename) or os.getenv("__BUGZILLA_UNITTEST_REGEN"):
        file(filename, "w").write(expect)
    ret = diff(file(filename).read(), expect)
    if ret:
        raise AssertionError("Output was different:\n%s" % ret)

def clicomm(argv):
    """
    Run bin/bugzilla.main() directly with passed argv
    """
    argv = shlex.split(argv)

    oldstdout = sys.stdout
    oldstderr = sys.stderr
    oldstdin = sys.stdin
    oldargv = sys.argv
    try:
        out = StringIO.StringIO()
        sys.stdout = out
        sys.stderr = out
        sys.stdin = None
        sys.argv = argv

        ret = 0
        mainout = None
        try:
            print " ".join(argv)
            print

            mainout = bugzillascript.main()
        except SystemExit, sys_e:
            ret = sys_e.code

        outt = out.getvalue()
        if outt.endswith("\n"):
            outt = outt[:-1]

        if ret != 0:
            raise RuntimeError("Command failed with %d\ncmd=%s\nout=%s" %
                               (ret, argv, outt))
        return mainout
    finally:
        sys.stdout = oldstdout
        sys.stderr = oldstderr
        sys.stdin = oldstdin
        sys.argv = oldargv