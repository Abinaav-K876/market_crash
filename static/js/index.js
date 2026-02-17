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