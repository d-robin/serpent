/** Move an element to <body> so no ancestor (transform, filter, overflow) can affect `position: fixed`. */
export function portal(node: HTMLElement) {
  document.body.appendChild(node);
  return { destroy() { node.remove(); } };
}
