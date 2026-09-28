const test = require('node:test');
const assert = require('node:assert/strict');
const {routeEdges} = require('../web/graph-routing.js');

// Check the result geometrically, independently of the router's collision helper.
function checkRoutes(positions, edges, width) {
  const routes = routeEdges(positions, edges, width, 106);
  for (const route of routes) {
    const first = route.points[0], last = route.points.at(-1);
    for (const [id, p] of [[route.source, first], [route.target, last]]) {
      const box = positions[id];
      assert.ok(p[0] >= box.x && p[0] <= box.x + width && p[1] >= box.y && p[1] <= box.y + 106);
      assert.ok(p[0] === box.x || p[0] === box.x + width || p[1] === box.y || p[1] === box.y + 106);
    }
    for (let i = 1; i < route.points.length; i++) {
      const a = route.points[i - 1], b = route.points[i];
      assert.ok(a[0] === b[0] || a[1] === b[1], 'segments must be orthogonal');
      assert.notDeepEqual(a, b, 'no zero-length segments');
      for (const box of Object.values(positions)) {
        const overlapX = Math.max(a[0], b[0]) > box.x && Math.min(a[0], b[0]) < box.x + width;
        const overlapY = Math.max(a[1], b[1]) > box.y && Math.min(a[1], b[1]) < box.y + 106;
        assert.ok(!(overlapX && overlapY), `route ${route.source} → ${route.target} enters a box`);
      }
      assert.ok(b[0] >= 0 && b[1] >= 0, 'outer gutters remain inside canvas');
    }
  }
  return routes;
}

for (const [width, columns, count] of [[230, 3, 12], [218, 4, 30], [230, 2, 2]]) {
  test(`all directed pairs, ${count} cards of width ${width}`, () => {
    const positions = Object.fromEntries(Array.from({length: count}, (_, i) => [String(i),
      {x: 40 + (i % columns) * (width + 60), y: 40 + Math.floor(i / columns) * 166}]));
    const edges = Object.keys(positions).flatMap(source => Object.keys(positions)
      .filter(target => source !== target).map(target => ({source, target})));
    const routes = checkRoutes(positions, edges, width);
    assert.equal(routes.length, count * (count - 1));
    assert.deepEqual(routes, routeEdges(positions, edges, width, 106), 'deterministic routing');
  });
}

test('sparse layers, reciprocal edges, duplicates and missing endpoints', () => {
  const positions = {a:{x:40,y:40}, b:{x:40,y:538}, c:{x:596,y:206}};
  const edges = [{source:'a',target:'b'}, {source:'b',target:'a'}, {source:'c',target:'b'},
    {source:'a',target:'b'}, {source:'a',target:'a'}, {source:'a',target:'missing'}];
  const routes = checkRoutes(positions, edges, 218);
  assert.equal(routes.length, 3);
  assert.deepEqual(routeEdges({}, [], 230, 106), []);
});

test('recursive call loops stay outside the function card', () => {
  const routes = checkRoutes({a:{x:40,y:120},b:{x:330,y:120}}, [{source:'a',target:'a',kind:'call'}], 230);
  assert.equal(routes.length, 1);
  assert.equal(routes[0].points.length, 4);
});
