// 文書の中の検索（ビューア）。エディタの検索（find.js）と同じ使い方になるようにしてある。
//
// - 一致した箇所は、すべてハイライトし、「n / 全部で m 件」を出す。大文字小文字の区別と、正規表現を選べる。
// - 画面に出ている文書の文字を探す。太字の途中などで文字が複数の要素に分かれていても、つなげて探す
//   （段落や表のセルなど、ブロックの境目には改行を挟むので、ブロックをまたぐ一致は出ない）。
// - 図（Mermaid・Vega-Lite の SVG）の中の文字は対象にしない。
// - 長さ0の一致（`^` だけなど）は、無かったことにする。
// - ハイライトは <mark class="find-hit"> を挟んで行い、閉じたら元の文書に戻す（文書の中身は変えない）。
const MdSearch = (() => {
  const CAP = 10000;                       // 数える上限（巨大な文書でも固まらないように）
  const BLOCKS = 'p,li,ul,ol,h1,h2,h3,h4,h5,h6,td,th,tr,table,pre,blockquote,div,section,figure,figcaption,summary,details,dt,dd,dl,hr,body';

  function build(query, caseSensitive, useRegex) {
    if (!query) return { re: null };
    try {
      const src = useRegex ? query : query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      return { re: new RegExp(src, 'gm' + (caseSensitive ? '' : 'i')) };
    } catch (e) {
      return { re: null, error: String(e.message || e).replace(/^Invalid regular expression: /, '') };
    }
  }

  function matchesOf(text, re) {
    const out = []; re.lastIndex = 0; let m;
    while ((m = re.exec(text))) {
      if (m[0].length === 0) { re.lastIndex++; continue; }
      out.push({ index: m.index, length: m[0].length });
      if (out.length >= CAP) break;
    }
    return out;
  }

  // 文書の文字を1本の文字列につなぎ、どの文字がどの文字ノードのどこにあるかを控える
  function collect(root) {
    const nodes = []; let text = '', lastBlock = null;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(n) {
        const p = n.parentElement;
        if (!p || !n.nodeValue) return NodeFilter.FILTER_REJECT;
        if (p.closest('svg, script, style, noscript')) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const block = node.parentElement.closest(BLOCKS);
      if (lastBlock !== null && block !== lastBlock) text += '\n';          // ブロックの境目をまたぐ一致を出さない
      nodes.push({ node, start: text.length });
      text += node.nodeValue;
      lastBlock = block;
    }
    return { text, nodes };
  }

  // 一致のそれぞれを <mark> で囲む。後ろの一致から処理すると、前の位置がずれない。戻り値は、一致ごとの <mark> の並び
  function highlight(nodes, matches) {
    const marks = new Array(matches.length);
    for (let k = matches.length - 1; k >= 0; k--) {
      const { index, length } = matches[k];
      const end = index + length, mine = [];
      for (let i = nodes.length - 1; i >= 0; i--) {
        const { node, start } = nodes[i];
        const stop = start + node.nodeValue.length;
        if (stop <= index || start >= end) continue;
        const s = Math.max(index, start) - start, e = Math.min(end, stop) - start;
        if (e < node.nodeValue.length) node.splitText(e);
        const target = s > 0 ? node.splitText(s) : node;
        const mark = document.createElement('mark');
        mark.className = 'find-hit';
        target.parentNode.insertBefore(mark, target);
        mark.appendChild(target);
        mine.unshift(mark);
      }
      marks[k] = mine;
    }
    return marks;
  }

  function create(cfg) {
    // cfg: { root: () => 本文の要素, ui: { bar, q, cs, re, count }, hasDocument: () => 文書が開いているか }
    const ui = cfg.ui;
    let marks = [], cur = -1, timer = null, lastError = null;

    function clearMarks() {
      const touched = new Set();
      for (const group of marks) for (const m of group) {
        const p = m.parentNode;
        if (!p) continue;
        while (m.firstChild) p.insertBefore(m.firstChild, m);
        p.removeChild(m);
        touched.add(p);
      }
      touched.forEach(p => p.normalize());               // 分けた文字ノードを、元のとおりにつなぎ直す
      marks = []; cur = -1;
    }

    function setCurrent(i) {
      if (cur >= 0 && marks[cur]) marks[cur].forEach(m => m.classList.remove('cur'));
      cur = i;
      if (cur >= 0 && marks[cur]) {
        marks[cur].forEach(m => m.classList.add('cur'));
        marks[cur][0].scrollIntoView({ block: 'center', inline: 'nearest' });
      }
    }

    function updateCount(note) {
      let t;
      if (lastError) t = '正規表現が正しくありません';
      else if (!ui.q.value) t = '';
      else if (!cfg.hasDocument()) t = '開いている文書がありません';
      else if (!marks.length) t = '見つかりません';
      else t = (cur >= 0 ? `${cur + 1} / ` : '') + `${marks.length}${marks.length >= CAP ? '+' : ''} 件`;
      ui.count.textContent = note ? `${t}（${note}）` : t;
      ui.count.classList.toggle('bad', !marks.length && !!ui.q.value && cfg.hasDocument());
    }

    // 検索語・オプション・文書が変わったら、ハイライトと件数を作り直す。first: 最初の一致へ移る
    function refresh(first) {
      clearTimeout(timer);
      clearMarks();
      const root = cfg.root();
      const b = build(ui.q.value, ui.cs.checked, ui.re.checked);
      lastError = b.error || null;
      ui.q.classList.toggle('bad', !!b.error);
      if (b.re && root && cfg.hasDocument()) {
        const { text, nodes } = collect(root);
        marks = highlight(nodes, matchesOf(text, b.re));
        if (first && marks.length) setCurrent(0);
      }
      updateCount();
    }
    const schedule = () => { clearTimeout(timer); timer = setTimeout(() => refresh(true), 150); };

    // dir: 1 = 次へ、-1 = 前へ。端まで来たら反対側へ戻る
    function step(dir) {
      if (!ui.q.value) return false;
      if (!marks.length) refresh(false);
      if (!marks.length) return false;
      let i = cur + dir, note = '';
      if (cur < 0) i = dir > 0 ? 0 : marks.length - 1;
      else if (i >= marks.length) { i = 0; note = '先頭に戻りました'; }
      else if (i < 0) { i = marks.length - 1; note = '末尾に戻りました'; }
      setCurrent(i);
      updateCount(note);
      return true;
    }

    function open() {
      ui.bar.hidden = false;
      const root = cfg.root(), selection = window.getSelection();
      const range = selection && selection.rangeCount ? selection.getRangeAt(0) : null;
      const sel = range && root && root.contains(range.commonAncestorContainer) ? range.toString() : '';   // 本文の中で選んでいる文字だけ
      if (sel && !sel.includes('\n') && sel.length <= 200) ui.q.value = sel;                              // 検索する文字列に入れる
      ui.q.focus(); ui.q.select();
      refresh(true);
    }
    function close() {
      ui.bar.hidden = true;
      clearMarks();
    }
    const isOpen = () => !ui.bar.hidden;

    ui.q.addEventListener('input', schedule);
    ui.cs.addEventListener('change', () => refresh(true));
    ui.re.addEventListener('change', () => refresh(true));
    return { open, close, isOpen, step, refresh, count: () => marks.length, current: () => cur };
  }

  return { create, build, matchesOf, collect };
})();
