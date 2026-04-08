#!/usr/bin/env python3
"""
Integration test for chart server backend functionality.
Tests all chart server management endpoints.
"""

import requests
import time
import sys

BASE_URL = "http://localhost:8000"


def test_list_servers():
    """Test listing all chart servers"""
    print("\n1. Testing list servers endpoint...")
    response = requests.get(f"{BASE_URL}/api/charts/servers")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert "servers" in data, "Response should contain 'servers'"
    assert "count" in data, "Response should contain 'count'"
    print(f"   ✓ Found {data['count']} running servers")
    return data


def test_start_server(version_id):
    """Test starting a chart server for a version"""
    print(f"\n2. Testing start server for {version_id}...")
    response = requests.post(f"{BASE_URL}/api/charts/server/{version_id}")
    
    if response.status_code == 404:
        print(f"   ! Version {version_id} not found (expected for non-existent versions)")
        return None
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert data["status"] in ["started", "already_running"], f"Unexpected status: {data['status']}"
    assert "port" in data, "Response should contain 'port'"
    assert "url" in data, "Response should contain 'url'"
    print(f"   ✓ Server {data['status']} on port {data['port']}")
    print(f"   ✓ URL: {data['url']}")
    return data


def test_server_status(version_id):
    """Test checking chart server status"""
    print(f"\n3. Testing server status for {version_id}...")
    response = requests.get(f"{BASE_URL}/api/charts/server/{version_id}/status")
    
    if response.status_code == 404:
        print(f"   ! Server for {version_id} not found")
        return None
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert "status" in data, "Response should contain 'status'"
    print(f"   ✓ Server status: {data['status']}")
    if data['status'] == 'running':
        assert "port" in data, "Running server should have 'port'"
        assert "url" in data, "Running server should have 'url'"
        print(f"   ✓ Running on port {data['port']}")
    return data


def test_stop_server(version_id):
    """Test stopping a chart server"""
    print(f"\n4. Testing stop server for {version_id}...")
    response = requests.delete(f"{BASE_URL}/api/charts/server/{version_id}")
    
    if response.status_code == 404:
        print(f"   ! Server for {version_id} not found")
        return None
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    data = response.json()
    assert data["status"] in ["stopped", "not_running"], f"Unexpected status: {data['status']}"
    print(f"   ✓ Server {data['status']}")
    return data


def test_multiple_servers():
    """Test running multiple chart servers simultaneously"""
    print("\n5. Testing multiple simultaneous servers...")
    
    # Start server for test_v001
    server1 = test_start_server("test_v001")
    if server1 and server1['status'] == 'started':
        port1 = server1['port']
        
        # Start server for test_v002
        server2 = test_start_server("test_v002")
        if server2 and server2['status'] == 'started':
            port2 = server2['port']
            
            # Verify different ports
            assert port1 != port2, "Servers should use different ports"
            print(f"   ✓ Servers running on different ports: {port1} and {port2}")
            
            # List all servers
            servers = test_list_servers()
            assert servers['count'] == 2, f"Expected 2 servers, got {servers['count']}"
            
            # Stop both servers
            test_stop_server("test_v001")
            test_stop_server("test_v002")
            
            # Verify cleanup
            time.sleep(1)
            servers = test_list_servers()
            assert servers['count'] == 0, f"Expected 0 servers after cleanup, got {servers['count']}"
            print(f"   ✓ All servers stopped and cleaned up")
            return True
    
    return False


def test_port_allocation():
    """Test dynamic port allocation"""
    print("\n6. Testing dynamic port allocation...")
    
    # Start multiple servers and check port allocation
    ports = []
    for i in range(3):
        version_id = f"test_v001" if i % 2 == 0 else "test_v002"
        server = test_start_server(version_id)
        if server and server['status'] == 'started':
            port = server['port']
            if port not in ports:
                ports.append(port)
                print(f"   ✓ Allocated port: {port}")
            else:
                print(f"   ! Port {port} reused (expected for same version)")
    
    # Stop all servers
    test_stop_server("test_v001")
    test_stop_server("test_v002")
    
    return True


def run_all_tests():
    """Run all integration tests"""
    print("=" * 60)
    print("CHART SERVER BACKEND INTEGRATION TESTS")
    print("=" * 60)
    
    try:
        # Test 1: List servers (should be empty initially)
        test_list_servers()
        
        # Test 2: Start servers for test versions
        test_start_server("test_v001")
        test_start_server("test_v002")
        
        # Test 3: Check server status
        test_server_status("test_v001")
        test_server_status("test_v002")
        
        # Test 4: List servers (should show 2)
        servers = test_list_servers()
        assert servers['count'] == 2, f"Expected 2 servers, got {servers['count']}"
        
        # Test 5: Test non-existent version
        print("\n7. Testing non-existent version...")
        response = requests.post(f"{BASE_URL}/api/charts/server/nonexistent_v999")
        assert response.status_code == 404, "Expected 404 for non-existent version"
        print("   ✓ Correctly returns 404 for non-existent version")
        
        # Test 6: Stop servers
        test_stop_server("test_v001")
        test_stop_server("test_v002")
        
        # Test 7: Verify cleanup
        time.sleep(1)
        servers = test_list_servers()
        assert servers['count'] == 0, f"Expected 0 servers, got {servers['count']}"
        
        # Test 8: Test multiple servers simultaneously
        test_multiple_servers()
        
        # Test 9: Test port allocation
        test_port_allocation()
        
        print("\n" + "=" * 60)
        print("✓ ALL TESTS PASSED!")
        print("=" * 60)
        return True
        
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        return False
    except Exception as e:
        print(f"\n✗ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    # Check if server is running
    try:
        requests.get(BASE_URL, timeout=2)
    except requests.exceptions.ConnectionError:
        print(f"✗ Server not running at {BASE_URL}")
        print("Please start the Flask server first: python3 app.py")
        sys.exit(1)
    
    success = run_all_tests()
    sys.exit(0 if success else 1)
