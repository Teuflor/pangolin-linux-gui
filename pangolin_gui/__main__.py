"""Entry point: `python3 -m pangolin_gui [--hidden] [--debug]`."""
from __future__ import annotations

import argparse
import logging
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pangolin-gui", description="Pangolin tray client for Linux")
    parser.add_argument("--hidden", action="store_true", help="start in the tray without opening a window")
    parser.add_argument("--debug", action="store_true", help="verbose logging")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from pangolin_gui.app import PangolinApp
    # Gtk.Application parses its own argv; hand it only the program name.
    return PangolinApp(start_hidden=args.hidden).run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main())
