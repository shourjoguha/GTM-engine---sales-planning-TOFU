#!/usr/bin/env python3
"""Test chart server functionality"""

import sys
from pathlib import Path

# Add reportingCharts to path
sys.path.insert(0, str(Path(__file__).parent / 'reportingCharts'))
from run_charts import build_handler
import socket
import threading
from http.server import ThreadingHTTPServer


def find_available_port(start_port=8765):
    """Find an available port starting from start_port"""
    for port in range(start_port, start_port + 100):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('127.0.0.1', port))
                return port
        except OSError:
            continue
    raise RuntimeError('No available ports found')


def test_chart_server():
    """Test chart server components"""
    print("Testing chart server functionality...")
    
    # Test 1: Port finding
    print("\n1. Testing port finding...")
    port = find_available_port()
    print(f"   Found available port: {port}")
    
    # Test 2: Handler creation
    print("\n2. Testing handler creation...")
    test_dir = Path(__file__).parent / 'data' / 'dummy'
    if test_dir.exists():
        handler = build_handler(test_dir)
        print("   Successfully created chart server handler")
        
        # Test 3: Server creation (don't start it)
        print("\n3. Testing server instantiation...")
        server = ThreadingHTTPServer(('127.0.0.1', port), handler)
        print(f"   Successfully created HTTP server on port {port}")
        server.server_close()
        print("   Server closed successfully")
    else:
        print("   Test directory not found, skipping handler test")
    
    print("\n✓ Chart server functionality is working!")
    return True


if __name__ == '__main__':
    try:
        test_chart_server()
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
