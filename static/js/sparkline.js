/**
 * Premium Sparkline Renderer — gradient fill, smooth curves, pulsing dot.
 * Pure vanilla JS, no dependencies.
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
    const pad = 2;

    ctx.clearRect(0, 0, w, h);

    // Build points
    const points = [];
    for (let i = 0; i < data.length; i++) {
        const x = (i / (data.length - 1)) * w;
        const y = h - ((data[i] - min) / range) * (h - pad * 2) - pad;
        points.push({ x, y });
    }

    if (points.length < 2) return;

    // Draw smooth curve using quadratic bezier through midpoints
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = lineWidth;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';

    ctx.moveTo(points[0].x, points[0].y);
    for (let i = 1; i < points.length - 1; i++) {
        const midX = (points[i].x + points[i + 1].x) / 2;
        const midY = (points[i].y + points[i + 1].y) / 2;
        ctx.quadraticCurveTo(points[i].x, points[i].y, midX, midY);
    }
    // Final segment
    const last = points[points.length - 1];
    ctx.lineTo(last.x, last.y);
    ctx.stroke();

    // Gradient fill under curve
    if (fill) {
        ctx.lineTo(w, h);
        ctx.lineTo(0, h);
        ctx.closePath();

        const gradient = ctx.createLinearGradient(0, 0, 0, h);
        gradient.addColorStop(0, hexToRgba(color, 0.25));
        gradient.addColorStop(0.6, hexToRgba(color, 0.06));
        gradient.addColorStop(1, hexToRgba(color, 0.0));
        ctx.fillStyle = gradient;
        ctx.fill();
    }

    // Pulsing dot at latest point
    const lastPt = points[points.length - 1];
    ctx.beginPath();
    ctx.arc(lastPt.x, lastPt.y, 2.5, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();

    // Outer glow ring
    ctx.beginPath();
    ctx.arc(lastPt.x, lastPt.y, 4.5, 0, Math.PI * 2);
    ctx.strokeStyle = hexToRgba(color, 0.35);
    ctx.lineWidth = 1;
    ctx.stroke();
}

/**
 * Convert hex color to rgba string.
 */
function hexToRgba(hex, alpha) {
    // Handle named colors or already-rgb strings
    if (hex.startsWith('rgb')) {
        return hex.replace(')', `, ${alpha})`).replace('rgb', 'rgba');
    }
    hex = hex.replace('#', '');
    if (hex.length === 3) {
        hex = hex.split('').map(c => c + c).join('');
    }
    const r = parseInt(hex.substring(0, 2), 16);
    const g = parseInt(hex.substring(2, 4), 16);
    const b = parseInt(hex.substring(4, 6), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
