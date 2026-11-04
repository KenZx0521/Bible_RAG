// 建 DOM 的小工具。文字一律走 textContent、屬性一律走 setAttribute，沒有任何 HTML 字串入口：
// 答案、段落標題、人名都是外部資料，不能有機會被當成 HTML 解析。

function setAttributes(node, attrs) {
  Object.entries(attrs).forEach(([name, value]) => {
    if (value === true) node.setAttribute(name, '');
    else if (value !== false && value !== null && value !== undefined) node.setAttribute(name, String(value));
  });
}

/** el('button', {class:'x', text:'按我', on:{click}}, [子節點…])；子節點可以是 null，會被略過。 */
export function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  const { text, on = {}, ...attrs } = props;
  setAttributes(node, attrs);
  if (text !== undefined) node.textContent = text;
  Object.entries(on).forEach(([type, handler]) => node.addEventListener(type, handler));
  node.append(...children.filter(Boolean));
  return node;
}

/** 關聯圖重畫後，依資料屬性找回同一顆按鈕（節點或親屬關係字）；同一對人可能有兩條關係，要連 type 一起比。 */
export function findRedrawn(element) {
  const { id, from, to, type } = element.dataset;
  if (id) return document.querySelector(`.node[data-id="${CSS.escape(id)}"]`);
  if (from) return document.querySelector(`.edge-label[data-from="${CSS.escape(from)}"][data-to="${CSS.escape(to)}"][data-type="${CSS.escape(type)}"]`);
  return null;
}

/** 字元（code point）數，與 server、backend 的 500 字上限算法一致。 */
export function charCount(text) {
  return [...text].length;
}
