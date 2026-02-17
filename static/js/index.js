/**
 * MARKET CRASH PRO TERMINAL - v2.0
 * 
 * A high-performance trading simulation frontend.
 * Features:
 * - Reactive State Management
 * - Web Audio API Sound Synthesis
 * - Canvas Particle System
 * - Real-time Data Visualization
 */

/* ===========================
   CORE CONSTANTS
   =========================== */
const CONSTANTS = {
    POLL_INTERVAL: 1000,
    ANIMATION_FPS: 60,
    MAX_CHAT_HISTORY: 50,
    MAX_NEWS_HISTORY: 20,
    THEME: {
        BULL: '#00f090',
        BEAR: '#ff2a4d',
        BLUE: '#2d7ff9',
        GOLD: '#ffc107',
        BG: '#0a0b10'
    }
};

/* ===========================
   AUDIO ENGINE (Procedural Sound)
   =========================== */
class AudioEngine {
    constructor() {
        this.ctx = new (window.AudioContext || window.webkitAudioContext)();
        this.masterGain = this.ctx.createGain();
        this.masterGain.gain.value = 0.3; // Default volume
        this.masterGain.connect(this.ctx.destination);
        this.enabled = true;
    }

    playTone(freq, type, duration, vol = 1) {
        if (!this.enabled) return;
        const osc = this.ctx.createOscillator();
        const gain = this.ctx.createGain();
        
        osc.type = type;
        osc.frequency.setValueAtTime(freq, this.ctx.currentTime);
        
        gain.gain.setValueAtTime(vol, this.ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.01, this.ctx.currentTime + duration);
        
        osc.connect(gain);
        gain.connect(this.masterGain);
        
        osc.start();
        osc.stop(this.ctx.currentTime + duration);
    }

    playTick() { this.playTone(800, 'sine', 0.05, 0.2); }
    playBuy()  { this.playTone(1200, 'triangle', 0.1, 0.4); setTimeout(() => this.playTone(1600, 'triangle', 0.2, 0.4), 80); }
    playSell() { this.playTone(600, 'sawtooth', 0.1, 0.4); setTimeout(() => this.playTone(400, 'sawtooth', 0.2, 0.4), 80); }
    playAlert() { 
        this.playTone(880, 'square', 0.3, 0.5); 
        setTimeout(() => this.playTone(880, 'square', 0.3, 0.5), 400); 
    }
    playCrash() {
        if (!this.enabled) return;
        const osc = this.ctx.createOscillator();
        const gain = this.ctx.createGain();
        osc.frequency.setValueAtTime(100, this.ctx.currentTime);
        osc.frequency.exponentialRampToValueAtTime(10, this.ctx.currentTime + 2);
        gain.gain.setValueAtTime(0.8, this.ctx.currentTime);
        gain.gain.linearRampToValueAtTime(0, this.ctx.currentTime + 2);
        osc.connect(gain);
        gain.connect(this.masterGain);
        osc.start();
        osc.stop(this.ctx.currentTime + 2);
    }
    
    toggle() {
        this.enabled = !this.enabled;
        return this.enabled;
    }
}

/* ===========================
   PARTICLE SYSTEM (Background)
   =========================== */
