"""
PDF Merger Main Entry Point.
Handles CLI arguments, Context Menu installation/uninstallation,
Atomic Single-Instance Election, and GUI lifecycle.
"""

import os
import sys
import time
import argparse
from typing import List

# Ensure src module can be found
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ipc import setup_single_instance
from src.registry import install_context_menu, uninstall_context_menu


def parse_args():
    parser = argparse.ArgumentParser(description="PDF Merger with Bookmarks and File Conversion")
    parser.add_argument("--install", action="store_true", help="Install context menu entry in Windows Explorer")
    parser.add_argument("--uninstall", action="store_true", help="Remove context menu entry from Windows Explorer")
    parser.add_argument("-o", "--output", help="Output PDF file path (for silent/CLI mode)")
    parser.add_argument("--silent", action="store_true", help="Run merge without GUI")
    parser.add_argument("files", nargs="*", help="Files or folders to merge")
    return parser.parse_known_args()


def main():
    args, unknown = parse_args()
    
    # 1. Registry commands
    if args.install:
        success = install_context_menu()
        sys.exit(0 if success else 1)
            
    if args.uninstall:
        success = uninstall_context_menu()
        sys.exit(0 if success else 1)

    # 2. Collect input files
    all_input_files = list(args.files) + list(unknown)
    cleaned_files = []
    for f in all_input_files:
        clean_p = f.strip().strip('"').strip("'")
        if os.path.exists(clean_p):
            cleaned_files.append(os.path.abspath(clean_p))

    # 3. CLI / Silent mode
    if args.silent and args.output:
        from src.merger import merge_files
        try:
            res = merge_files(cleaned_files, args.output)
            sys.exit(0)
        except Exception:
            sys.exit(1)

    # 4. Atomic Single-Instance Coordination
    # Determines if this process is the Master or a secondary instance
    is_master, master_server = setup_single_instance(cleaned_files)
    if not is_master:
        # Handed off files to master -> Exit immediately, don't open extra windows!
        sys.exit(0)

    # If this is the Master instance, give a brief pause (200ms) to collect all
    # simultaneous instances launched by Windows Explorer for multiple selected files
    time.sleep(0.25)

    # 5. Start GUI
    from src.gui import PDFMergerApp
    
    initial = master_server.collected_files if master_server else cleaned_files
    app = PDFMergerApp(initial_files=initial)
    
    if master_server:
        master_server.set_callback(lambda new_files: app.after(0, app.add_files, new_files))
        
    try:
        app.mainloop()
    finally:
        if master_server:
            master_server.stop()


if __name__ == "__main__":
    main()
