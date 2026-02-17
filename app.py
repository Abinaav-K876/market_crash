#!/usr/bin/env python3
import os
import sys
import sqlite3
import threading
import time
import random
from functools import wraps
from flask import Flask, render_template, request, session, jsonify, redirect, url_for, g

# ======================
# CONFIGURATION
# ======================
# Database path as requested
DB_DIR = '/opt/extra1_1tb/database'
DB_PATH = os.path.join(DB_DIR, 'market_crash.db')

# Ensure directory exists
try:
    os.makedirs(DB_DIR, exist_ok=True)
except PermissionError:
    print(f"WARNING: Cannot create {DB_DIR}. Please run as sudo or change DB_PATH in app.py")
    # Fallback to local directory if permission denied
    DB_PATH = 'market_crash_local.db'

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.urandom(24)
app.config['PERMANENT_SESSION_LIFETIME'] = 3600


# ======================
# DATABASE SETUP
# ======================
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error):
    if hasattr(g, 'db'):
        g.db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    c = db.cursor()
    c.execute("PRAGMA foreign_keys = ON")

    c.execute('''CREATE TABLE IF NOT EXISTS rooms (
        room_id TEXT PRIMARY KEY,
        current_price REAL NOT NULL DEFAULT 100.0,
        round_number INTEGER NOT NULL DEFAULT 0,
        is_active INTEGER NOT NULL DEFAULT 1,
        crash_occurred INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS players (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_id TEXT NOT NULL,
        player_name TEXT NOT NULL,
        cash REAL NOT NULL DEFAULT 1000.0,
        shares_held INTEGER NOT NULL DEFAULT 0,
        is_active INTEGER NOT NULL DEFAULT 1,
        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE CASCADE
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS transactions (
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
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS price_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_id TEXT NOT NULL,
        round_number INTEGER NOT NULL,
        price REAL NOT NULL,
        event_type TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE CASCADE
    )''')

    c.execute('CREATE INDEX IF NOT EXISTS idx_rooms_active ON rooms(is_active, crash_occurred, round_number)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_players_room ON players(room_id, is_active)')

    db.commit()
    db.close()
    print(f"✓ Database initialized at {DB_PATH}")


# ======================
# GAME ENGINE
# ======================
class MarketEngine:
    MAX_ROUNDS = 10
    CRASH_PROBABILITY = 0.10
    BIG_MOVE_PROBABILITY = 0.20
    NORMAL_VOLATILITY = (0.90, 1.10)
    BIG_VOLATILITY = (0.75, 1.25)

    @staticmethod
    def calculate_new_price(current_price, round_num):
        if random.random() < MarketEngine.CRASH_PROBABILITY:
            return 0.01, "CRASH", True

        if round_num > 7:
            volatility = (0.80, 1.30)
        elif round_num > 4:
            volatility = (0.85, 1.20)
        else:
            volatility = MarketEngine.NORMAL_VOLATILITY

        if random.random() < MarketEngine.BIG_MOVE_PROBABILITY:
            volatility = MarketEngine.BIG_VOLATILITY

        factor = random.uniform(volatility[0], volatility[1])
        new_price = max(0.01, round(current_price * factor, 2))

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
    print("✓ Market simulation engine started")
    while True:
        time.sleep(10)
        try:
            db = sqlite3.connect(DB_PATH)
            db.row_factory = sqlite3.Row
            c = db.cursor()
            c.execute('''SELECT room_id, current_price, round_number FROM rooms 
                        WHERE is_active=1 AND crash_occurred=0 AND round_number < ?''',
                      (MarketEngine.MAX_ROUNDS,))
            rooms = c.fetchall()

            for room in rooms:
                room_id = room['room_id']
                price = room['current_price']
                round_num = room['round_number'] + 1

                new_price, event, is_crash = MarketEngine.calculate_new_price(price, round_num)

                is_active = 0 if (is_crash or round_num >= MarketEngine.MAX_ROUNDS) else 1
                crash_occurred = 1 if is_crash else 0

                c.execute('''UPDATE rooms SET current_price=?, round_number=?, is_active=?, 
                            crash_occurred=?, last_updated=CURRENT_TIMESTAMP WHERE room_id=?''',
                          (new_price, round_num, is_active, crash_occurred, room_id))

                c.execute('''INSERT INTO price_history (room_id, round_number, price, event_type) 
                            VALUES (?, ?, ?, ?)''', (room_id, round_num, new_price, event))

                if is_crash:
                    print(f"!!! MARKET CRASH in room {room_id} at round {round_num} !!!")

            db.commit()
            db.close()
        except Exception as e:
            print(f"✗ Market sim error: {e}")
            if 'db' in locals():
                try:
                    db.close()
                except:
                    pass


