// Auto-uppercase room ID + strip invalid chars
document.getElementById('room_id')?.addEventListener('input', function () {
    this.value = this.value.toUpperCase().replace(/[^A-Z0-9]/g, '');
});

// Show / hide inline field error
function setError(id, show) {
    const el = document.getElementById(id);
    if (el) el.classList.toggle('show', show);
}

// Clear error on input
document.querySelectorAll('.form-input').forEach(input => {
    input.addEventListener('input', function () {
        const map = {
            player_name_create: 'create-name-error',
            player_name_join:   'join-name-error',
            room_id:            'join-room-error',
        };
        const errId = map[this.id];
        if (errId) setError(errId, false);
    });
});

// Create form
document.getElementById('create-form')?.addEventListener('submit', function (e) {
    const name = this.querySelector('[name="player_name"]').value.trim();
    const ok = name.length >= 2 && name.length <= 15;
    setError('create-name-error', !ok);
    if (!ok) e.preventDefault();
});

// Join form
document.getElementById('join-form')?.addEventListener('submit', function (e) {
    const name   = this.querySelector('[name="player_name"]').value.trim();
    const roomId = this.querySelector('[name="room_id"]').value.trim();

    const nameOk = name.length >= 2 && name.length <= 15;
    const roomOk = /^[A-Z0-9]{6}$/.test(roomId);

    setError('join-name-error', !nameOk);
    setError('join-room-error', !roomOk);

    if (!nameOk || !roomOk) e.preventDefault();
});
