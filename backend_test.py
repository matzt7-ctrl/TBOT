import requests
import sys
import json
from datetime import datetime

class BinanceTradingBotTester:
    def __init__(self, base_url="https://ma-trade-bot.preview.emergentagent.com"):
        self.base_url = base_url
        self.api_url = f"{base_url}/api"
        self.tests_run = 0
        self.tests_passed = 0

    def run_test(self, name, method, endpoint, expected_status, data=None, headers=None):
        """Run a single API test"""
        url = f"{self.api_url}/{endpoint}" if endpoint else f"{self.api_url}/"
        if headers is None:
            headers = {'Content-Type': 'application/json'}

        self.tests_run += 1
        print(f"\n🔍 Testing {name}...")
        print(f"   URL: {url}")
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, timeout=10)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=headers, timeout=10)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=headers, timeout=10)

            success = response.status_code == expected_status
            if success:
                self.tests_passed += 1
                print(f"✅ Passed - Status: {response.status_code}")
                try:
                    response_data = response.json()
                    print(f"   Response: {json.dumps(response_data, indent=2)[:200]}...")
                except:
                    print(f"   Response: {response.text[:200]}...")
            else:
                print(f"❌ Failed - Expected {expected_status}, got {response.status_code}")
                print(f"   Response: {response.text[:200]}...")

            return success, response.json() if response.headers.get('content-type', '').startswith('application/json') else response.text

        except Exception as e:
            print(f"❌ Failed - Error: {str(e)}")
            return False, {}

    def test_health_check(self):
        """Test the health check endpoint"""
        return self.run_test("Health Check", "GET", "", 200)

    def test_get_configs(self):
        """Test getting trading configurations"""
        return self.run_test("Get Trading Configs", "GET", "configs", 200)

    def test_create_config(self):
        """Test creating a trading configuration"""
        sample_config = {
            "name": "BTC Test Strategy",
            "symbol": "BTCUSDT",
            "timeframes": ["1h", "4h"],
            "sma_periods": [10, 20, 50],
            "trade_type": "spot",
            "risk_management": {
                "max_position_size": 0.01,
                "stop_loss_percentage": 2,
                "take_profit_percentage": 5,
                "max_daily_loss": 100
            }
        }
        return self.run_test("Create Trading Config", "POST", "config", 200, sample_config)

    def test_get_trades(self):
        """Test getting trade history"""
        return self.run_test("Get Trades", "GET", "trades", 200)

    def test_get_positions(self):
        """Test getting positions"""
        return self.run_test("Get Positions", "GET", "positions", 200)

    def test_binance_setup_without_credentials(self):
        """Test Binance setup without credentials (should fail)"""
        return self.run_test("Binance Setup (No Credentials)", "POST", "binance/setup", 400, {})

    def test_account_without_setup(self):
        """Test account info without Binance setup (should fail)"""
        return self.run_test("Account Info (No Setup)", "GET", "account", 400)

    def test_market_price_without_setup(self):
        """Test market price without Binance setup (should fail)"""
        return self.run_test("Market Price (No Setup)", "GET", "market/price/BTCUSDT", 400)

    def test_sma_analysis(self):
        """Test SMA analysis endpoint"""
        return self.run_test("SMA Analysis", "GET", "analysis/sma/BTCUSDT?timeframe=1h&periods=10,20,50", 200)

    def test_websocket_endpoint(self):
        """Test WebSocket endpoint availability (basic check)"""
        try:
            import websocket
            ws_url = self.base_url.replace('https://', 'wss://').replace('http://', 'ws://') + '/ws'
            print(f"\n🔍 Testing WebSocket Connection...")
            print(f"   URL: {ws_url}")
            
            # Simple connection test
            ws = websocket.create_connection(ws_url, timeout=5)
            ws.close()
            print("✅ WebSocket connection successful")
            self.tests_passed += 1
            self.tests_run += 1
            return True, "WebSocket connection successful"
        except Exception as e:
            print(f"❌ WebSocket connection failed: {str(e)}")
            self.tests_run += 1
            return False, str(e)

def main():
    print("🚀 Starting Binance Trading Bot API Tests")
    print("=" * 50)
    
    tester = BinanceTradingBotTester()
    
    # Run all tests
    test_results = []
    
    # Basic API tests
    test_results.append(tester.test_health_check())
    test_results.append(tester.test_get_configs())
    test_results.append(tester.test_create_config())
    test_results.append(tester.test_get_trades())
    test_results.append(tester.test_get_positions())
    
    # Binance integration tests (expected to fail without API keys)
    test_results.append(tester.test_binance_setup_without_credentials())
    test_results.append(tester.test_account_without_setup())
    test_results.append(tester.test_market_price_without_setup())
    
    # Analysis tests
    test_results.append(tester.test_sma_analysis())
    
    # WebSocket test
    test_results.append(tester.test_websocket_endpoint())
    
    # Print final results
    print("\n" + "=" * 50)
    print(f"📊 Test Results: {tester.tests_passed}/{tester.tests_run} tests passed")
    
    failed_tests = tester.tests_run - tester.tests_passed
    if failed_tests > 0:
        print(f"⚠️  {failed_tests} tests failed")
        return 1
    else:
        print("🎉 All tests passed!")
        return 0

if __name__ == "__main__":
    sys.exit(main())