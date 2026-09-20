#!/usr/bin/env python3
"""Entry point. Run: python3 play.py [savefile] [--seed N]"""
import sys
from verdigris.game import main
if __name__ == "__main__":
    sys.exit(main())
