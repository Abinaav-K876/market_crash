#!/usr/bin/env python3
"""
Market Crash - Multiplayer Economic Simulation Game
Flask application running on port 8086 with SQLite database at specified path
"""
import os
import sys
import sqlite3
import threading
import time
import random
import json
from datetime import datetime
from functools import wraps
from flask import Flask, render_template_string, request, session, jsonify, redirect, url_for, g

# ======================
# CONFIGURATION
# ======================
DB_PATH = '/opt/extra1_1tb/database/market_crash.db'
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Secure random key
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1 hour session timeout

# ======================
# DATABASE SETUP
# ======================
def get_db():
    """Get database connection for current request"""
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(error):
    """Close database connection when request ends"""
    if hasattr(g, 'db'):
        g.db.close()

def init_db():
    """Initialize database schema"""
    db = sqlite3.connect(DB_PATH)
    cursor = db.cursor()
    
    # Enable foreign keys
    cursor.execute("PRAGMA foreign_keys = ON")
    
    # Rooms table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rooms (
            room_id TEXT PRIMARY KEY,
            current_price REAL NOT NULL DEFAULT 100.0,
            round_number INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            crash_occurred INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Players table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id TEXT NOT NULL,
            player_name TEXT NOT NULL,
            cash REAL NOT NULL DEFAULT 1000.0,
            shares_held INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE CASCADE
        )
    ''')
    
    # Transactions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id TEXT NOT NULL,
            player_id INTEGER NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('buy', 'sell')),
            shares INTEGER NOT NULL,
            price_per_share REAL NOT NULL,
            total_amount REAL NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE CASCADE,
            FOREIGN KEY (player_id) REFERENCES players(id) ON DELETE CASCADE
        )
    ''')
    
    # Price history table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id TEXT NOT NULL,
            round_number INTEGER NOT NULL,
            price REAL NOT NULL,
            event_type TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE CASCADE
        )
    ''')
    
    # Create indexes for performance
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_rooms_active ON rooms(is_active, crash_occurred, round_number)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_players_room ON players(room_id, is_active)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_transactions_room ON transactions(room_id, timestamp)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_price_history_room ON price_history(room_id, round_number)')
    
    db.commit()
    db.close()
    print(f"✓ Database initialized at {DB_PATH}")

# ======================
# GAME ENGINE
# ======================
class MarketEngine:
    """Handles market simulation logic"""
    MAX_ROUNDS = 10
    CRASH_PROBABILITY = 0.10  # 10% chance of crash per round
    BIG_MOVE_PROBABILITY = 0.20  # 20% chance of significant move
    NORMAL_VOLATILITY = (0.90, 1.10)  # 10% up/down
    BIG_VOLATILITY = (0.75, 1.25)    # 25% up/down
    
    @staticmethod
    def calculate_new_price(current_price, round_num):
        """Calculate new price with realistic market events"""
        # Crash event (terminal)
        if random.random() < MarketEngine.CRASH_PROBABILITY:
            return 0.01, "CRASH", True
        
        # Determine volatility based on round progression
        if round_num > 7:  # Increased volatility in late game
            volatility = (0.80, 1.30)
        elif round_num > 4:
            volatility = (0.85, 1.20)
        else:
            volatility = MarketEngine.NORMAL_VOLATILITY
        
        # Big move event
        if random.random() < MarketEngine.BIG_MOVE_PROBABILITY:
            volatility = MarketEngine.BIG_VOLATILITY
        
        # Apply random factor with floor at $0.01
        factor = random.uniform(volatility[0], volatility[1])
        new_price = max(0.01, round(current_price * factor, 2))
        
        # Determine event type for display
        if factor > 1.15:
            event_type = "SURGE"
        elif factor > 1.05:
            event_type = "RISE"
        elif factor < 0.85:
            event_type = "CRASH_WARNING"
        elif factor < 0.95:
            event_type = "DROP"
        else:
            event_type = "STABLE"
            
        return new_price, event_type, False

def market_simulation_loop():
    """Background thread that updates market prices every 10 seconds"""
    print("✓ Market simulation engine started")
    while True:
        time.sleep(10)  # Update every 10 seconds
        
        try:
            db = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
            db.row_factory = sqlite3.Row
            cursor = db.cursor()
            
            # Get all active rooms that haven't crashed and haven't reached max rounds
            cursor.execute('''
                SELECT room_id, current_price, round_number 
                FROM rooms 
                WHERE is_active = 1 
                  AND crash_occurred = 0 
                  AND round_number < ?
            ''', (MarketEngine.MAX_ROUNDS,))
            
            active_rooms = cursor.fetchall()
            if not active_rooms:
                db.close()
                continue
            
            print(f"→ Processing {len(active_rooms)} active rooms")
            
            for room in active_rooms:
                room_id = room['room_id']
                current_price = room['current_price']
                round_num = room['round_number'] + 1
                
                # Calculate new price and event
                new_price, event_type, is_crash = MarketEngine.calculate_new_price(current_price, round_num)
                
                # Determine game state
                is_active = 1
                crash_occurred = 1 if is_crash else 0
                
                if is_crash or round_num >= MarketEngine.MAX_ROUNDS:
                    is_active = 0
                
                # Update room state
                cursor.execute('''
                    UPDATE rooms 
                    SET current_price = ?, 
                        round_number = ?, 
                        is_active = ?, 
                        crash_occurred = ?,
                        last_updated = CURRENT_TIMESTAMP
                    WHERE room_id = ?
                ''', (new_price, round_num, is_active, crash_occurred, room_id))
                
                # Record price history
                cursor.execute('''
                    INSERT INTO price_history (room_id, round_number, price, event_type)
                    VALUES (?, ?, ?, ?)
                ''', (room_id, round_num, new_price, event_type))
                
                # Announce significant events
                if is_crash:
                    print(f"!!! MARKET CRASH in room {room_id} at round {round_num} !!!")
                elif round_num >= MarketEngine.MAX_ROUNDS:
                    print(f"✓ Room {room_id} completed all {MarketEngine.MAX_ROUNDS} rounds")
                else:
                    print(f"Room {room_id} | Round {round_num} | {event_type}: ${current_price:.2f} → ${new_price:.2f}")
            
            db.commit()
            db.close()
            
        except Exception as e:
            print(f"✗ Error in market simulation: {str(e)}")
            if 'db' in locals():
                try:
                    db.rollback()
                    db.close()
                except:
                    pass

# ======================
# HELPERS & DECORATORS
# ======================
def require_player(f):
    """Decorator to ensure player is in session and valid"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        room_id = kwargs.get('room_id') or request.json.get('room_id')
        player_id = session.get('player_id')
        
        if not player_id or not room_id:
            return jsonify({'error': 'Session expired. Please rejoin the room.'}), 401
        
        db = get_db()
        cursor = db.cursor()
        
        # Verify player exists in this room
        cursor.execute('''
            SELECT p.*, r.is_active, r.crash_occurred, r.current_price
            FROM players p
            JOIN rooms r ON p.room_id = r.room_id
            WHERE p.id = ? AND p.room_id = ? AND p.is_active = 1
        ''', (player_id, room_id))
        
        player = cursor.fetchone()
        if not player:
            session.clear()
            return jsonify({'error': 'Player not found in this room. Session expired.'}), 403
        
        # Attach player and room data to request context
        request.player = player
        request.room = {
            'is_active': player['is_active'],
            'crash_occurred': player['crash_occurred'],
            'current_price': player['current_price']
        }
        
        return f(*args, **kwargs)
    return decorated_function

def generate_room_id():
    """Generate unique 6-character room ID"""
    while True:
        room_id = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=6))
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT 1 FROM rooms WHERE room_id = ?", (room_id,))
        if not cursor.fetchone():
            return room_id

# ======================
# ROUTES
# ======================
@app.route('/')
def index():
    """Landing page with room creation/joining"""
    return render_template_string(HTML_TEMPLATES['index'])

@app.route('/create_room', methods=['POST'])
def create_room():
    """Create a new game room"""
    player_name = request.form.get('player_name', '').strip()
    if not player_name or len(player_name) < 2 or len(player_name) > 15:
        return redirect(url_for('index'))
    
    # Generate unique room ID
    room_id = generate_room_id()
    
    db = get_db()
    cursor = db.cursor()
    
    # Create room
    cursor.execute('''
        INSERT INTO rooms (room_id, current_price, round_number, is_active, crash_occurred)
        VALUES (?, 100.0, 0, 1, 0)
    ''', (room_id,))
    
    # Create player
    cursor.execute('''
        INSERT INTO players (room_id, player_name, cash, shares_held, is_active)
        VALUES (?, ?, 1000.0, 0, 1)
    ''', (room_id, player_name))
    
    player_id = cursor.lastrowid
    db.commit()
    
    # Set session
    session.permanent = True
    session['player_id'] = player_id
    session['room_id'] = room_id
    
    return redirect(url_for('room', room_id=room_id))

@app.route('/join_room', methods=['POST'])
def join_room():
    """Join an existing game room"""
    room_id = request.form.get('room_id', '').strip().upper()
    player_name = request.form.get('player_name', '').strip()
    
    if not room_id or not player_name or len(player_name) < 2 or len(player_name) > 15:
        return redirect(url_for('index'))
    
    db = get_db()
    cursor = db.cursor()
    
    # Verify room exists and is joinable (round 0, active, not crashed)
    cursor.execute('''
        SELECT * FROM rooms 
        WHERE room_id = ? 
          AND is_active = 1 
          AND crash_occurred = 0 
          AND round_number = 0
    ''', (room_id,))
    
    room = cursor.fetchone()
    if not room:
        return redirect(url_for('index'))
    
    # Create player
    cursor.execute('''
        INSERT INTO players (room_id, player_name, cash, shares_held, is_active)
        VALUES (?, ?, 1000.0, 0, 1)
    ''', (room_id, player_name))
    
    player_id = cursor.lastrowid
    db.commit()
    
    # Set session
    session.permanent = True
    session['player_id'] = player_id
    session['room_id'] = room_id
    
    return redirect(url_for('room', room_id=room_id))

@app.route('/room/<room_id>')
def room(room_id):
    """Game room interface"""
    player_id = session.get('player_id')
    if not player_id:
        return redirect(url_for('index'))
    
    db = get_db()
    cursor = db.cursor()
    
    # Verify player belongs to this room
    cursor.execute('''
        SELECT p.*, r.round_number, r.is_active, r.crash_occurred, r.current_price
        FROM players p
        JOIN rooms r ON p.room_id = r.room_id
        WHERE p.id = ? AND p.room_id = ? AND p.is_active = 1
    ''', (player_id, room_id))
    
    player = cursor.fetchone()
    if not player:
        session.clear()
        return redirect(url_for('index'))
    
    return render_template_string(
        HTML_TEMPLATES['room'],
        room_id=room_id,
        player_name=player['player_name'],
        initial_cash=player['cash'],
        initial_shares=player['shares_held'],
        current_price=player['current_price'],
        round_number=player['round_number'],
        is_active=player['is_active'],
        crash_occurred=player['crash_occurred']
    )

@app.route('/api/room/<room_id>/state')
@require_player
def room_state(room_id):
    """Get current room state for AJAX updates"""
    db = get_db()
    cursor = db.cursor()
    
    # Get room info
    cursor.execute('SELECT * FROM rooms WHERE room_id = ?', (room_id,))
    room = cursor.fetchone()
    
    if not room:
        return jsonify({'error': 'Room not found'}), 404
    
    # Get all active players in room for leaderboard
    cursor.execute('''
        SELECT id, player_name, cash, shares_held 
        FROM players 
        WHERE room_id = ? AND is_active = 1
        ORDER BY (cash + shares_held * ?) DESC
    ''', (room_id, room['current_price']))
    
    players = cursor.fetchall()
    
    # Calculate leaderboard with total value
    leaderboard = []
    for p in players:
        total_value = p['cash'] + (p['shares_held'] * room['current_price'])
        leaderboard.append({
            'player_name': p['player_name'],
            'cash': round(p['cash'], 2),
            'shares': p['shares_held'],
            'total_value': round(total_value, 2),
            'is_current': p['id'] == request.player['id']
        })
    
    # Get recent transactions (last 8)
    cursor.execute('''
        SELECT t.*, p.player_name 
        FROM transactions t
        JOIN players p ON t.player_id = p.id
        WHERE t.room_id = ?
        ORDER BY t.timestamp DESC
        LIMIT 8
    ''', (room_id,))
    transactions = cursor.fetchall()
    
    # Get price history for chart (last 10 rounds)
    cursor.execute('''
        SELECT round_number, price, event_type 
        FROM price_history 
        WHERE room_id = ?
        ORDER BY round_number DESC
        LIMIT 10
    ''', (room_id,))
    price_history = cursor.fetchall()
    
    # Format price history for chart (oldest first)
    chart_data = []
    for ph in reversed(price_history):
        chart_data.append({
            'round': ph['round_number'],
            'price': round(ph['price'], 2),
            'event': ph['event_type']
        })
    
    # Determine game status message
    status_msg = ""
    if room['crash_occurred']:
        status_msg = "MARKET CRASHED! Game over."
    elif room['round_number'] >= MarketEngine.MAX_ROUNDS:
        status_msg = f"Game completed {MarketEngine.MAX_ROUNDS} rounds!"
    elif room['round_number'] == 0:
        status_msg = "Waiting for players... Game starts in under 10 seconds!"
    else:
        status_msg = f"Round {room['round_number']} of {MarketEngine.MAX_ROUNDS}"
    
    # Calculate player's total value
    player_total = request.player['cash'] + (request.player['shares_held'] * room['current_price'])
    
    return jsonify({
        'success': True,
        'room': {
            'current_price': round(room['current_price'], 2),
            'round_number': room['round_number'],
            'max_rounds': MarketEngine.MAX_ROUNDS,
            'is_active': room['is_active'],
            'crash_occurred': room['crash_occurred'],
            'status_message': status_msg,
            'time_until_update': max(0, 10 - (time.time() - room['last_updated'].timestamp()) % 10)
        },
        'player': {
            'cash': round(request.player['cash'], 2),
            'shares': request.player['shares_held'],
            'total_value': round(player_total, 2)
        },
        'leaderboard': leaderboard,
        'transactions': [{
            'player_name': t['player_name'],
            'type': t['type'].upper(),
            'shares': t['shares'],
            'price': round(t['price_per_share'], 2),
            'total': round(t['total_amount'], 2),
            'timestamp': t['timestamp'].strftime('%H:%M:%S')
        } for t in transactions],
        'price_history': chart_data,
        'events': {
            'CRASH': {'color': '#e74c3c', 'label': '💥 CRASH'},
            'CRASH_WARNING': {'color': '#e67e22', 'label': '⚠️ WARNING'},
            'SURGE': {'color': '#2ecc71', 'label': '🚀 SURGE'},
            'RISE': {'color': '#27ae60', 'label': '📈 RISE'},
            'DROP': {'color': '#e67e22', 'label': '📉 DROP'},
            'STABLE': {'color': '#3498db', 'label': '➡️ STABLE'}
        }
    })

@app.route('/api/room/<room_id>/buy', methods=['POST'])
@require_player
def buy_shares(room_id):
    """Handle share purchase"""
    if not request.is_json:
        return jsonify({'error': 'Invalid request'}), 400
    
    data = request.get_json()
    try:
        shares = int(data.get('shares', 0))
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid share amount'}), 400
    
    if shares <= 0:
        return jsonify({'error': 'Shares must be positive'}), 400
    
    # Verify room is active and not crashed
    if not request.room['is_active'] or request.room['crash_occurred']:
        return jsonify({'error': 'Market is closed. Game has ended.'}), 400
    
    current_price = request.room['current_price']
    total_cost = shares * current_price
    
    # Verify sufficient funds
    if request.player['cash'] < total_cost:
        return jsonify({'error': f'Insufficient funds. Need ${total_cost:.2f}, have ${request.player["cash"]:.2f}'}), 400
    
    db = get_db()
    cursor = db.cursor()
    
    # Update player holdings
    new_cash = request.player['cash'] - total_cost
    new_shares = request.player['shares_held'] + shares
    
    cursor.execute('''
        UPDATE players 
        SET cash = ?, shares_held = ?
        WHERE id = ?
    ''', (new_cash, new_shares, request.player['id']))
    
    # Record transaction
    cursor.execute('''
        INSERT INTO transactions (room_id, player_id, type, shares, price_per_share, total_amount)
        VALUES (?, ?, 'buy', ?, ?, ?)
    ''', (room_id, request.player['id'], shares, current_price, total_cost))
    
    db.commit()
    
    return jsonify({
        'success': True,
        'message': f'Bought {shares} shares at ${current_price:.2f} each (${total_cost:.2f} total)',
        'new_cash': round(new_cash, 2),
        'new_shares': new_shares
    })

@app.route('/api/room/<room_id>/sell', methods=['POST'])
@require_player
def sell_shares(room_id):
    """Handle share sale"""
    if not request.is_json:
        return jsonify({'error': 'Invalid request'}), 400
    
    data = request.get_json()
    try:
        shares = int(data.get('shares', 0))
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid share amount'}), 400
    
    if shares <= 0:
        return jsonify({'error': 'Shares must be positive'}), 400
    
    # Verify room is active and not crashed
    if not request.room['is_active'] or request.room['crash_occurred']:
        return jsonify({'error': 'Market is closed. Game has ended.'}), 400
    
    # Verify sufficient shares
    if request.player['shares_held'] < shares:
        return jsonify({'error': f'Insufficient shares. Trying to sell {shares}, own {request.player["shares_held"]}'}), 400
    
    current_price = request.room['current_price']
    total_amount = shares * current_price
    
    db = get_db()
    cursor = db.cursor()
    
    # Update player holdings
    new_cash = request.player['cash'] + total_amount
    new_shares = request.player['shares_held'] - shares
    
    cursor.execute('''
        UPDATE players 
        SET cash = ?, shares_held = ?
        WHERE id = ?
    ''', (new_cash, new_shares, request.player['id']))
    
    # Record transaction
    cursor.execute('''
        INSERT INTO transactions (room_id, player_id, type, shares, price_per_share, total_amount)
        VALUES (?, ?, 'sell', ?, ?, ?)
    ''', (room_id, request.player['id'], shares, current_price, total_amount))
    
    db.commit()
    
    return jsonify({
        'success': True,
        'message': f'Sold {shares} shares at ${current_price:.2f} each (${total_amount:.2f} total)',
        'new_cash': round(new_cash, 2),
        'new_shares': new_shares
    })

@app.route('/api/room/<room_id>/chat', methods=['POST'])
@require_player
def chat_message(room_id):
    """Simple chat endpoint (future expansion)"""
    return jsonify({'success': True, 'message': 'Chat feature coming soon!'})

# ======================
# HTML TEMPLATES
# ======================
HTML_TEMPLATES = {
    'index': '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Market Crash - Economic Simulation Game</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #1a2a6c, #2c3e50, #4a6491);
            color: #fff;
            line-height: 1.6;
            padding: 20px;
            min-height: 100vh;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: rgba(30, 40, 70, 0.85);
            border-radius: 20px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5);
            overflow: hidden;
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        header {
            text-align: center;
            padding: 30px 20px;
            background: rgba(0, 20, 40, 0.9);
            border-bottom: 2px solid #3498db;
            position: relative;
        }
        h1 {
            font-size: 3.5rem;
            margin-bottom: 10px;
            text-shadow: 0 0 15px rgba(52, 152, 219, 0.8);
            background: linear-gradient(to right, #3498db, #2ecc71, #f1c40f);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
            letter-spacing: -1px;
        }
        .subtitle {
            font-size: 1.4rem;
            color: #bdc3c7;
            margin-top: 10px;
        }
        .game-desc {
            padding: 25px;
            background: rgba(25, 35, 60, 0.9);
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }
        .game-desc h2 {
            text-align: center;
            margin-bottom: 15px;
            color: #3498db;
            font-size: 2rem;
        }
        .game-desc p {
            margin: 12px 0;
            font-size: 1.1rem;
            text-align: center;
        }
        .features {
            display: flex;
            justify-content: space-around;
            flex-wrap: wrap;
            margin-top: 20px;
        }
        .feature {
            background: rgba(40, 50, 80, 0.7);
            border-radius: 15px;
            padding: 15px;
            width: 30%;
            min-width: 200px;
            margin: 10px;
            text-align: center;
            border: 1px solid rgba(52, 152, 219, 0.3);
            transition: transform 0.3s ease;
        }
        .feature:hover {
            transform: translateY(-5px);
            border-color: rgba(52, 152, 219, 0.6);
        }
        .feature h3 {
            color: #3498db;
            margin-bottom: 8px;
            font-size: 1.3rem;
        }
        .actions {
            padding: 30px;
            display: flex;
            flex-direction: column;
            gap: 25px;
        }
        .section-title {
            text-align: center;
            font-size: 1.8rem;
            margin-bottom: 15px;
            color: #3498db;
            position: relative;
        }
        .section-title:after {
            content: '';
            display: block;
            width: 50%;
            height: 3px;
            background: linear-gradient(to right, transparent, #3498db, transparent);
            margin: 8px auto;
        }
        .form-group {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        label {
            font-size: 1.1rem;
            margin-bottom: 5px;
            color: #bdc3c7;
        }
        input {
            padding: 15px;
            border-radius: 12px;
            border: 2px solid rgba(52, 152, 219, 0.4);
            background: rgba(20, 30, 50, 0.8);
            color: white;
            font-size: 1.2rem;
            transition: all 0.3s;
        }
        input:focus {
            outline: none;
            border-color: #3498db;
            box-shadow: 0 0 0 3px rgba(52, 152, 219, 0.2);
        }
        .btn {
            background: linear-gradient(to right, #3498db, #2980b9);
            color: white;
            border: none;
            padding: 18px 30px;
            font-size: 1.3rem;
            border-radius: 15px;
            cursor: pointer;
            transition: all 0.3s;
            font-weight: bold;
            letter-spacing: 1px;
            text-transform: uppercase;
            position: relative;
            overflow: hidden;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.4);
        }
        .btn:active {
            transform: translateY(1px);
        }
        .btn-create {
            background: linear-gradient(to right, #2ecc71, #27ae60);
        }
        .btn-join {
            background: linear-gradient(to right, #9b59b6, #8e44ad);
        }
        .btn:hover {
            opacity: 0.95;
        }
        .btn:after {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: rgba(255, 255, 255, 0.1);
            transform: rotate(30deg);
            transition: all 0.6s;
        }
        .btn:hover:after {
            transform: rotate(30deg) translate(50%, 50%);
        }
        .room-id-example {
            text-align: center;
            margin-top: 8px;
            color: #f1c40f;
            font-style: italic;
            font-size: 0.9rem;
        }
        footer {
            text-align: center;
            padding: 20px;
            color: #7f8c8d;
            font-size: 0.9rem;
            border-top: 1px solid rgba(255, 255, 255, 0.1);
            margin-top: 10px;
        }
        @media (max-width: 600px) {
            .actions { padding: 20px; }
            h1 { font-size: 2.5rem; }
            .subtitle { font-size: 1.1rem; }
            .feature { width: 100%; }
            .btn { padding: 15px; font-size: 1.1rem; }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>MARKET CRASH</h1>
            <div class="subtitle">Can you beat the market before it collapses?</div>
        </header>
        
        <section class="game-desc">
            <h2>How to Play</h2>
            <p>💰 Start with $1,000 cash and zero shares</p>
            <p>📈 Buy low, sell high as the market fluctuates every 10 seconds</p>
            <p>⚠️ Watch for crash warnings - the market can collapse at any moment!</p>
            <p>🏆 Highest portfolio value when the game ends wins</p>
            
            <div class="features">
                <div class="feature">
                    <h3>Real-time Market</h3>
                    <p>Dynamic price movements with realistic events</p>
                </div>
                <div class="feature">
                    <h3>Multiplayer</h3>
                    <p>Compete against friends in private rooms</p>
                </div>
                <div class="feature">
                    <h3>Strategic Depth</h3>
                    <p>Risk management separates winners from losers</p>
                </div>
            </div>
        </section>
        
        <section class="actions">
            <div>
                <div class="section-title">Create New Room</div>
                <form action="{{ url_for('create_room') }}" method="post">
                    <div class="form-group">
                        <label for="player_name_create">Your Trader Name</label>
                        <input type="text" id="player_name_create" name="player_name" required 
                               placeholder="Enter your name (2-15 characters)" maxlength="15" minlength="2">
                    </div>
                    <button type="submit" class="btn btn-create">Create Room &raquo;</button>
                </form>
            </div>
            
            <div>
                <div class="section-title">Join Existing Room</div>
                <form action="{{ url_for('join_room') }}" method="post">
                    <div class="form-group">
                        <label for="room_id">Room ID</label>
                        <input type="text" id="room_id" name="room_id" required 
                               placeholder="Enter 6-character room ID" maxlength="6" minlength="6" pattern="[A-Z0-9]{6}">
                        <div class="room-id-example">Example: A7B9C2</div>
                    </div>
                    <div class="form-group">
                        <label for="player_name_join">Your Trader Name</label>
                        <input type="text" id="player_name_join" name="player_name" required 
                               placeholder="Enter your name (2-15 characters)" maxlength="15" minlength="2">
                    </div>
                    <button type="submit" class="btn btn-join">Join Room &raquo;</button>
                </form>
            </div>
        </section>
        
        <footer>
            <p>Market Crash &copy; 2026 | Economic Simulation Game | Database: {{ db_path }}</p>
            <p>Flask Server Running on Port 8086</p>
        </footer>
    </div>
    
    <script>
        // Auto-uppercase room ID input
        document.getElementById('room_id')?.addEventListener('input', function(e) {
            e.target.value = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '');
        });
        
        // Form validation
        document.querySelectorAll('form').forEach(form => {
            form.addEventListener('submit', function(e) {
                const playerName = this.querySelector('[name="player_name"]').value.trim();
                if (playerName.length < 2 || playerName.length > 15) {
                    e.preventDefault();
                    alert('Player name must be 2-15 characters long');
                    return;
                }
                
                if (this.querySelector('[name="room_id"]')) {
                    const roomId = this.querySelector('[name="room_id"]').value.trim();
                    if (!/^[A-Z0-9]{6}$/.test(roomId)) {
                        e.preventDefault();
                        alert('Room ID must be exactly 6 uppercase letters/numbers');
                        return;
                    }
                }
            });
        });
    </script>
</body>
</html>
    ''',
    
    'room': '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Market Crash - Room {{ room_id }}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #0c2461, #1e3799, #4a6491);
            color: #fff;
            line-height: 1.6;
            padding: 15px;
            min-height: 100vh;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        header {
            text-align: center;
            padding: 20px 0;
            margin-bottom: 25px;
            position: relative;
        }
        .room-header {
            background: rgba(15, 35, 70, 0.92);
            border-radius: 20px;
            padding: 20px;
            box-shadow: 0 8px 25px rgba(0, 0, 0, 0.4);
            border: 1px solid rgba(255, 255, 255, 0.15);
            position: relative;
            overflow: hidden;
        }
        .room-header:before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle, rgba(52, 152, 219, 0.15) 0%, transparent 70%);
            z-index: 0;
        }
        .room-id {
            font-size: 2.8rem;
            font-weight: bold;
            letter-spacing: 3px;
            margin: 10px 0;
            background: linear-gradient(to right, #3498db, #2ecc71, #f1c40f);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
            text-shadow: 0 0 10px rgba(52, 152, 219, 0.5);
            position: relative;
            z-index: 1;
        }
        .status-bar {
            background: rgba(25, 45, 85, 0.95);
            border-radius: 15px;
            padding: 15px;
            margin: 20px 0;
            text-align: center;
            border: 1px solid rgba(52, 152, 219, 0.4);
            position: relative;
            z-index: 1;
        }
        .status-message {
            font-size: 1.6rem;
            font-weight: bold;
            min-height: 30px;
            color: #f1c40f;
        }
        .crashed .status-message { color: #e74c3c; }
        .completed .status-message { color: #2ecc71; }
        .countdown {
            font-size: 1.4rem;
            margin-top: 8px;
            color: #e74c3c;
            font-weight: bold;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 25px;
            margin-bottom: 25px;
        }
        .card {
            background: rgba(25, 45, 85, 0.92);
            border-radius: 20px;
            padding: 25px;
            box-shadow: 0 8px 25px rgba(0, 0, 0, 0.35);
            border: 1px solid rgba(255, 255, 255, 0.1);
            transition: transform 0.3s ease;
        }
        .card:hover {
            transform: translateY(-5px);
            border-color: rgba(52, 152, 219, 0.5);
        }
        .card-title {
            font-size: 1.8rem;
            margin-bottom: 20px;
            text-align: center;
            color: #3498db;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
        }
        .card-title i { font-size: 1.5em; }
        .portfolio-stats {
            text-align: center;
        }
        .stat-label {
            font-size: 1.1rem;
            color: #bdc3c7;
            margin-bottom: 8px;
        }
        .stat-value {
            font-size: 2.5rem;
            font-weight: bold;
            margin: 10px 0;
        }
        .cash { color: #2ecc71; }
        .shares { color: #3498db; }
        .value { color: #f1c40f; }
        .price-display {
            font-size: 3.5rem;
            font-weight: bold;
            text-align: center;
            margin: 15px 0;
            background: linear-gradient(to right, #e74c3c, #f39c12, #2ecc71);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
            text-shadow: 0 0 15px rgba(255, 255, 255, 0.3);
        }
        .chart-container {
            position: relative;
            height: 250px;
            margin-top: 15px;
        }
        .leaderboard-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }
        .leaderboard-table th {
            background: rgba(52, 152, 219, 0.25);
            padding: 12px 15px;
            text-align: left;
            font-weight: bold;
            color: #3498db;
        }
        .leaderboard-table td {
            padding: 12px 15px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }
        .leaderboard-table tr:hover td {
            background: rgba(255, 255, 255, 0.08);
        }
        .current-player {
            background: rgba(52, 152, 219, 0.15) !important;
            border-left: 4px solid #3498db;
        }
        .rank {
            font-weight: bold;
            width: 40px;
        }
        .rank-1 { color: #f1c40f; }
        .rank-2 { color: #bdc3c7; }
        .rank-3 { color: #cd7f32; }
        .transactions-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
            font-size: 0.95rem;
        }
        .transactions-table th {
            background: rgba(40, 60, 90, 0.8);
            padding: 10px 12px;
            text-align: left;
            font-weight: bold;
            color: #bdc3c7;
            font-size: 0.9rem;
        }
        .transactions-table td {
            padding: 8px 12px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        }
        .buy { color: #2ecc71; font-weight: bold; }
        .sell { color: #e74c3c; font-weight: bold; }
        .action-buttons {
            display: flex;
            gap: 20px;
            margin-top: 25px;
            justify-content: center;
        }
        .btn-action {
            padding: 20px 45px;
            font-size: 1.5rem;
            font-weight: bold;
            border: none;
            border-radius: 18px;
            cursor: pointer;
            transition: all 0.3s;
            position: relative;
            overflow: hidden;
            letter-spacing: 1px;
            min-width: 200px;
            box-shadow: 0 6px 15px rgba(0, 0, 0, 0.3);
        }
        .btn-buy {
            background: linear-gradient(to right, #27ae60, #2ecc71);
            color: white;
        }
        .btn-sell {
            background: linear-gradient(to right, #c0392b, #e74c3c);
            color: white;
        }
        .btn-action:hover {
            transform: translateY(-3px);
            box-shadow: 0 8px 20px rgba(0, 0, 0, 0.4);
        }
        .btn-action:active {
            transform: translateY(1px);
        }
        .btn-action:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        .btn-action:after {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: rgba(255, 255, 255, 0.15);
            transform: rotate(30deg);
            transition: all 0.6s;
        }
        .btn-action:hover:after {
            transform: rotate(30deg) translate(50%, 50%);
        }
        .game-over {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 10, 25, 0.95);
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            z-index: 1000;
            text-align: center;
            padding: 20px;
            display: none;
        }
        .game-over.show {
            display: flex;
        }
        .game-over h2 {
            font-size: 4rem;
            margin-bottom: 30px;
            color: #e74c3c;
            text-shadow: 0 0 20px rgba(231, 76, 60, 0.7);
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0% { text-shadow: 0 0 10px rgba(231, 76, 60, 0.7); }
            50% { text-shadow: 0 0 25px rgba(231, 76, 60, 1); }
            100% { text-shadow: 0 0 10px rgba(231, 76, 60, 0.7); }
        }
        .winner-message {
            font-size: 2.5rem;
            margin: 20px 0;
            color: #f1c40f;
            text-shadow: 0 0 10px rgba(241, 196, 15, 0.7);
            background: linear-gradient(to right, #f1c40f, #e67e22);
            -webkit-background-clip: text;
            background-clip: text;
            color: transparent;
            font-weight: bold;
        }
        .final-leaderboard {
            background: rgba(30, 50, 90, 0.9);
            border-radius: 20px;
            padding: 30px;
            max-width: 600px;
            width: 100%;
            margin-top: 20px;
            border: 2px solid rgba(241, 196, 15, 0.3);
        }
        .final-leaderboard ol {
            text-align: left;
            margin-top: 15px;
            font-size: 1.4rem;
        }
        .final-leaderboard li {
            padding: 12px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }
        .final-leaderboard li:first-child {
            color: #f1c40f;
            font-weight: bold;
            font-size: 1.6rem;
        }
        .final-leaderboard li:nth-child(2) {
            color: #bdc3c7;
        }
        .final-leaderboard li:nth-child(3) {
            color: #cd7f32;
        }
        .btn-home {
            background: linear-gradient(to right, #3498db, #2980b9);
            color: white;
            border: none;
            padding: 18px 60px;
            font-size: 1.6rem;
            border-radius: 50px;
            margin-top: 30px;
            cursor: pointer;
            transition: all 0.3s;
            font-weight: bold;
            letter-spacing: 2px;
            box-shadow: 0 8px 25px rgba(0, 0, 0, 0.4);
        }
        .btn-home:hover {
            transform: translateY(-3px);
            box-shadow: 0 12px 30px rgba(0, 0, 0, 0.5);
            background: linear-gradient(to right, #2980b9, #3498db);
        }
        .message-container {
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 1000;
            max-width: 400px;
        }
        .message {
            padding: 15px 25px;
            border-radius: 12px;
            margin-bottom: 10px;
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.3);
            animation: slideIn 0.3s, fadeOut 0.5s 2.5s forwards;
            word-wrap: break-word;
        }
        @keyframes slideIn {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }
        @keyframes fadeOut {
            from { opacity: 1; }
            to { opacity: 0; }
        }
        .message.success {
            background: linear-gradient(to right, #27ae60, #2ecc71);
            border-left: 5px solid #27ae60;
        }
        .message.error {
            background: linear-gradient(to right, #c0392b, #e74c3c);
            border-left: 5px solid #c0392b;
        }
        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
            .room-id { font-size: 2.2rem; }
            .price-display { font-size: 2.8rem; }
            .action-buttons { flex-direction: column; }
            .btn-action { width: 100%; }
            .card { padding: 20px; }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="room-header">
                <div class="room-id">{{ room_id }}</div>
                <div class="status-bar {{ 'crashed' if crash_occurred else 'completed' if round_number >= 10 else '' }}">
                    <div class="status-message" id="status-message">
                        {% if crash_occurred %}
                            MARKET CRASHED! Game Over
                        {% elif round_number >= 10 %}
                            Game Completed - Final Results
                        {% elif round_number == 0 %}
                            Waiting for players... Game starts soon!
                        {% else %}
                            Round {{ round_number }} of 10
                        {% endif %}
                    </div>
                    <div class="countdown" id="countdown">10 seconds until next update</div>
                </div>
            </div>
        </header>
        
        <div class="grid">
            <div class="card">
                <div class="card-title">📈 LIVE MARKET</div>
                <div class="price-display" id="current-price">${{ "%.2f"|format(current_price) }}</div>
                <div class="chart-container">
                    <canvas id="price-chart"></canvas>
                </div>
                <div style="text-align: center; margin-top: 10px; font-style: italic; color: #bdc3c7;">
                    Price history (last 10 rounds)
                </div>
            </div>
            
            <div class="card">
                <div class="card-title">💼 YOUR PORTFOLIO</div>
                <div class="portfolio-stats">
                    <div class="stat-label">CASH</div>
                    <div class="stat-value cash" id="player-cash">${{ "%.2f"|format(initial_cash) }}</div>
                    
                    <div class="stat-label" style="margin-top: 20px;">SHARES HELD</div>
                    <div class="stat-value shares" id="player-shares">{{ initial_shares }}</div>
                    
                    <div class="stat-label" style="margin-top: 20px; color: #f1c40f;">TOTAL VALUE</div>
                    <div class="stat-value value" id="total-value">${{ "%.2f"|format(initial_cash + initial_shares * current_price) }}</div>
                </div>
                <div class="action-buttons">
                    <button class="btn-action btn-buy" id="buy-btn" {% if not is_active or crash_occurred %}disabled{% endif %}>
                        BUY SHARES
                    </button>
                    <button class="btn-action btn-sell" id="sell-btn" {% if not is_active or crash_occurred %}disabled{% endif %}>
                        SELL SHARES
                    </button>
                </div>
            </div>
            
            <div class="card">
                <div class="card-title">🏆 LEADERBOARD</div>
                <table class="leaderboard-table">
                    <thead>
                        <tr>
                            <th class="rank">RANK</th>
                            <th>TRADER</th>
                            <th>VALUE</th>
                        </tr>
                    </thead>
                    <tbody id="leaderboard-body">
                        <tr>
                            <td class="rank rank-1">1</td>
                            <td>{{ player_name }}</td>
                            <td>${{ "%.2f"|format(initial_cash + initial_shares * current_price) }}</td>
                        </tr>
                        <tr>
                            <td class="rank rank-2">2</td>
                            <td>Player2</td>
                            <td>$980.00</td>
                        </tr>
                        <tr>
                            <td class="rank rank-3">3</td>
                            <td>Player3</td>
                            <td>$950.00</td>
                        </tr>
                    </tbody>
                </table>
            </div>
            
            <div class="card">
                <div class="card-title">📊 RECENT TRANSACTIONS</div>
                <table class="transactions-table">
                    <thead>
                        <tr>
                            <th>TRADER</th>
                            <th>TYPE</th>
                            <th>SHARES</th>
                            <th>PRICE</th>
                        </tr>
                    </thead>
                    <tbody id="transactions-body">
                        <tr>
                            <td>{{ player_name }}</td>
                            <td class="buy">BUY</td>
                            <td>5</td>
                            <td>$100.00</td>
                        </tr>
                        <tr>
                            <td>Player2</td>
                            <td class="sell">SELL</td>
                            <td>3</td>
                            <td>$102.50</td>
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>
    
    <div class="game-over" id="game-over">
        <h2 id="game-result-title">MARKET CRASHED!</h2>
        <div class="winner-message" id="winner-message">Loading winner...</div>
        <div class="final-leaderboard">
            <div style="font-size: 1.8rem; margin-bottom: 15px; color: #bdc3c7;">Final Rankings</div>
            <ol id="final-rankings">
                <li>Loading results...</li>
            </ol>
        </div>
        <button class="btn-home" onclick="window.location.href='/'">BACK TO HOME</button>
    </div>
    
    <div class="message-container" id="message-container"></div>
    
    <script>
        // Game state
        const ROOM_ID = "{{ room_id }}";
        const INITIAL_PRICE = {{ current_price }};
        const IS_ACTIVE = {{ 1 if is_active else 0 }};
        const CRASH_OCCURRED = {{ 1 if crash_occurred else 0 }};
        let countdown = 10;
        let countdownInterval;
        let pollInterval;
        let priceChart;
        
        // Initialize chart
        function initChart() {
            const ctx = document.getElementById('price-chart').getContext('2d');
            priceChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: Array.from({length: 10}, (_, i) => `Round ${i+1}`),
                    datasets: [{
                        label: 'Stock Price ($)',
                        data: Array(10).fill(INITIAL_PRICE),
                        borderColor: '#3498db',
                        backgroundColor: 'rgba(52, 152, 219, 0.1)',
                        borderWidth: 3,
                        pointBackgroundColor: '#3498db',
                        pointRadius: 5,
                        pointHoverRadius: 8,
                        fill: true,
                        tension: 0.3
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: function(context) {
                                    return `$${context.parsed.y.toFixed(2)}`;
                                }
                            }
                        }
                    },
                    scales: {
                        y: {
                            beginAtZero: false,
                            grid: { color: 'rgba(255, 255, 255, 0.1)' },
                            ticks: { color: '#bdc3c7' }
                        },
                        x: {
                            grid: { color: 'rgba(255, 255, 255, 0.1)' },
                            ticks: { color: '#bdc3c7' }
                        }
                    }
                }
            });
        }
        
        // Update countdown timer
        function updateCountdown() {
            document.getElementById('countdown').textContent = `${countdown} seconds until next update`;
            countdown = countdown > 0 ? countdown - 1 : 10;
        }
        
        // Show message notification
        function showMessage(message, type = 'success') {
            const container = document.getElementById('message-container');
            const div = document.createElement('div');
            div.className = `message ${type}`;
            div.textContent = message;
            container.appendChild(div);
            
            // Auto-remove after animation
            setTimeout(() => {
                div.remove();
            }, 3000);
        }
        
        // Buy shares dialog
        document.getElementById('buy-btn').addEventListener('click', () => {
            const shares = prompt('How many shares would you like to BUY?\nCurrent price: $' + 
                document.getElementById('current-price').textContent.replace('$', ''));
            if (shares && !isNaN(shares) && parseInt(shares) > 0) {
                fetch(`/api/room/${ROOM_ID}/buy`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({shares: parseInt(shares)})
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        showMessage(data.message, 'success');
                    } else {
                        showMessage(data.error, 'error');
                    }
                })
                .catch(error => {
                    showMessage('Transaction failed. Please try again.', 'error');
                    console.error('Error:', error);
                });
            }
        });
        
        // Sell shares dialog
        document.getElementById('sell-btn').addEventListener('click', () => {
            const currentShares = parseInt(document.getElementById('player-shares').textContent);
            if (currentShares === 0) {
                showMessage('You have no shares to sell!', 'error');
                return;
            }
            
            const shares = prompt(`How many shares would you like to SELL? (You own ${currentShares})\nCurrent price: $` + 
                document.getElementById('current-price').textContent.replace('$', ''));
            if (shares && !isNaN(shares) && parseInt(shares) > 0 && parseInt(shares) <= currentShares) {
                fetch(`/api/room/${ROOM_ID}/sell`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({shares: parseInt(shares)})
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        showMessage(data.message, 'success');
                    } else {
                        showMessage(data.error, 'error');
                    }
                })
                .catch(error => {
                    showMessage('Transaction failed. Please try again.', 'error');
                    console.error('Error:', error);
                });
            } else if (shares) {
                showMessage(`Invalid amount. You own ${currentShares} shares.`, 'error');
            }
        });
        
        // Poll game state
        function pollGameState() {
            fetch(`/api/room/${ROOM_ID}/state`)
                .then(response => response.json())
                .then(data => {
                    if (!data.success) {
                        if (data.error.includes('Session expired')) {
                            window.location.href = '/';
                        }
                        return;
                    }
                    
                    // Update price display
                    document.getElementById('current-price').textContent = '$' + data.room.current_price.toFixed(2);
                    
                    // Update player portfolio
                    document.getElementById('player-cash').textContent = '$' + data.player.cash.toFixed(2);
                    document.getElementById('player-shares').textContent = data.player.shares;
                    document.getElementById('total-value').textContent = '$' + data.player.total_value.toFixed(2);
                    
                    // Update status message
                    document.getElementById('status-message').textContent = data.room.status_message;
                    const statusBar = document.querySelector('.status-bar');
                    statusBar.className = 'status-bar';
                    if (data.room.crash_occurred) {
                        statusBar.classList.add('crashed');
                    } else if (!data.room.is_active && data.room.round_number >= data.room.max_rounds) {
                        statusBar.classList.add('completed');
                    }
                    
                    // Update countdown
                    countdown = Math.ceil(data.room.time_until_update);
                    
                    // Update leaderboard
                    const leaderboardBody = document.getElementById('leaderboard-body');
                    leaderboardBody.innerHTML = '';
                    data.leaderboard.forEach((player, index) => {
                        const row = document.createElement('tr');
                        if (player.is_current) row.classList.add('current-player');
                        row.innerHTML = `
                            <td class="rank ${index < 3 ? 'rank-' + (index+1) : ''}">${index+1}</td>
                            <td>${player.player_name}</td>
                            <td>$${player.total_value.toFixed(2)}</td>
                        `;
                        leaderboardBody.appendChild(row);
                    });
                    
                    // Update transactions
                    const transactionsBody = document.getElementById('transactions-body');
                    transactionsBody.innerHTML = '';
                    data.transactions.forEach(tx => {
                        const row = document.createElement('tr');
                        row.innerHTML = `
                            <td>${tx.player_name}</td>
                            <td class="${tx.type === 'BUY' ? 'buy' : 'sell'}">${tx.type}</td>
                            <td>${tx.shares}</td>
                            <td>$${tx.price.toFixed(2)}</td>
                        `;
                        transactionsBody.appendChild(row);
                    });
                    
                    // Update chart
                    if (priceChart && data.price_history.length > 0) {
                        // Prepare data for chart
                        const labels = data.price_history.map(p => `Round ${p.round}`);
                        const prices = data.price_history.map(p => p.price);
                        
                        // Update chart colors based on last event
                        const lastEvent = data.price_history[data.price_history.length - 1].event;
                        let borderColor = '#3498db';
                        if (lastEvent === 'CRASH' || lastEvent === 'CRASH_WARNING') borderColor = '#e74c3c';
                        else if (lastEvent === 'SURGE' || lastEvent === 'RISE') borderColor = '#2ecc71';
                        else if (lastEvent === 'DROP') borderColor = '#e67e22';
                        
                        priceChart.data.labels = labels;
                        priceChart.data.datasets[0].data = prices;
                        priceChart.data.datasets[0].borderColor = borderColor;
                        priceChart.data.datasets[0].pointBackgroundColor = borderColor;
                        priceChart.update();
                    }
                    
                    // Check for game over
                    if (!data.room.is_active && (data.room.crash_occurred || data.room.round_number >= data.room.max_rounds)) {
                        showGameOver(data);
                    }
                    
                })
                .catch(error => {
                    console.error('Polling error:', error);
                    // Don't redirect on polling errors to avoid disrupting gameplay
                });
        }
        
        // Show game over screen
        function showGameOver(data) {
            clearInterval(pollInterval);
            clearInterval(countdownInterval);
            
            const gameOver = document.getElementById('game-over');
            const title = document.getElementById('game-result-title');
            const winnerMsg = document.getElementById('winner-message');
            const rankings = document.getElementById('final-rankings');
            
            // Set title and message
            if (data.room.crash_occurred) {
                title.textContent = '💥 MARKET CRASHED! 💥';
                title.style.color = '#e74c3c';
                title.style.textShadow = '0 0 20px rgba(231, 76, 60, 0.8)';
            } else {
                title.textContent = '🏆 GAME COMPLETED! 🏆';
                title.style.color = '#2ecc71';
                title.style.textShadow = '0 0 20px rgba(46, 204, 113, 0.8)';
            }
            
            // Set winner message
            if (data.leaderboard.length > 0) {
                const winner = data.leaderboard[0];
                winnerMsg.textContent = `${winner.player_name} wins with $${winner.total_value.toFixed(2)}!`;
            }
            
            // Set final rankings
            rankings.innerHTML = '';
            data.leaderboard.forEach((player, index) => {
                const li = document.createElement('li');
                li.textContent = `${player.player_name}: $${player.total_value.toFixed(2)}`;
                if (index === 0) li.style.fontSize = '1.8rem';
                rankings.appendChild(li);
            });
            
            // Show game over screen
            setTimeout(() => {
                gameOver.classList.add('show');
            }, 1000);
        }
        
        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            initChart();
            updateCountdown();
            countdownInterval = setInterval(updateCountdown, 1000);
            pollGameState(); // Initial poll
            pollInterval = setInterval(pollGameState, 2000);
            
            // Disable buttons if game is over
            if (!IS_ACTIVE || CRASH_OCCURRED) {
                document.getElementById('buy-btn').disabled = true;
                document.getElementById('sell-btn').disabled = true;
            }
        });
        
        // Cleanup on unload
        window.addEventListener('beforeunload', () => {
            clearInterval(pollInterval);
            clearInterval(countdownInterval);
        });
    </script>
</body>
</html>
    '''
}

# ======================
# MAIN EXECUTION
# ======================
if __name__ == '__main__':
    # Initialize database
    init_db()
    
    # Start market simulation engine in background thread
    simulation_thread = threading.Thread(target=market_simulation_loop, daemon=True)
    simulation_thread.start()
    
    # Start Flask application
    print("="*60)
    print("🚀 MARKET CRASH GAME SERVER STARTING")
    print(f"📁 Database: {DB_PATH}")
    print(f"🌐 Access at: http://localhost:8086")
    print(f"⏱️  Market updates every 10 seconds")
    print(f"👥 Create rooms and compete with friends!")
    print("="*60)
    
    try:
        app.run(host='0.0.0.0', port=8086, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\n\n✓ Server stopped by user")
    except Exception as e:
        print(f"\n✗ Fatal error: {str(e)}")
        sys.exit(1)
