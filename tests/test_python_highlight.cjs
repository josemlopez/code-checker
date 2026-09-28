const test = require('node:test');
const assert = require('node:assert/strict');
const {lines, render} = require('../web/python-highlight.js');
const decode = html => html.replace(/<[^>]+>/g, '').replace(/&(amp|lt|gt|quot|#39);/g,
  (_, name) => ({amp:'&',lt:'<',gt:'>',quot:'"','#39':"'"}[name]));

test('Python highlighting preserves source, multiline strings and escaped HTML', () => {
  const source = 'async def acción(x: int = 0xFF):\n    """A multiline\n    <script>alert(1)</script> # docstring"""\n    # <img onerror="bad()">\n    return f"value={x}"\n';
  const result = lines(source);
  assert.equal(result.map(decode).join('\n'), source);
  assert.match(result[0], /py-keyword/);
  assert.match(result[0], /py-definition">acción/);
  assert.match(result[0], /py-number">0xFF/);
  assert.match(result[2], /py-string/);
  assert.doesNotMatch(result[2], /py-comment/);
  assert.match(result[3], /py-comment/);
  assert.ok(!result.join('').includes('<script>'));
  assert.ok(!result.join('').includes('<img'));
  assert.match(render(source, 42), /aria-hidden="true">42<\/span>/);
});

test('incomplete strings, raw strings, escapes and blank lines preserve text', () => {
  for (const source of ['', '\n\n', 'x = r"a\\\\b"\ny = .5e-2', 'x = "a\\"b"\n', 'x = "unfinished\npass', '"""unfinished\ncontinued']) {
    assert.equal(lines(source).map(decode).join('\n'), source);
  }
});
