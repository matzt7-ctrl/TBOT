from fastapi import FastAPI, APIRouter, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any
import uuid
from datetime import datetime, timezone
import asyncio
import json
import threading
import time
import pandas as pd
import numpy as np
import talib

# Binance imports
from binance.client import Client
from binance.exceptions import BinanceAPIException
import websocket

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# Create the main app without a prefix
app = FastAPI(title="Binance Trading Bot", description="Advanced MA-based Trading Bot for Binance")

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# WebSocket connections manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                pass

manager = ConnectionManager()

# Pydantic Models
class TradingConfig(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    symbol: str
    timeframes: List[str]
    sma_periods: List[int]
    trade_type: str  # "spot" or "futures"
    risk_management: Dict[str, Any]
    is_active: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class TradingConfigCreate(BaseModel):
    name: str
    symbol: str
    timeframes: List[str]
    sma_periods: List[int]
    trade_type: str
    risk_management: Dict[str, Any]

class Position(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    config_id: str
    symbol: str
    side: str  # "BUY" or "SELL"
    quantity: float
    entry_price: float
    current_price: float
    pnl: float
    pnl_percentage: float
    status: str  # "OPEN", "CLOSED"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Trade(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    config_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    order_id: str
    status: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class PriceData(BaseModel):
    symbol: str
    price: float
    timestamp: datetime
    volume: float = 0
    high: float = 0
    low: float = 0

# SMA Calculator
class SMACalculator:
    def __init__(self):
        self.price_data = {}
        
    def add_price_data(self, symbol: str, timeframe: str, price: float, timestamp: datetime):
        key = f"{symbol}_{timeframe}"
        if key not in self.price_data:
            self.price_data[key] = []
        
        self.price_data[key].append({
            'price': price,
            'timestamp': timestamp
        })
        
        # Keep only last 200 data points for memory efficiency
        if len(self.price_data[key]) > 200:
            self.price_data[key] = self.price_data[key][-200:]
    
    def calculate_sma(self, symbol: str, timeframe: str, period: int) -> Optional[float]:
        key = f"{symbol}_{timeframe}"
        if key not in self.price_data or len(self.price_data[key]) < period:
            return None
        
        recent_prices = [data['price'] for data in self.price_data[key][-period:]]
        return sum(recent_prices) / len(recent_prices)
    
    def get_sma_signals(self, symbol: str, timeframe: str, fast_period: int, slow_period: int) -> Dict[str, Any]:
        fast_sma = self.calculate_sma(symbol, timeframe, fast_period)
        slow_sma = self.calculate_sma(symbol, timeframe, slow_period)
        
        if fast_sma is None or slow_sma is None:
            return {"signal": "WAIT", "fast_sma": fast_sma, "slow_sma": slow_sma}
        
        if fast_sma > slow_sma:
            signal = "BUY"
        elif fast_sma < slow_sma:
            signal = "SELL"
        else:
            signal = "HOLD"
        
        return {
            "signal": signal,
            "fast_sma": fast_sma,
            "slow_sma": slow_sma,
            "crossover_strength": abs(fast_sma - slow_sma) / slow_sma * 100
        }

# Trading Engine
class TradingEngine:
    def __init__(self):
        self.binance_client = None
        self.sma_calculator = SMACalculator()
        self.active_configs = {}
        self.positions = {}
        self.is_running = False
        
    def initialize_binance_client(self, api_key: str, api_secret: str):
        try:
            self.binance_client = Client(api_key, api_secret)
            # Test connection
            self.binance_client.get_account()
            return True
        except Exception as e:
            logging.error(f"Failed to initialize Binance client: {e}")
            return False
    
    async def start_trading(self, config: TradingConfig):
        self.active_configs[config.id] = config
        # Start price monitoring for this config
        await self.monitor_symbol_prices(config)
    
    async def stop_trading(self, config_id: str):
        if config_id in self.active_configs:
            del self.active_configs[config_id]
    
    async def monitor_symbol_prices(self, config: TradingConfig):
        # This would typically connect to Binance WebSocket
        # For now, we'll simulate with periodic price updates
        while config.id in self.active_configs:
            try:
                if self.binance_client:
                    ticker = self.binance_client.get_symbol_ticker(symbol=config.symbol)
                    current_price = float(ticker['price'])
                    current_time = datetime.now(timezone.utc)
                    
                    # Add price data for all configured timeframes
                    for timeframe in config.timeframes:
                        self.sma_calculator.add_price_data(
                            config.symbol, timeframe, current_price, current_time
                        )
                    
                    # Check for trading signals
                    await self.check_trading_signals(config, current_price)
                    
                    # Broadcast price update to connected clients
                    price_data = {
                        "type": "price_update",
                        "symbol": config.symbol,
                        "price": current_price,
                        "timestamp": current_time.isoformat()
                    }
                    await manager.broadcast(json.dumps(price_data))
                
            except Exception as e:
                logging.error(f"Error monitoring prices for {config.symbol}: {e}")
            
            await asyncio.sleep(5)  # Update every 5 seconds
    
    async def check_trading_signals(self, config: TradingConfig, current_price: float):
        # Check SMA signals for each timeframe
        signals = {}
        
        for timeframe in config.timeframes:
            if len(config.sma_periods) >= 2:
                fast_period = min(config.sma_periods)
                slow_period = max(config.sma_periods)
                
                signal_data = self.sma_calculator.get_sma_signals(
                    config.symbol, timeframe, fast_period, slow_period
                )
                signals[timeframe] = signal_data
        
        # Advanced logic: require confirmation from multiple timeframes
        buy_signals = sum(1 for s in signals.values() if s["signal"] == "BUY")
        sell_signals = sum(1 for s in signals.values() if s["signal"] == "SELL")
        total_timeframes = len(signals)
        
        if buy_signals >= (total_timeframes * 0.6):  # 60% confirmation
            await self.execute_trade(config, "BUY", current_price)
        elif sell_signals >= (total_timeframes * 0.6):
            await self.execute_trade(config, "SELL", current_price)
        
        # Broadcast signal data
        signal_update = {
            "type": "signal_update",
            "config_id": config.id,
            "symbol": config.symbol,
            "signals": signals,
            "consensus": {
                "buy_signals": buy_signals,
                "sell_signals": sell_signals,
                "total_timeframes": total_timeframes
            }
        }
        await manager.broadcast(json.dumps(signal_update))
    
    async def execute_trade(self, config: TradingConfig, side: str, price: float):
        try:
            # Risk management checks
            risk_config = config.risk_management
            max_position_size = risk_config.get("max_position_size", 0.01)
            
            # Calculate position size based on risk management
            account_info = self.binance_client.get_account()
            usdt_balance = 0
            for balance in account_info['balances']:
                if balance['asset'] == 'USDT':
                    usdt_balance = float(balance['free'])
                    break
            
            position_value = usdt_balance * max_position_size
            quantity = position_value / price
            
            # Place order
            if config.trade_type == "spot":
                if side == "BUY":
                    order = self.binance_client.order_market_buy(
                        symbol=config.symbol,
                        quoteOrderQty=position_value
                    )
                else:
                    # For sell, we need to calculate quantity differently
                    order = self.binance_client.order_market_sell(
                        symbol=config.symbol,
                        quantity=quantity
                    )
            
            # Save trade to database
            trade = Trade(
                config_id=config.id,
                symbol=config.symbol,
                side=side,
                quantity=float(order.get('executedQty', quantity)),
                price=float(order.get('price', price)),
                order_id=str(order['orderId']),
                status=order['status']
            )
            
            trade_dict = trade.dict()
            trade_dict['timestamp'] = trade_dict['timestamp'].isoformat()
            await db.trades.insert_one(trade_dict)
            
            # Broadcast trade execution
            trade_update = {
                "type": "trade_executed",
                "trade": trade_dict
            }
            await manager.broadcast(json.dumps(trade_update))
            
        except Exception as e:
            logging.error(f"Error executing trade: {e}")

# Global trading engine instance
trading_engine = TradingEngine()

# API Routes
@api_router.get("/")
async def root():
    return {"message": "Binance Trading Bot API", "status": "active"}

@api_router.post("/config", response_model=TradingConfig)
async def create_trading_config(config: TradingConfigCreate):
    config_obj = TradingConfig(**config.dict())
    config_dict = config_obj.dict()
    config_dict['created_at'] = config_dict['created_at'].isoformat()
    await db.trading_configs.insert_one(config_dict)
    return config_obj

@api_router.get("/configs", response_model=List[TradingConfig])
async def get_trading_configs():
    configs = await db.trading_configs.find().to_list(100)
    for config in configs:
        if 'created_at' in config and isinstance(config['created_at'], str):
            config['created_at'] = datetime.fromisoformat(config['created_at'])
    return [TradingConfig(**config) for config in configs]

@api_router.put("/config/{config_id}/toggle")
async def toggle_trading_config(config_id: str):
    config = await db.trading_configs.find_one({"id": config_id})
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    
    new_status = not config.get('is_active', False)
    await db.trading_configs.update_one(
        {"id": config_id},
        {"$set": {"is_active": new_status}}
    )
    
    if new_status:
        config_obj = TradingConfig(**config)
        config_obj.is_active = True
        await trading_engine.start_trading(config_obj)
    else:
        await trading_engine.stop_trading(config_id)
    
    return {"config_id": config_id, "is_active": new_status}

@api_router.post("/binance/setup")
async def setup_binance_credentials(credentials: Dict[str, str]):
    api_key = credentials.get("api_key")
    api_secret = credentials.get("api_secret")
    
    if not api_key or not api_secret:
        raise HTTPException(status_code=400, detail="API key and secret are required")
    
    success = trading_engine.initialize_binance_client(api_key, api_secret)
    if success:
        return {"status": "success", "message": "Binance client initialized successfully"}
    else:
        raise HTTPException(status_code=400, detail="Failed to initialize Binance client")

@api_router.get("/account")
async def get_account_info():
    if not trading_engine.binance_client:
        raise HTTPException(status_code=400, detail="Binance client not initialized")
    
    try:
        account_info = trading_engine.binance_client.get_account()
        balances = []
        for balance in account_info['balances']:
            free_amount = float(balance['free'])
            locked_amount = float(balance['locked'])
            if free_amount > 0 or locked_amount > 0:
                balances.append({
                    'asset': balance['asset'],
                    'free': free_amount,
                    'locked': locked_amount,
                    'total': free_amount + locked_amount
                })
        
        return {
            'account_type': account_info['accountType'],
            'can_trade': account_info['canTrade'],
            'balances': balances
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get account info: {str(e)}")

@api_router.get("/trades", response_model=List[Trade])
async def get_trades(config_id: Optional[str] = None):
    query = {"config_id": config_id} if config_id else {}
    trades = await db.trades.find(query).sort("timestamp", -1).to_list(100)
    
    for trade in trades:
        if 'timestamp' in trade and isinstance(trade['timestamp'], str):
            trade['timestamp'] = datetime.fromisoformat(trade['timestamp'])
    
    return [Trade(**trade) for trade in trades]

@api_router.get("/positions", response_model=List[Position])
async def get_positions():
    positions = await db.positions.find().to_list(100)
    for position in positions:
        for field in ['created_at', 'updated_at']:
            if field in position and isinstance(position[field], str):
                position[field] = datetime.fromisoformat(position[field])
    return [Position(**position) for position in positions]

@api_router.get("/market/price/{symbol}")
async def get_symbol_price(symbol: str):
    if not trading_engine.binance_client:
        raise HTTPException(status_code=400, detail="Binance client not initialized")
    
    try:
        ticker = trading_engine.binance_client.get_symbol_ticker(symbol=symbol)
        return {
            "symbol": symbol,
            "price": float(ticker['price']),
            "timestamp": datetime.now(timezone.utc)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get price: {str(e)}")

@api_router.get("/analysis/sma/{symbol}")
async def get_sma_analysis(symbol: str, timeframe: str = "1h", periods: str = "10,20,50"):
    try:
        period_list = [int(p.strip()) for p in periods.split(',')]
        analysis = {}
        
        for period in period_list:
            sma_value = trading_engine.sma_calculator.calculate_sma(symbol, timeframe, period)
            analysis[f"sma_{period}"] = sma_value
        
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "analysis": analysis,
            "timestamp": datetime.now(timezone.utc)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get SMA analysis: {str(e)}")

# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Handle incoming WebSocket messages
            try:
                message = json.loads(data)
                if message.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Include the router in the main app
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()