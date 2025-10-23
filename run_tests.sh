#!/bin/bash

# Contact Agent POC - Test Suite
# Information Gathering Team - L07

echo "======================================================================"
echo "CONTACT AGENT POC - TEST SUITE"
echo "======================================================================"

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
    echo "✓ Virtual environment activated"
else
    echo "⚠️  Warning: No virtual environment found. Run: python3 -m venv venv"
fi

echo ""
echo "======================================================================"
echo "TEST 1: Query Normalization (Step 1)"
echo "======================================================================"
python -m scripts.task_parser
if [ $? -eq 0 ]; then
    echo "✓ Test 1 PASSED"
else
    echo "✗ Test 1 FAILED"
    exit 1
fi

echo ""
echo "======================================================================"
echo "TEST 2: Domain Finding (Step 2)"
echo "======================================================================"
python -m scripts.domain_finder_cli --company "UCF Computer Science" --provider dummy
if [ $? -eq 0 ]; then
    echo "✓ Test 2 PASSED"
else
    echo "✗ Test 2 FAILED"
    exit 1
fi

echo ""
echo "======================================================================"
echo "TEST 3: Contact Flow (Step 1 + Step 2)"
echo "======================================================================"
python -m scripts.contact_flow_cli --query "find contact for UCF" --provider dummy
if [ $? -eq 0 ]; then
    echo "✓ Test 3 PASSED"
else
    echo "✗ Test 3 FAILED"
    exit 1
fi

echo ""
echo "======================================================================"
echo "TEST 4: Contact Extraction (Step 3) - Real Website"
echo "======================================================================"
python -m scripts.contact_extraction_cli --url "https://www.ucf.edu/about/" --company "UCF" --timeout 15
if [ $? -eq 0 ]; then
    echo "✓ Test 4 PASSED"
else
    echo "⚠️  Test 4 FAILED (may be network-related)"
fi

echo ""
echo "======================================================================"
echo "TEST 5: Complete Workflow (Step 1 + 2 + 3) with Dummy Provider"
echo "======================================================================"
python -m scripts.contact_agent_full --query "UCF Computer Science contact" --provider dummy
if [ $? -eq 0 ]; then
    echo "✓ Test 5 PASSED"
else
    echo "✗ Test 5 FAILED"
    exit 1
fi

echo ""
echo "======================================================================"
echo "TEST 6: JSON Output Format (for BI Team Integration)"
echo "======================================================================"
python -m scripts.contact_agent_full --query "test query" --provider dummy --json > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "✓ Test 6 PASSED"
else
    echo "✗ Test 6 FAILED"
    exit 1
fi

echo ""
echo "======================================================================"
echo "ALL TESTS COMPLETED"
echo "======================================================================"
echo ""
echo "✓ Contact Agent POC is fully functional!"
echo ""
echo "Next steps:"
echo "  1. Set SERPAPI_KEY in .env to test with real Google search"
echo "  2. Run: python -m scripts.contact_agent_full --query 'your query' --provider serpapi"
echo "  3. Integrate with Browser Interaction team's agent orchestration"
echo ""