class ParticleSystem {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');
        this.particles = [];
        this.resize();
        window.addEventListener('resize', () => this.resize());
        this.animate();
    }

    resize() {
        this.canvas.width = window.innerWidth;
        this.canvas.height = window.innerHeight;
        this.initParticles();
    }

    initParticles() {
        this.particles = [];
        const count = Math.floor((this.canvas.width * this.canvas.height) / 15000);
        for (let i = 0; i < count; i++) {
            this.particles.push({
                x: Math.random() * this.canvas.width,
                y: Math.random() * this.canvas.height,
                vx: (Math.random() - 0.5) * 0.5,
                vy: (Math.random() - 0.5) * 0.5,
                size: Math.random() * 2 + 1,
                alpha: Math.random() * 0.5
            });
        }
    }

    animate() {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        
        this.ctx.fillStyle = '#2d7ff9';
        
        for (let p of this.particles) {
            p.x += p.vx;
            p.y += p.vy;

            if (p.x < 0 || p.x > this.canvas.width) p.vx *= -1;
            if (p.y < 0 || p.y > this.canvas.height) p.vy *= -1;

            this.ctx.globalAlpha = p.alpha * 0.2;
            this.ctx.beginPath();
            this.ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
            this.ctx.fill();
        }

        // Draw connections
        this.ctx.strokeStyle = '#2d7ff9';
        this.ctx.lineWidth = 0.5;
        for (let i = 0; i < this.particles.length; i++) {
            for (let j = i + 1; j < this.particles.length; j++) {
                const dx = this.particles[i].x - this.particles[j].x;
                const dy = this.particles[i].y - this.particles[j].y;
                const dist = Math.sqrt(dx * dx + dy * dy);

                if (dist < 100) {
                    this.ctx.globalAlpha = (1 - dist / 100) * 0.1;
                    this.ctx.beginPath();
                    this.ctx.moveTo(this.particles[i].x, this.particles[i].y);
                    this.ctx.lineTo(this.particles[j].x, this.particles[j].y);
                    this.ctx.stroke();
                }
            }
        }

        requestAnimationFrame(() => this.animate());
    }
}

/* ===========================
   STATE MANAGEMENT
   =========================== */
class Store {
    constructor() {
        this.state = {
            price: CONFIG.initialPrice,
            lastPrice: CONFIG.initialPrice,
            cash: CONFIG.initialCash,
            shares: CONFIG.initialShares,
            netWorth: CONFIG.initialCash + (CONFIG.initialShares * CONFIG.initialPrice),
            round: 0,
            maxRounds: 10,
            isActive: true,
            crashed: false,
            history: [],
            chat: [],
            news: [],
            orderBook: { asks: [], bids: [] },
            leaderboard: []
        };
        this.listeners = [];
    }

    subscribe(listener) {
        this.listeners.push(listener);
    }

    setState(newState) {
        // Calculate derived state
        if (newState.price !== undefined) {
            this.state.lastPrice = this.state.price;
        }
        
        this.state = { ...this.state, ...newState };
        
        // Recalculate Net Worth if needed
        if (newState.cash !== undefined || newState.shares !== undefined || newState.price !== undefined) {
            this.state.netWorth = this.state.cash + (this.state.shares * this.state.price);
        }

        this.notify();
    }

    notify() {
        this.listeners.forEach(fn => fn(this.state));
    }
}

/* ===========================
   UI CONTROLLER
   =========================== */
class UIController {
    constructor(store, audio) {
        this.store = store;
        this.audio = audio;
        this.chart = null;
        
        this.elements = {
            priceMain: document.getElementById('main-price'),
            priceDelta: document.getElementById('price-delta-val'),
            netWorth: document.getElementById('header-networth'),
            round: document.getElementById('header-round'),
            status: document.getElementById('status-indicator'),
            statusText: document.getElementById('status-text'),
            availCash: document.getElementById('avail-cash'),
            availShares: document.getElementById('avail-shares'),
            newsFeed: document.getElementById('news-feed'),
            chatMsgs: document.getElementById('chat-messages'),
            obAsks: document.getElementById('ob-asks'),
            obBids: document.getElementById('ob-bids'),
            lbList: document.getElementById('leaderboard-list'),
            spread: document.getElementById('spread-display'),
            btnBuy: document.getElementById('btn-buy'),
            btnSell: document.getElementById('btn-sell'),
            gameOverModal: document.getElementById('game-over-modal')
        };

        this.initChart();
        this.bindEvents();
        this.store.subscribe(this.render.bind(this));
    }

