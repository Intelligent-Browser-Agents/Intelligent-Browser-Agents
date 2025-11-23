"""
Manual API tests for DOM Q&A endpoint.

Run this after starting the server with: uvicorn app.main:app --reload
"""
import requests
from pathlib import Path

BASE_URL = "http://localhost:8000"


def test_happy_path_policy():
    """Test normal request with policy.html (obvious Q&A)."""
    print("\n=== Test 1: Happy Path (policy.html) ===")
    html_file = Path("data/samples/policy.html")
    with open(html_file, 'r', encoding='utf-8') as f:
        html_content = f.read()

    response = requests.post(
        f"{BASE_URL}/answer",
        json={
            "dom": html_content,
            "prompt": "When are refunds allowed?"
        }
    )

    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    assert response.status_code == 200, "Expected 200 OK"
    print("✓ Happy path test (policy.html) passed\n")


def test_happy_path_simple():
    """Test normal request with simple.html."""
    print("=== Test 1b: Happy Path (simple.html) ===")
    html_file = Path("data/samples/simple.html")
    with open(html_file, 'r', encoding='utf-8') as f:
        html_content = f.read()

    response = requests.post(
        f"{BASE_URL}/answer",
        json={
            "dom": html_content,
            "prompt": "What is in the welcome section?"
        }
    )

    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    assert response.status_code == 200, "Expected 200 OK"
    print("✓ Happy path test (simple.html) passed\n")


def test_empty_dom():
    """Test validation with empty DOM."""
    print("=== Test 2: Empty DOM Validation ===")
    response = requests.post(
        f"{BASE_URL}/answer",
        json={
            "dom": "",
            "prompt": "What is the answer?"
        }
    )

    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    assert response.status_code == 422, "Expected 422 Unprocessable Entity"
    print("✓ Empty DOM validation test passed\n")


def test_empty_prompt():
    """Test validation with empty prompt."""
    print("=== Test 3: Empty Prompt Validation ===")
    response = requests.post(
        f"{BASE_URL}/answer",
        json={
            "dom": "<html><body><p>Content</p></body></html>",
            "prompt": ""
        }
    )

    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    assert response.status_code == 422, "Expected 422 Unprocessable Entity"
    print("✓ Empty prompt validation test passed\n")


def test_whitespace_only_dom():
    """Test validation with whitespace-only DOM."""
    print("=== Test 4: Whitespace-only DOM Validation ===")
    response = requests.post(
        f"{BASE_URL}/answer",
        json={
            "dom": "   \n\t  ",
            "prompt": "What is the answer?"
        }
    )

    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    assert response.status_code == 422, "Expected 422 Unprocessable Entity"
    print("✓ Whitespace-only DOM validation test passed\n")


def test_large_dom():
    """Test validation with DOM exceeding size limit (default 10MB)."""
    print("=== Test 5: Large DOM Validation (11MB) ===")
    # Create a large DOM (11MB) to exceed the default 10MB limit
    chunk = "<p>This is a large paragraph with enough text to make it meaningful. "
    target_size = 11_534_336  # 11MB in bytes
    chunk_size = len(chunk.encode('utf-8'))
    num_chunks = (target_size - 100) // chunk_size
    large_dom = "<html><body>" + (chunk * num_chunks) + "</body></html>"
    
    actual_size = len(large_dom.encode('utf-8'))
    print(f"Created DOM size: {actual_size / (1024*1024):.2f}MB")
    
    response = requests.post(
        f"{BASE_URL}/answer",
        json={
            "dom": large_dom,
            "prompt": "What is the answer?"
        }
    )

    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    assert response.status_code == 413, "Expected 413 Payload Too Large"
    print("✓ Large DOM validation test passed\n")


def test_health_check():
    """Test root health check endpoint."""
    print("=== Test 6: Health Check ===")
    response = requests.get(f"{BASE_URL}/")
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    assert response.status_code == 200, "Expected 200 OK"
    assert response.json()["status"] == "ok"
    print("✓ Health check test passed\n")


if __name__ == "__main__":
    print("=" * 60)
    print("DOM Q&A API Manual Tests")
    print("=" * 60)
    print("Make sure the server is running: uvicorn app.main:app --reload")
    print("=" * 60)
    
    try:
        test_health_check()
        test_happy_path_policy()
        test_happy_path_simple()
        test_empty_dom()
        test_empty_prompt()
        test_whitespace_only_dom()
        test_large_dom()
        
        print("=" * 60)
        print("✓ All manual tests passed!")
        print("=" * 60)
    except requests.exceptions.ConnectionError:
        print("\n❌ Error: Could not connect to server.")
        print("Please start the server with: uvicorn app.main:app --reload")
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()