# ======================
# HELPERS
# ======================
def require_player(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        room_id = kwargs.get('room_id')
        if not room_id and request.is_json:
            room_id = request.json.get('room_id')

        player_id = session.get('player_id')

        if not player_id or not room_id:
            return jsonify({'error': 'Session expired'}), 401

        db = get_db()
        c = db.cursor()
        c.execute('''SELECT p.*, r.is_active, r.crash_occurred, r.current_price 
                    FROM players p JOIN rooms r ON p.room_id=r.room_id 
                    WHERE p.id=? AND p.room_id=? AND p.is_active=1''', (player_id, room_id))
        player = c.fetchone()

        if not player:
            session.clear()
            return jsonify({'error': 'Player not found'}), 403

        request.player = player
        request.room = {
            'is_active': player['is_active'],
            'crash_occurred': player['crash_occurred'],
            'current_price': player['current_price']
        }
        return f(*args, **kwargs)

    return decorated


def generate_room_id():
    while True:
        rid = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=6))
        db = get_db()
        if not db.execute("SELECT 1 FROM rooms WHERE room_id=?", (rid,)).fetchone():
            return rid


# ======================
# ROUTES
# ======================
@app.route('/')
def index():
    return render_template('index.html', db_path=DB_PATH)


@app.route('/create_room', methods=['POST'])
def create_room():
    name = request.form.get('player_name', '').strip()
    if not (2 <= len(name) <= 15):
        return redirect('/')

    room_id = generate_room_id()
    db = get_db()
    db.execute('INSERT INTO rooms (room_id) VALUES (?)', (room_id,))
    db.execute('INSERT INTO players (room_id, player_name) VALUES (?, ?)', (room_id, name))
    player_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.commit()

    session.permanent = True
    session['player_id'] = player_id
    session['room_id'] = room_id
    return redirect(url_for('room', room_id=room_id))


@app.route('/join_room', methods=['POST'])
def join_room():
    room_id = request.form.get('room_id', '').strip().upper()
    name = request.form.get('player_name', '').strip()

    if not room_id or not (2 <= len(name) <= 15):
        return redirect('/')

    db = get_db()
    room = db.execute('''SELECT * FROM rooms WHERE room_id=? AND is_active=1 
                        AND crash_occurred=0 AND round_number=0''', (room_id,)).fetchone()

    if not room:
        return redirect('/')

    db.execute('INSERT INTO players (room_id, player_name) VALUES (?, ?)', (room_id, name))
    player_id = db.execute('SELECT last_insert_rowid()').fetchone()[0]
    db.commit()

    session.permanent = True
    session['player_id'] = player_id
    session['room_id'] = room_id
    return redirect(url_for('room', room_id=room_id))


