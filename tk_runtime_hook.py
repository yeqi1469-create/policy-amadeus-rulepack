import os
import sys

if getattr(sys, "frozen", False):
    bundle = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    os.environ["TCL_LIBRARY"] = os.path.join(bundle, "tcl", "tcl8.6")
    os.environ["TK_LIBRARY"] = os.path.join(bundle, "tcl", "tk8.6")
