/** Render server-sanitized problem Markdown and its KaTeX math nodes. */
let katexPromise;

/** Remove repeated numeric values from previously saved Luogu resource limits. */
export function normalizeProblemStatementHtml(html) {
  return String(html || "").replace(
    /(时间限制：|内存限制：)(\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)+)(\s*(?:ms|MiB))/g,
    (_, label, values, unit) => `${label}${[...new Set(values.split("-"))].join("-")}${unit}`,
  );
}

export async function renderProblemMath(root) {
  if (!katexPromise) {
    katexPromise = Promise.all([
      import("./vendor/katex/katex.mjs?v=0.19.1"),
    ]).then(([module]) => module.default);
  }
  const katex = await katexPromise;
  for (const node of root.querySelectorAll(".math.inline, .math.block")) {
    katex.render(node.textContent, node, {
      displayMode: node.classList.contains("block"),
      throwOnError: false,
      output: "htmlAndMathml",
    });
  }
}

export function appendProblemStatement(container, html) {
  const content = document.createElement("div");
  content.className = "problem-statement-content markdown-content";
  content.innerHTML = normalizeProblemStatementHtml(html);
  container.append(content);
  void renderProblemMath(content).catch(() => {
    content.classList.add("math-render-error");
  });
}