@app.route('/room/<room_id>')
def room(room_id):
    player_id = session.get('player_id')
    if not player_id:
        return redirect('/')

    db = get_db()
    player = db.execute('''SELECT p.*, r.round_number, r.is_active, r.crash_occurred, r.current_price 
                          FROM players p JOIN rooms r ON p.room_id=r.room_id 
                          WHERE p.id=? AND p.room_id=? AND p.is_active=1''',
                        (player_id, room_id)).fetchone()

    if not player:
        session.clear()
        return redirect('/')

    return render_template('room.html',
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
    db = get_db()
    room = db.execute('SELECT * FROM rooms WHERE room_id=?', (room_id,)).fetchone()
    if not room:
        return jsonify({'error': 'Room not found'}), 404

    players = db.execute('''SELECT id, player_name, cash, shares_held FROM players 
                           WHERE room_id=? AND is_active=1 ORDER BY (cash + shares_held * ?) DESC''',
                         (room_id, room['current_price'])).fetchall()

    leaderboard = [{
        'player_name': p['player_name'],
        'cash': round(p['cash'], 2),
        'shares': p['shares_held'],
        'total_value': round(p['cash'] + p['shares_held'] * room['current_price'], 2),
        'is_current': p['id'] == request.player['id']
    } for p in players]

    txns = db.execute('''SELECT t.*, p.player_name FROM transactions t 
                        JOIN players p ON t.player_id=p.id WHERE t.room_id=? 
                        ORDER BY t.timestamp DESC LIMIT 8''', (room_id,)).fetchall()

    history = db.execute('''SELECT round_number, price, event_type FROM price_history 
                           WHERE room_id=? ORDER BY round_number DESC LIMIT 10''',
                         (room_id,)).fetchall()

    chart_data = [{'round': h['round_number'], 'price': round(h['price'], 2), 'event': h['event_type']}
                  for h in reversed(history)]

    if room['crash_occurred']:
        status = "MARKET CRASHED! Game over."
    elif room['round_number'] >= MarketEngine.MAX_ROUNDS:
        status = f"Game completed {MarketEngine.MAX_ROUNDS} rounds!"
    elif room['round_number'] == 0:
        status = "Waiting for players... Game starts soon!"
    else:
        status = f"Round {room['round_number']} of {MarketEngine.MAX_ROUNDS}"

    # Calculate time until next update
    try:
        last_updated = room['last_updated']
        # Handle datetime object vs string
        if isinstance(last_updated, str):
            from datetime import datetime
            last_updated = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
        time_diff = time.time() - last_updated.timestamp()
        time_until = max(0, 10 - (time_diff % 10))
    except:
        time_until = 10

    return jsonify({
        'success': True,
        'room': {
            'current_price': round(room['current_price'], 2),
            'round_number': room['round_number'],
            'max_rounds': MarketEngine.MAX_ROUNDS,
            'is_active': room['is_active'],
            'crash_occurred': room['crash_occurred'],
            'status_message': status,
            'time_until_update': time_until
        },
        'player': {
            'cash': round(request.player['cash'], 2),
            'shares': request.player['shares_held'],
            'total_value': round(request.player['cash'] + request.player['shares_held'] * room['current_price'], 2)
        },
        'leaderboard': leaderboard,
        'transactions': [{
            'player_name': t['player_name'],
            'type': t['type'].upper(),
            'shares': t['shares'],
            'price': round(t['price_per_share'], 2),
            'total': round(t['total_amount'], 2),
            'timestamp': t['timestamp'].strftime('%H:%M:%S') if hasattr(t['timestamp'], 'strftime') else str(
                t['timestamp'])
        } for t in txns],
        'price_history': chart_data
    })


@app.route('/api/room/<room_id>/buy', methods=['POST'])
@require_player
def buy_shares(room_id):
    if not request.is_json:
        return jsonify({'error': 'Invalid request'}), 400
    try:
        shares = int(request.json.get('shares', 0))
    except:
        return jsonify({'error': 'Invalid shares'}), 400

    if shares <= 0:
        return jsonify({'error': 'Shares must be positive'}), 400
    if not request.room['is_active'] or request.room['crash_occurred']:
        return jsonify({'error': 'Market closed'}), 400

    price = request.room['current_price']
    total = shares * price
    if request.player['cash'] < total:
        return jsonify({'error': f'Need ${total:.2f}, have ${request.player["cash"]:.2f}'}), 400

    db = get_db()
    new_cash = request.player['cash'] - total
    new_shares = request.player['shares_held'] + shares
    db.execute('UPDATE players SET cash=?, shares_held=? WHERE id=?',
               (new_cash, new_shares, request.player['id']))
    db.execute('''INSERT INTO transactions (room_id, player_id, type, shares, price_per_share, total_amount)
                 VALUES (?, ?, 'buy', ?, ?, ?)''',
               (room_id, request.player['id'], shares, price, total))
    db.commit()
    return jsonify({'success': True, 'message': f'Bought {shares} @ ${price:.2f} (${total:.2f})',
                    'new_cash': round(new_cash, 2), 'new_shares': new_shares})


@app.route('/api/room/<room_id>/sell', methods=['POST'])
@require_player
def sell_shares(room_id):
    if not request.is_json:
        return jsonify({'error': 'Invalid request'}), 400
    try:
        shares = int(request.json.get('shares', 0))
    except:
        return jsonify({'error': 'Invalid shares'}), 400

    if shares <= 0:
        return jsonify({'error': 'Shares must be positive'}), 400
    if not request.room['is_active'] or request.room['crash_occurred']:
        return jsonify({'error': 'Market closed'}), 400
    if request.player['shares_held'] < shares:
        return jsonify({'error': f'Own {request.player["shares_held"]} shares, trying to sell {shares}'}), 400

    price = request.room['current_price']
    total = shares * price
    db = get_db()
    new_cash = request.player['cash'] + total
    new_shares = request.player['shares_held'] - shares
    db.execute('UPDATE players SET cash=?, shares_held=? WHERE id=?',
               (new_cash, new_shares, request.player['id']))
    db.execute('''INSERT INTO transactions (room_id, player_id, type, shares, price_per_share, total_amount)
                 VALUES (?, ?, 'sell', ?, ?, ?)''',
               (room_id, request.player['id'], shares, price, total))
    db.commit()
    return jsonify({'success': True, 'message': f'Sold {shares} @ ${price:.2f} (${total:.2f})',
                    'new_cash': round(new_cash, 2), 'new_shares': new_shares})


if __name__ == '__main__':
    init_db()
    threading.Thread(target=market_simulation_loop, daemon=True).start()
    print("\n" + "=" * 60)
    print("🚀 MARKET CRASH GAME SERVER STARTING")
    print(f"📁 Database: {DB_PATH}")
    print(f"🌐 Access at: http://localhost:8086")
    print(f"⏱️  Market updates every 10 seconds")
    print("=" * 60 + "\n")
    app.run(host='0.0.0.0', port=8086, debug=False, threaded=True)