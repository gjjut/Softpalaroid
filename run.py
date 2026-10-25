"""Запуск Softpalaroid из исходников:  python run.py [фото.jpg]"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from softpalaroid.app import main

if __name__ == "__main__":
    raise SystemExit(main())
