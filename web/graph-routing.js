'use strict';

// Nodes occupy aligned rows/columns, with >= 60px gutters and 40px outer margins.
// Routes use those gutters; a segment may touch a port but never enter a card.
const GraphRouting = (() => {
  function intersects(a, b, box) {
    if (a[0] === b[0]) return a[0] > box.x && a[0] < box.x + box.width &&
      Math.max(a[1], b[1]) > box.y && Math.min(a[1], b[1]) < box.y + box.height;
    return a[1] > box.y && a[1] < box.y + box.height &&
      Math.max(a[0], b[0]) > box.x && Math.min(a[0], b[0]) < box.x + box.width;
  }
  function compact(points) {
    const result = [];
    for (const p of points) {
      const last = result.at(-1), before = result.at(-2);
      if (last && last[0] === p[0] && last[1] === p[1]) continue;
      if (before && ((before[0] === last[0] && last[0] === p[0]) ||
          (before[1] === last[1] && last[1] === p[1]))) result.pop();
      result.push(p);
    }
    return result;
  }
  function routeEdges(positions, edges, width, height) {
    const boxes = Object.values(positions).map(p => ({...p, width, height}));
    const clear = points => points.slice(1).every((p, i) => !boxes.some(b => intersects(points[i], p, b)));
    const unique = [...new Map(edges.filter(e => (e.source !== e.target || e.kind === 'call') && positions[e.source] && positions[e.target])
      .map(e => [JSON.stringify([e.source, e.target, e.context || '']), e])).values()];
    return unique.map((edge, index) => {
      const a = positions[edge.source], b = positions[edge.target];
      const lane = 12 + (index % 5) * 3, port = ((index % 7) - 3) * 5;
      let points;
      if (edge.source === edge.target) {
        points = [[a.x+width,a.y+30],[a.x+width+lane,a.y+30],
          [a.x+width+lane,a.y+76],[a.x+width,a.y+76]];
      } else if (a.y === b.y) {
        const sign = b.x > a.x ? 1 : -1;
        const start = [a.x + (sign > 0 ? width : 0), a.y + height / 2 + port];
        const end = [b.x + (sign > 0 ? 0 : width), b.y + height / 2 + port];
        points = [start, end];
        if (!clear(points)) points = [start, [start[0] + sign * lane, start[1]],
          [start[0] + sign * lane, a.y - lane], [end[0] - sign * lane, a.y - lane],
          [end[0] - sign * lane, end[1]], end];
      } else {
        const sign = b.y > a.y ? 1 : -1;
        const start = [a.x + width / 2 + port, a.y + (sign > 0 ? height : 0)];
        const end = [b.x + width / 2 + port, b.y + (sign > 0 ? 0 : height)];
        const sy = start[1] + sign * lane, ty = end[1] - sign * lane;
        points = [start, [start[0], sy], [end[0], sy], end];
        if (!clear(points)) {
          const channel = b.x >= a.x ? a.x + width + lane : a.x - lane;
          points = [start, [start[0], sy], [channel, sy], [channel, ty], [end[0], ty], end];
        }
      }
      points = compact(points);
      // Fail visibly during development if a layout stops honoring its gutters.
      if (!clear(points)) throw new Error('El trazado de dependencias necesita más espacio entre cajas.');
      return {...edge, points, path: points.map((p, i) => `${i ? 'L' : 'M'}${p[0]},${p[1]}`).join(' ')};
    });
  }
  return {routeEdges};
})();
if (typeof module !== 'undefined') module.exports = GraphRouting;
