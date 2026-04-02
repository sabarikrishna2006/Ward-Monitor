/**
 * Lightweight sparkline renderer — pure vanilla JS, no dependencies.
 * Draws a mini line chart on a canvas element.
 */
function renderSparkline(canvas, data, options = {}) {
    if (!canvas || !data || data.length === 0) return;

    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth || canvas.width;
    const h = canvas.clientHeight || canvas.height;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    ctx.scale(dpr, dpr);

    const color = options.color || '#3b82f6';
    const lineWidth = options.lineWidth || 1.5;
    const fill = options.fill !== false;

    const min = options.min !== undefined ? options.min : Math.min(...data);
    const max = options.max !== undefined ? options.max : Math.max(...data);
    const range = max - min || 1;

    ctx.clearRect(0, 0, w, h);

    // Draw trend line
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = lineWidth;
    ctx.lineJoin = 'round';

    for (let i = 0; i < data.length; i++) {
        const x = (i / (data.length - 1)) * w;
        const y = h - ((data[i] - min) / range) * (h - 2) - 1;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Fill area under the line
    if (fill) {
        ctx.lineTo(w, h);
        ctx.lineTo(0, h);
        ctx.closePath();
        ctx.fillStyle = color.replace(')', ', 0.15)').replace('rgb', 'rgba');
        ctx.globalAlpha = 0.3;
        ctx.fill();
        ctx.globalAlpha = 1;
    }
}