    initChart() {
        const ctx = document.getElementById('main-chart').getContext('2d');
        const gradient = ctx.createLinearGradient(0, 0, 0, 400);
        gradient.addColorStop(0, 'rgba(45, 127, 249, 0.5)');
        gradient.addColorStop(1, 'rgba(45, 127, 249, 0)');

        this.chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: 'MCRSH/USD',
                    data: [],
                    borderColor: '#2d7ff9',
                    backgroundColor: gradient,
                    borderWidth: 2,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    fill: true,
                    tension: 0.4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                interaction: { intersect: false, mode: 'index' },
                plugins: { legend: { display: false } },
                scales: {
                    x: { display: false },
                    y: {
                        position: 'right',
                        grid: { color: 'rgba(255,255,255,0.05)' },
                        ticks: { color: '#9ca3af', callback: v => '$' + v.toFixed(2) }
                    }
                }
            }
        });
    }

    bindEvents() {
        // Trade Buttons
        this.elements.btnBuy.addEventListener('click', () => this.executeTrade('buy'));
        this.elements.btnSell.addEventListener('click', () => this.executeTrade('sell'));
        
        // Quick Amount Inputs
        document.getElementById('buy-amount').addEventListener('input', (e) => this.updateEstimates(e.target.value, 'buy'));
        document.getElementById('sell-amount').addEventListener('input', (e) => this.updateEstimates(e.target.value, 'sell'));

        // Max Buttons
        document.getElementById('max-buy-btn').addEventListener('click', () => {
            const max = Math.floor(this.store.state.cash / this.store.state.price);
            document.getElementById('buy-amount').value = max;
            this.updateEstimates(max, 'buy');
        });
        document.getElementById('max-sell-btn').addEventListener('click', () => {
            const max = this.store.state.shares;
            document.getElementById('sell-amount').value = max;
            this.updateEstimates(max, 'sell');
        });

        // Chat
        document.getElementById('chat-send').addEventListener('click', () => this.sendChat());
        document.getElementById('chat-input').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.sendChat();
        });
    }

    updateEstimates(amount, type) {
        const total = amount * this.store.state.price;
        const el = document.getElementById(`${type}-est-total`);
        el.textContent = '$' + total.toFixed(2);
        
        if (type === 'buy' && total > this.store.state.cash) el.classList.add('text-bear');
        else if (type === 'buy') el.classList.remove('text-bear');
    }

    executeTrade(type) {
        const amount = parseInt(document.getElementById(`${type}-amount`).value);
        if (!amount || amount <= 0) return this.showToast('Invalid amount', 'error');

        // Optimistic check
        if (type === 'buy' && amount * this.store.state.price > this.store.state.cash) {
            return this.showToast('Insufficient funds', 'error');
        }
        if (type === 'sell' && amount > this.store.state.shares) {
            return this.showToast('Insufficient shares', 'error');
        }

        fetch(`/api/room/${CONFIG.roomId}/${type}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ shares: amount })
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                this.showToast(`${type.toUpperCase()} Order Executed`, 'success');
                this.audio[type === 'buy' ? 'playBuy' : 'playSell']();
                document.getElementById(`${type}-amount`).value = ''; // Reset input
                pollState(); // Force update
            } else {
                this.showToast(data.error, 'error');
                this.audio.playAlert();
            }
        });
    }

    sendChat() {
        const input = document.getElementById('chat-input');
        const msg = input.value.trim();
        if (!msg) return;

        fetch(`/api/room/${CONFIG.roomId}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: msg })
        })
        .then(r => r.json())
        .then(data => {
            if (data.success) {
                input.value = '';
                pollState();
            }
        });
    }

    showToast(msg, type = 'info') {
        const el = document.createElement('div');
        el.className = `toast-card ${type}`;
        el.innerHTML = `
            <div class="font-bold text-xs uppercase mb-1">${type}</div>
            <div>${msg}</div>
        `;
        document.getElementById('toast-wrap').appendChild(el);
        setTimeout(() => el.remove(), 4000);
    }

    render(state) {
        // 1. Header Stats
        this.elements.priceMain.textContent = state.price.toFixed(2);
        this.elements.netWorth.textContent = '$' + state.netWorth.toFixed(2);
        this.elements.round.textContent = `${state.round}/${state.maxRounds}`;
        this.elements.availCash.textContent = '$' + state.cash.toFixed(2);
        this.elements.availShares.textContent = state.shares;

        // Price Delta Styling
        const delta = ((state.price - state.lastPrice) / state.lastPrice) * 100;
        const deltaEl = document.getElementById('price-delta-wrap');
        const priceEl = this.elements.priceMain;
        
        if (state.price > state.lastPrice) {
            deltaEl.className = 'price-delta flex-center gap-sm text-bull';
            this.elements.priceDelta.textContent = `+${delta.toFixed(2)}%`;
            priceEl.className = 'main-price text-bull flash-text-up';
            this.audio.playTick();
        } else if (state.price < state.lastPrice) {
            deltaEl.className = 'price-delta flex-center gap-sm text-bear';
            this.elements.priceDelta.textContent = `${delta.toFixed(2)}%`;
            priceEl.className = 'main-price text-bear flash-text-down';
            this.audio.playTick();
        } else {
            priceEl.className = 'main-price text-white';
        }

        // 2. Chart Update
        if (state.history.length > 0) {
            this.chart.data.labels = state.history.map(h => h.round);
            this.chart.data.datasets[0].data = state.history.map(h => h.price);
            
            // Dynamic color based on trend
            const isUp = state.history[state.history.length-1].price >= state.history[0].price;
            const color = isUp ? CONSTANTS.THEME.BULL : CONSTANTS.THEME.BEAR;
            this.chart.data.datasets[0].borderColor = color;
            this.chart.data.datasets[0].backgroundColor = (ctx) => {
                const grad = ctx.chart.ctx.createLinearGradient(0, 0, 0, 400);
                grad.addColorStop(0, isUp ? 'rgba(0, 240, 144, 0.5)' : 'rgba(255, 42, 77, 0.5)');
                grad.addColorStop(1, 'rgba(0,0,0,0)');
                return grad;
            };
            this.chart.update();
        }

        // 3. Order Book
        this.renderOrderBook(state.orderBook);

        // 4. Chat
        this.renderChat(state.chat);

        // 5. News (simulated based on events)
        // Check last history event for news generation if backend doesn't provide
        // (Actually backend provides it now via chat system messages, so we filter those)
        
        // 6. Game State
        if (state.crashed) {
            this.elements.status.className = 'status-dot bg-bear animate-pulse';
            this.elements.statusText.textContent = 'CRASHED';
            this.elements.statusText.className = 'stat-value text-mono text-xs text-bear';
            this.triggerGameOver('CRASHED', state.netWorth);
        } else if (!state.isActive && state.round >= state.maxRounds) {
            this.elements.status.className = 'status-dot bg-gold';
            this.elements.statusText.textContent = 'COMPLETED';
            this.triggerGameOver('COMPLETED', state.netWorth);
        } else {
            this.elements.status.className = 'status-dot connected animate-pulse';
            this.elements.statusText.textContent = 'LIVE';
        }

        // 7. Leaderboard
        this.renderLeaderboard(state.leaderboard);
    }

    renderOrderBook(book) {
        if (!book.asks) return;
        
        // Asks (reversed to show lowest ask at bottom)
        this.elements.obAsks.innerHTML = book.asks.slice(-8).map(o => `
            <div class="ob-row">
                <div class="ob-bg ask" style="width: ${Math.min(o.vol/5, 100)}%"></div>
                <div class="ob-val text-bear text-left">${o.price.toFixed(2)}</div>
                <div class="ob-val text-right">${o.vol}</div>
                <div class="ob-val text-right text-dim">${(o.price * o.vol).toFixed(0)}</div>
            </div>
        `).join('');

        // Bids
        this.elements.obBids.innerHTML = book.bids.slice(0, 8).map(o => `
            <div class="ob-row">
                <div class="ob-bg bid" style="width: ${Math.min(o.vol/5, 100)}%"></div>
                <div class="ob-val text-bull text-left">${o.price.toFixed(2)}</div>
                <div class="ob-val text-right">${o.vol}</div>
                <div class="ob-val text-right text-dim">${(o.price * o.vol).toFixed(0)}</div>
            </div>
        `).join('');
        
        // Spread
        if (book.asks.length && book.bids.length) {
            const spread = book.asks[book.asks.length-1].price - book.bids[0].price;
            const pct = (spread / book.bids[0].price) * 100;
            this.elements.spread.textContent = `SPREAD ${spread.toFixed(2)} (${pct.toFixed(2)}%)`;
        }
    }

    renderChat(messages) {
        // Only update if length changed to avoid scroll jumping
        if (messages.length === this.elements.chatMsgs.childElementCount) return;

        this.elements.chatMsgs.innerHTML = messages.map(m => `
            <div class="chat-msg ${m.is_system ? 'system' : ''}">
                <span class="timestamp">[${m.time}]</span>
                ${!m.is_system ? `<span class="author">${m.player}</span>:` : ''}
                <span class="content">${m.message}</span>
            </div>
        `).join('');
        
        this.elements.chatMsgs.scrollTop = this.elements.chatMsgs.scrollHeight;

        // Filter system messages for news feed
        const news = messages.filter(m => m.is_system);
        this.elements.newsFeed.innerHTML = news.map(n => `
            <div class="news-item">
                <span class="news-time">${n.time}</span>
                <div class="news-headline">${n.message}</div>
                <span class="news-tag bg-blue text-blue bg-opacity-10">MARKET</span>
            </div>
        `).join('');
    }

    renderLeaderboard(lb) {
        this.elements.lbList.innerHTML = lb.map((p, i) => `
            <div class="flex-row justify-between p-2 border-b border-white/5 ${p.is_current ? 'bg-blue/10' : ''}">
                <div class="flex-center gap-sm">
                    <span class="text-dim text-mono w-4">#${i+1}</span>
                    <span class="font-bold text-sm ${p.is_current ? 'text-blue' : ''}">${p.player_name}</span>
                </div>
                <span class="text-mono text-sm">$${p.total_value.toFixed(2)}</span>
            </div>
        `).join('');
    }

    triggerGameOver(title, score) {
        const modal = this.elements.gameOverModal;
        if (modal.classList.contains('active')) return;
        
        document.getElementById('go-title').textContent = title === 'CRASHED' ? 'MARKET COLLAPSE' : 'SESSION CLOSED';
        document.getElementById('go-score').textContent = '$' + score.toFixed(2);
        
        if (title === 'CRASHED') {
            this.audio.playCrash();
        } else {
            this.audio.playAlert();
        }
        
        setTimeout(() => modal.classList.add('active'), 1500);
    }
}

/* ===========================
   BOOTSTRAP
   =========================== */
const store = new Store();
const audio = new AudioEngine();
const ui = new UIController(store, audio);
const particles = new ParticleSystem('particle-canvas');

// Sound toggle global
window.toggleSound = () => {
    const s = audio.toggle();
    ui.showToast(s ? 'Sound Enabled' : 'Sound Muted', 'info');
};

// Polling Loop
async function pollState() {
    try {
        const res = await fetch(`/api/room/${CONFIG.roomId}/state`);
        const data = await res.json();
        
        if (data.success) {
            store.setState({
                price: data.room.current_price,
                round: data.room.round_number,
                isActive: data.room.is_active,
                crashed: !!data.room.crash_occurred,
                cash: data.player.cash,
                shares: data.player.shares,
                history: data.price_history,
                chat: data.chat,
                orderBook: data.order_book,
                leaderboard: data.leaderboard
            });
        } else if (data.error === 'Session expired') {
            window.location.href = '/';
        }
    } catch (e) {
        console.error("Poll error:", e);
    }
}

setInterval(pollState, CONSTANTS.POLL_INTERVAL);
pollState(); // Init
