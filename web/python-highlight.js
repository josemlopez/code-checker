'use strict';

// Presentation only: source is escaped, never evaluated or inserted as markup.
const PythonHighlight = (() => {
  const keywords = new Set('False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield match case type'.split(' '));
  const builtins = new Set('abs all any bool bytes callable classmethod dict enumerate Exception float frozenset getattr hasattr int isinstance issubclass iter len list map max min next object open print property range repr reversed round set setattr sorted staticmethod str sum super tuple type zip self cls'.split(' '));
  const escape = value => value.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function lines(source) {
    const output = [''];
    let i = 0, definition = false;
    function emit(value, kind) {
      value.split('\n').forEach((part, index) => {
        if (index) output.push('');
        output[output.length - 1] += kind && part ? `<span class="py-${kind}">${escape(part)}</span>` : escape(part);
      });
    }
    while (i < source.length) {
      const rest = source.slice(i);
      let value, kind;
      const quote = rest.match(/^(?:[rRuUbBfF]{1,2})?("""|'''|"|')/);
      if (quote) {
        const delimiter = quote[1];
        let end = i + quote[0].length;
        while (end < source.length) {
          if (source[end] === '\\') { end = Math.min(source.length, end + 2); continue; }
          if (source.startsWith(delimiter, end)) { end += delimiter.length; break; }
          if (delimiter.length === 1 && source[end] === '\n') break;
          end++;
        }
        value = source.slice(i, end);kind = 'string';
      } else if (rest[0] === '#') {
        value = rest.match(/^[^\n]*/)[0];kind = 'comment';
      } else if (/^\s/.test(rest)) {
        value = rest.match(/^\s+/)[0];
      } else if (/^[\p{L}_]/u.test(rest)) {
        value = rest.match(/^[\p{L}\p{N}_]+/u)[0];
        kind = definition ? 'definition' : keywords.has(value) ? 'keyword' : builtins.has(value) ? 'builtin' : null;
        definition = value === 'def' || value === 'class';
      } else if (/^\d|^\.\d/.test(rest)) {
        value = rest.match(/^(?:0[xX][\da-fA-F_]+|0[bB][01_]+|0[oO][0-7_]+|(?:\d[\d_]*(?:\.[\d_]*)?|\.[\d_]+)(?:[eE][+-]?[\d_]+)?[jJ]?)/)[0];
        kind = 'number';
      } else {
        value = rest[0];kind = /[+\-*/%=<>!&|^~:@]/.test(value) ? 'operator' : null;
      }
      emit(value, kind);i += value.length;
    }
    return output;
  }
  function render(source, firstLine=1) {
    return lines(source).map((line, i) => `<div class="code-line"><span class="line-no" aria-hidden="true">${firstLine+i}</span><span class="code-text">${line || ' '}</span></div>`).join('');
  }
  return {lines, render};
})();
if (typeof module !== 'undefined') module.exports = PythonHighlight;
